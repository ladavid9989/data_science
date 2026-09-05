# 05 — Architecture Case Studies and Tutoring Exercises

The goal is not to list the maximum number of services. The student must choose
the smallest architecture that satisfies the stated constraints and explain how
it recovers from failure.

## Case 1 — Small e-commerce company

**Requirements**

- Orders come from a cursor-paginated REST API.
- Product and payment files arrive daily.
- Ten analysts run occasional SQL queries.
- A dashboard must refresh every morning.
- The platform team has two engineers.

| Appropriate first design | Premature design |
|:---:|:---:|
| **REST + files**<br>↓<br>Scheduled Python ingestion<br>↓<br>S3 Bronze<br>↓<br>SQL/PySpark only when justified<br>↓<br>Parquet Silver<br>↓<br>Athena + BI | Kafka<br>+ always-on Spark cluster<br>+ several serving databases<br>+ complex orchestration |

**Skills:** Python, API contracts, retry, cursor, watermark, S3 prefixes,
Parquet, Athena SQL, partitioning, data tests.

**Exercise:** Explain the checkpoint commit order after page 4 succeeds but the
process crashes before the manifest is written.

## Case 2 — Growing multi-tenant SaaS company

**Requirements**

- Product events arrive continuously.
- Billing and CRM APIs update hourly.
- PostgreSQL account changes must reach analytics within 15 minutes.
- BI metrics must be consistent across customer-success and finance teams.

```text
Product events ─► Kafka ───────────────┐
PostgreSQL ─────► CDC ─────────────────┼► Bronze / staging
Billing + CRM ──► Airflow API jobs ────┘
                                          ↓
                                  SQL/Spark transforms
                                          ↓
                                  Warehouse data marts
                                          ↓
                                 Governed BI definitions
```

**Skills:** Kafka offsets, CDC sequences, Airflow scheduling/backfills, tenant
keys, idempotent upserts, dimensional modeling, SQL tests, metric ownership.

**Exercise:** Design a replay that rebuilds one tenant and one date without
duplicating billing events.

## Case 3 — Regulated financial reporting

**Requirements**

- Every source file and transformation must be auditable.
- Reports must reconcile to transaction totals.
- Sensitive columns require restricted access.
- Late corrections can change previously published periods.

```text
Transactions
     ↓ encrypted immutable landing
Manifest + checksum + source sequence
     ↓ validated processing with quarantine
Versioned curated tables
     ↓ reconciliation and approval gate
Warehouse reporting mart
     ↓ restricted BI access + audit logs
```

**Skills:** least privilege, encryption, secrets, lineage, immutable evidence,
reconciliation, SCD/history, late-data correction, recovery testing.

**Exercise:** Define which records, metadata, and test evidence are required to
reproduce a report published three months ago.

## Case 4 — High-volume IoT telemetry

**Requirements**

- Devices emit a large continuous event stream.
- Events can be late, duplicated, and temporarily out of order.
- Operations needs a five-minute alert view.
- Data science needs complete historical data.

| Fast path | Historical path |
|:---:|:---:|
| **Devices**<br>↓<br>Kafka/Kinesis<br>↓<br>Streaming computation<br>↓<br>Five-minute alert store | **Same durable stream**<br>↓<br>S3 Bronze<br>↓<br>Batch reconciliation<br>↓<br>Partitioned historical tables |

**Skills:** partition keys, offsets, event time, watermarks, late-data policy,
backpressure, idempotent sinks, batch/stream reconciliation, observability.

**Exercise:** Decide whether the partition key should be `device_id`, region, or
event type. Discuss ordering, skew, and consumer parallelism.

## Architecture decision worksheet

Complete this before naming services.

| Question | Student answer |
|---|---|
| Business outcome | |
| Sources and ownership | |
| Data volume and arrival rate | |
| Required freshness | |
| Batch, CDC, stream, or hybrid | |
| Stable record key | |
| Ordering or sequence guarantee | |
| Raw replay requirement | |
| Quality and reconciliation rules | |
| Sensitive-data controls | |
| Main query pattern | |
| Recovery point after failure | |
| Cost guardrail | |
| Simplest acceptable stack | |

## Review rubric

| Area | Weak answer | Strong answer |
|---|---|---|
| Requirements | Names services immediately | Defines volume, freshness, failure, query, and security constraints first |
| Ingestion | “Call the API” | Explains pagination, retry classes, timeout, checkpoint, and source contract |
| Storage | “Put it in S3” | Defines Bronze immutability, prefixes, format, retention, and metadata |
| Transformation | “Use Spark because data is big” | Justifies engine choice and explains schema, shuffle, quality, and output layout |
| CDC | “Use latest timestamp” | Defines key, operation, source sequence, duplicates, deletes, and committed position |
| Serving | “Use Redshift/Snowflake” | Defines table grain, consumers, query pattern, and quality gates |
| Reliability | “Airflow retries it” | Explains partial failure, idempotency, replay, alerting, and backfill scope |
| Cost | “Partitioning is cheaper” | Names the filter pattern and the measured bytes/files avoided |

## Interview drill

Give a two-minute answer using this order:

```text
Business requirement
  ↓
Source contract and ingestion mode
  ↓
Storage and transformation design
  ↓
Quality, state, and recovery behavior
  ↓
Serving layer and users
  ↓
Measured trade-off and remaining limitation
```

Avoid a service inventory. A strong answer connects every technology to a
specific requirement and states what evidence was actually implemented.
