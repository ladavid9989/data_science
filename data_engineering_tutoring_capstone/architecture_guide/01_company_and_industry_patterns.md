# 01 — Architecture Patterns by Company Size and Industry

## Architecture follows constraints, not company labels

Company size is a useful clue, but architecture should be selected from workload
evidence: data volume, arrival rate, freshness, query patterns, team size,
compliance, recovery objectives, and budget.

## Horizontal comparison by operating model

| Lean / early-stage | Growing analytics team | Large regulated enterprise | Event-intensive product |
|:---:|:---:|:---:|:---:|
| **APIs + App DB**<br>↓<br>**Managed ingestion**<br>↓<br>**S3 + Athena**<br>or<br>**BigQuery**<br>↓<br>**Dashboard** | **APIs + DB CDC**<br>↓<br>**Airflow / managed scheduler**<br>↓<br>**S3 Bronze**<br>↓<br>**Spark or SQL transforms**<br>↓<br>**Warehouse + BI** | **Many domains**<br>↓<br>**Batch + CDC + streams**<br>↓<br>**Governed data lake**<br>↓<br>**EMR / Glue / lakehouse**<br>↓<br>**Redshift + BI** | **Apps + devices**<br>↓<br>**Kafka / Kinesis**<br>↓<br>**Streaming compute**<br>↓<br>**Lakehouse + serving store**<br>↓<br>**Real-time BI** |
| Minimize operations and tool count | Add orchestration, testing, and reusable models | Emphasize security, lineage, isolation, audit, and recovery | Emphasize throughput, event time, replay, ordering, and low latency |

The four columns are alternatives, not required stages. Use the smallest design
that meets the business service level.

## What usually changes as an organization grows

| Concern | Lean team | Growing team | Enterprise |
|---|---|---|---|
| Ingestion | Scheduled Python or managed connectors | Reusable API framework and CDC | Domain-owned contracts, batch and streaming platforms |
| Storage | One governed bucket or warehouse | Bronze/Silver/Gold zones | Multiple accounts/domains, retention tiers, formal governance |
| Processing | SQL and Pandas for suitable data sizes | SQL plus Spark when justified | Several engines selected by workload |
| Orchestration | Cron or a managed scheduler | Airflow or equivalent | Managed orchestration with backfills, SLAs, and platform ownership |
| Quality | Assertions and row reconciliation | Shared tests, quarantine, alerts | Data contracts, lineage, audit evidence, incident response |
| Serving | Athena or one warehouse | Curated marts and semantic models | Multiple warehouses, lake query, APIs, and ML features |
| Operations | One team owns the pipeline | Data platform standards emerge | Dedicated platform, governance, security, and SRE responsibilities |

## Horizontal comparison by industry workload

| E-commerce | B2B SaaS | Finance / healthcare | IoT / gaming / advertising |
|:---:|:---:|:---:|:---:|
| **Orders + payments + clicks**<br>↓<br>CDC and event ingestion<br>↓<br>Lake + warehouse<br>↓<br>Revenue, inventory, funnels | **Tenant DB + product events + SaaS APIs**<br>↓<br>Incremental ingestion<br>↓<br>Tenant-aware models<br>↓<br>Usage and retention metrics | **Transactions / clinical or claims data**<br>↓<br>Immutable landing<br>↓<br>Validated and access-controlled processing<br>↓<br>Audited reporting | **High-rate events**<br>↓<br>Kafka / Kinesis<br>↓<br>Stream and batch processing<br>↓<br>Real-time metrics and historical analysis |
| Key problems: order state, late payment updates, inventory consistency | Key problems: tenant isolation, schema changes, API limits | Key problems: privacy, lineage, reconciliation, retention | Key problems: event time, duplicates, skew, backpressure, replay |

These are illustrative patterns. Regulations and internal policies must be
validated for the actual organization and jurisdiction.

## Skills implied by each pattern

| Pattern | Most important engineering skills |
|---|---|
| API-to-lake analytics | Python, HTTP, pagination, retries, JSON, S3 layout, Glue Catalog, Athena SQL |
| Warehouse-centered analytics | SQL, dimensional modeling, ELT, data tests, Redshift/BigQuery, BI serving |
| Spark lake processing | PySpark, schemas, partitioning, shuffle, file sizing, join strategy, EMR/Databricks operations |
| CDC platform | Source keys, log sequence/offsets, ordering, deduplication, checkpointing, MERGE, replay |
| Streaming platform | Kafka topics/partitions, consumer groups, offsets, event time, watermarking, idempotent sinks |
| Regulated platform | IAM, encryption, secrets, audit logs, lineage, retention, least privilege, recovery evidence |

## Architecture review questions

Before selecting a service, answer these questions:

1. How much data arrives, how often, and with what burst pattern?
2. Is the required freshness daily, hourly, within minutes, or within seconds?
3. Can the source resend data, change schema, or deliver records out of order?
4. Are queries exploratory, predictable BI workloads, or application-serving queries?
5. What happens after a partial write or a crash before checkpoint commit?
6. Which data is sensitive, and who must not be able to read it?
7. Which cost dominates: storage, bytes scanned, always-on compute, or engineering time?
8. What evidence proves completeness, uniqueness, freshness, and recoverability?

## Common mistakes

- Adding Kafka because data is “real time” without defining the latency target.
- Adding Spark when SQL on a warehouse or Athena is sufficient.
- Calling a local PySpark run “EMR operations experience.”
- Treating Bronze as clean data and losing the exact source response.
- Advancing a checkpoint before durable output is committed.
- Partitioning by a high-cardinality identifier and producing tiny files.
- Building separate platforms when one governed stack meets the workload.

