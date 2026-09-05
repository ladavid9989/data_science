# 02 — From Raw Source Data to a BI Dashboard

## The complete path

| Sources | Ingestion | Bronze | Processing | Silver | Warehouse / Gold | Consumption |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| REST APIs<br>Databases<br>Files<br>Application events | Cursor pagination<br>CDC<br>Batch upload<br>Kafka | Immutable JSON<br>Source metadata<br>Run manifest | Parse<br>Validate<br>Deduplicate<br>Flatten | Typed Parquet<br>Orders<br>Order items<br>Clean logs | Fact tables<br>Dimensions<br>Daily marts | Athena<br>Redshift<br>BI dashboard<br>Data science |
| **What arrived?** | **Did we collect it safely?** | **Can we replay it?** | **Is it valid?** | **Can analysts use it?** | **Does it answer business questions?** | **Is it trusted and fast enough?** |

## One order moving through the system

### 1. Source API response

```json
{
  "order_id": "ord_000101",
  "customer": {"id": "cust_0042", "tier": "plus"},
  "updated_at": "2026-01-03T10:05:00Z",
  "status": "paid",
  "total_amount": "88.00",
  "items": [
    {"sku": "SKU-010", "quantity": 2, "unit_price": "44.00"}
  ]
}
```

### 2. Bronze: preserve source truth

| Data file | Control metadata |
|---|---|
| Original API envelope and records | `run_id`, request ID, source URL, page number, row count, checksum, starting and ending watermark |

Bronze does not silently repair `"88.00"`, remove duplicates, or flatten the
`items` array. It preserves evidence for replay and investigation.

### 3. Silver: create typed, tabular data

`silver.orders`:

| order_id | customer_id | updated_at | status | total_amount | event_date |
|---|---|---|---|---:|---|
| ord_000101 | cust_0042 | 2026-01-03 10:05:00 | paid | 88.00 | 2026-01-03 |

`silver.order_items`:

| order_id | line_number | sku | quantity | unit_price | event_date |
|---|---:|---|---:|---:|---|
| ord_000101 | 1 | SKU-010 | 2 | 44.00 | 2026-01-03 |

Invalid orders are written to quarantine with a reason and source lineage. They
are not silently discarded.

### 4. Current state from CDC

| sequence_no | op | order_id | status | Meaning |
|---:|:---:|---|---|---|
| 101 | U | ord_000101 | paid | Older update |
| 102 | U | ord_000101 | shipped | Authoritative later update |
| 103 | D | ord_000205 | null | Delete the order |

The greatest committed source sequence is authoritative. A repeated event must
not create a duplicate or change the final result.

### 5. Gold: answer a business question

| order_date | order_count | purchasing_customers | gross_revenue | shipped_revenue |
|---|---:|---:|---:|---:|
| 2026-01-03 | 1,240 | 981 | 128,540.75 | 97,220.10 |

A BI dashboard should query this stable business grain instead of repeatedly
parsing raw API JSON.

## Data plane and control plane

| Data plane: business records | Control plane: safe operation |
|---|---|
| Orders, customers, items, application events, CDC changes | Cursor, watermark, checkpoint, manifest, checksum, schema version, row counts, logs, retry attempts |

A pipeline is incomplete if it moves business rows but cannot answer where they
came from, whether the run completed, or how to resume after failure.

## Batch, streaming, and hybrid delivery

| Batch | Streaming | Hybrid |
|:---:|:---:|:---:|
| **API / files**<br>↓<br>Scheduled extraction<br>↓<br>Bronze<br>↓<br>Daily transform | **Application events**<br>↓<br>Kafka<br>↓<br>Streaming consumer<br>↓<br>Near-real-time sink | **Kafka + database**<br>↓<br>Fast stream view<br>+<br>Batch reconciliation<br>↓<br>Trusted serving layer |
| Simpler recovery and lower operating complexity | Lower latency but more offset, ordering, and state concerns | Fast results plus a slower authoritative correction path |

## Failure and recovery checkpoints

| Failure point | Unsafe behavior | Safer design |
|---|---|---|
| API page fails | Return partial data as success | Retry bounded transient failures; fail visibly when exhausted |
| Process crashes after writing a page | Restart from an advanced watermark | Commit the watermark only after data and manifest are durable |
| Same record arrives twice | Append both rows | Deduplicate by a stable key and deterministic ordering |
| Bad JSON appears | Drop it | Preserve the source line and route it to quarantine |
| Kafka consumer crashes after sink write | Duplicate the business row | Use an idempotent sink, then commit the offset |
| BI query scans all history | Accept unpredictable cost | Filter partitions and publish purpose-built marts |

## Evidence produced at every layer

```text
Source
  ↓ request ID and source contract
Bronze
  ↓ page checksum, manifest, row count, watermark
Silver
  ↓ valid / quarantine / duplicate reconciliation
CDC snapshot
  ↓ latest sequence, delete and upsert tests, replay test
Gold
  ↓ source-to-fact reconciliation and business-rule tests
BI
  ↓ freshness timestamp, metric definition, access audit
```

