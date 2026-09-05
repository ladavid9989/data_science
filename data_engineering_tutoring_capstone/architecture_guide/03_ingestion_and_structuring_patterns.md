# 03 — Ingestion and Structuring Patterns

This module shows the same business data at successive boundaries. The snippets
are compact patterns; the executable implementations are in Notebooks 01 and 02.

## Source access is not transformation

| Source | How data is accessed | What the ingestion boundary should preserve |
|---|---|---|
| REST API | HTTP request with pagination and timeout | Response body, request ID, cursor, source URL, retrieval time |
| JSON/JSONL file | File or object read | Original bytes/lines, file path, checksum, delivery timestamp |
| Amazon S3 | Object key or prefix | Bucket/key, object version or ETag when appropriate, partition prefix |
| Athena | SQL reads data in S3 through catalog metadata | Query ID, SQL, input location, bytes scanned, result location |
| Database CDC | Transaction log or managed CDC service | Primary key, operation, source sequence/log position, commit time |
| Kafka | Consumer polls a topic partition | Topic, partition, offset, key, event time, headers |

Athena does not fetch a REST API. An ingestion process first writes API data to
S3; Athena then queries the data in place.

## Pattern A — Cursor-paginated REST extraction

```python
cursor = None

while True:
    params = {"limit": 100}
    if cursor is not None:
        params["cursor"] = cursor
    if committed_watermark is not None:
        params["updated_after"] = committed_watermark

    envelope = get_json_with_retry(session, api_url, params=params)
    records = envelope["data"]

    # Preserve the exact source page before business transformation.
    atomic_write_json(next_bronze_page_path(), envelope)

    cursor = envelope.get("next_cursor")
    if cursor is None:
        break
```

```text
GET first page
  ↓ save original response
next_cursor present? ── yes ──► GET next page
  │
  no
  ↓
write successful manifest
  ↓
commit high-watermark checkpoint
```

The cursor moves within one extraction run. The high watermark connects one
successful run to the next.

## Pattern B — Atomic checkpoint commit

```python
def atomic_write_json(path, payload):
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary_path, path)
```

The production-quality helper in `src/capstone_utils.py` also flushes and syncs
the temporary file and cleans it up after failure.

```text
Unsafe: checkpoint advances → data write fails → data can be skipped

Safer: data durable → manifest durable → atomic checkpoint replacement
```

For sources where multiple records can share an update timestamp, prefer a
composite position such as `(updated_at, order_id)` or a source log sequence.

## Pattern C — Explicit schema for nested JSON

```python
order_schema = T.StructType([
    T.StructField("order_id", T.StringType()),
    T.StructField("customer_id", T.StringType()),
    T.StructField("customer", customer_schema),
    T.StructField("total_amount", T.StringType()),
    T.StructField("items", T.ArrayType(item_schema)),
])

envelopes = (
    spark.read
    .schema(envelope_schema)
    .option("multiLine", True)
    .json(bronze_page_paths)
    .withColumn("source_file", F.input_file_name())
)
```

Read uncertain monetary values as strings first. Keep the raw value, then use a
safe cast so invalid values become visible quality failures instead of crashing
the complete batch.

## Pattern D — Normalize schema versions and validate

```python
normalized = envelopes.select(
    F.col("order.order_id").alias("order_id"),
    F.coalesce(
        F.col("order.customer_id"),       # API schema v1
        F.col("order.customer.id"),       # API schema v2
    ).alias("customer_id"),
    F.col("order.total_amount").alias("raw_total_amount"),
    F.col("order.total_amount")
        .try_cast("decimal(18,2)")
        .alias("total_amount"),
    F.col("source_file"),
)

classified = normalized.withColumn(
    "quarantine_reason",
    F.when(F.col("order_id").isNull(), "missing_order_id")
     .when(F.col("customer_id").isNull(), "missing_customer_id")
     .when(F.col("total_amount").isNull(), "invalid_total_amount"),
)
```

```text
Nested source JSON
  ↓ explicit schema and lineage
Normalized typed rows
  ↓ quality rules
  ├── valid candidate
  └── quarantine row + reason + original value + source file
```

## Pattern E — Convert one nested order into relational tables

```text
One API order
├── order_id
├── customer
└── items[]
      ├── item 1
      └── item 2
          ↓
orders:      one row per order
order_items: one row per order line
```

```python
orders = valid_orders.drop("items")

order_items = (
    valid_orders
    .select(
        "order_id",
        "event_date",
        F.posexplode("items").alias("line_offset", "item"),
    )
    .select(
        "order_id",
        (F.col("line_offset") + 1).alias("line_number"),
        F.col("item.sku").alias("sku"),
        F.col("item.quantity").cast("long").alias("quantity"),
        F.col("item.unit_price").try_cast("decimal(18,2)").alias("unit_price"),
        "event_date",
    )
)
```

## Pattern F — Query S3 data through Athena

Assume an external/catalog table already points to the S3 Bronze or Silver
location. Athena queries the files; it does not move them into Athena.

```sql
SELECT
    event_date,
    COUNT(*) AS order_count,
    SUM(total_amount) AS gross_revenue
FROM lakehouse.silver_orders
WHERE event_date BETWEEN DATE '2026-01-01' AND DATE '2026-01-07'
GROUP BY event_date
ORDER BY event_date;
```

The `event_date` filter matters when the S3 table is partitioned by that column.
Select only required columns and inspect bytes scanned.

## Pattern G — Apply CDC deterministically

```text
CDC events for one order
sequence 101: U → paid
sequence 102: U → shipped
sequence 102: U → shipped (duplicate delivery)
          ↓
keep the greatest deterministic sequence
          ↓
MERGE / upsert into current snapshot
          ↓
one row: shipped
```

Portable conceptual SQL:

```sql
WITH ranked_changes AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (
            PARTITION BY order_id
            ORDER BY sequence_no DESC
        ) AS rn
    FROM staged_changes AS c
),
latest_changes AS (
    SELECT *
    FROM ranked_changes
    WHERE rn = 1
)
-- Use the target platform's MERGE syntax:
-- D deletes the key; I/U insert or update the key.
SELECT * FROM latest_changes;
```

Production CDC also needs a durable committed source position. Keeping only the
latest event inside one batch is not sufficient to reject an older future batch.

## Pattern H — Publish a business mart

```sql
CREATE OR REPLACE TABLE mart_daily_sales AS
SELECT
    order_date,
    COUNT(*) AS order_count,
    COUNT(DISTINCT customer_id) AS purchasing_customers,
    SUM(total_amount) AS gross_revenue,
    AVG(total_amount) AS average_order_value
FROM fact_order
GROUP BY order_date;
```

The transformation path is now explicit:

```text
REST / JSON / CDC
  ↓ reliable ingestion and immutable Bronze
Nested semi-structured data
  ↓ schema, safe casting, quality, deduplication, flattening
Typed Silver tables
  ↓ fact/dimension modeling and business aggregation
Gold mart
  ↓ stable metric definitions
Dashboard / BI
```

