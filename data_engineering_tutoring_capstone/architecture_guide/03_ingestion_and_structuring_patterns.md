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

**Kafka를 쉽게 이해하면:** Producer가 메시지를 Kafka의 topic/partition에 넣으면,
Consumer는 새 메시지가 있는지 확인하여 가져옵니다. Offset은 Consumer가 어디까지
처리했는지 나타내는 책갈피이며, 처리한 데이터는 S3나 warehouse 같은 sink에 저장됩니다.

```text
Producer → Kafka topic/partition → Consumer → S3 / warehouse (sink)
                                      ↑
                         offset으로 처리 위치를 기억
```

Athena does not fetch a REST API. An ingestion process first writes API data to
S3; Athena then queries the data in place.

**Athena 흐름을 쉽게 이해하면:** Athena가 REST API를 직접 호출하는 것이 아닙니다.
Python, Lambda, 또는 Airflow가 API 데이터를 수집해 S3에 JSON/Parquet로 저장하고,
Athena는 그 S3 파일을 옮기지 않은 채 SQL로 조회합니다.

```text
REST API → Python / Lambda / Airflow → Amazon S3 → Amazon Athena → BI
              API 수집                 파일 저장       SQL 조회
```

## Pattern A — Cursor-paginated REST extraction

**한국어 설명:** API가 한 번에 모든 데이터를 주지 않을 때, cursor를 다음 페이지의
위치표처럼 사용해 끝까지 반복 수집합니다. 받은 각 응답은 변형하기 전에 Bronze에 그대로 저장합니다.

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

**한국어 설명:** Checkpoint는 이전 실행에서 어디까지 성공했는지 기록하는 책갈피입니다.
데이터 저장이 모두 끝난 뒤 임시 파일을 최종 파일로 한 번에 교체하여, 실패 시 데이터가 건너뛰어지는 일을 막습니다.

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

**한국어 설명:** 중첩 JSON의 필드와 데이터 타입을 미리 설계도처럼 정의합니다.
Spark의 자동 추측에만 맡기지 않아 타입 변화나 잘못된 값을 더 쉽게 발견할 수 있습니다.

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

**한국어 설명:** 서로 다른 API 버전의 필드를 하나의 표준 컬럼 구조로 통합합니다.
필수값 누락이나 숫자 변환 실패 데이터는 버리지 않고, 이유와 함께 quarantine으로 분리합니다.

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

**한국어 설명:** 주문 하나에 들어 있는 `items[]` 배열을 상품 하나당 한 행으로 펼칩니다.
그 결과 주문 테이블과 주문상품 테이블을 SQL로 분석하기 쉬운 형태로 만들 수 있습니다.

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

**한국어 설명:** Athena는 S3 파일을 자신의 저장소로 복사하지 않고 그 자리에서 SQL로 읽습니다.
날짜 partition과 필요한 컬럼만 조회하면 스캔 데이터가 줄어 비용과 실행 시간을 아낄 수 있습니다.

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

**한국어 설명:** CDC의 Insert, Update, Delete 이벤트 중 각 주문의 가장 최신 변경만 선택해
현재 테이블에 반영합니다. 중복 이벤트가 다시 와도 결과가 달라지지 않도록 순서와 키를 사용합니다.

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

**한국어 설명:** 정제된 데이터를 일별 매출처럼 비즈니스가 바로 사용할 지표로 집계합니다.
이 Gold mart를 BI 도구가 읽으므로 dashboard마다 같은 지표 정의를 재사용할 수 있습니다.

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
