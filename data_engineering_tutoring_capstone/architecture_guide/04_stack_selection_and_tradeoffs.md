# 04 — Technology Stack Selection and Trade-offs

## Start with the workload

Do not begin with “Which tool is popular?” Begin with the required behavior.

| Requirement | Architectural implication | Skills to demonstrate |
|---|---|---|
| Daily API snapshot | Scheduled batch ingestion may be sufficient | Python, HTTP, pagination, retries, checkpoint, Airflow |
| Database changes within minutes | CDC or frequent incremental extraction | Primary keys, sequence/log positions, deduplication, MERGE |
| Millions of events per second | Partitioned event log and horizontally scalable consumers | Kafka, keys, partitions, offsets, backpressure, streaming compute |
| Ad-hoc SQL over S3 | Serverless lake query | Athena, Glue Catalog, Parquet, partition pruning, scan-cost control |
| Repeated BI queries and governed metrics | Curated warehouse and data marts | Redshift/Snowflake/BigQuery, dimensional modeling, SQL ELT, semantic definitions |
| Large joins and complex transformations | Distributed processing may be justified | Spark/PySpark, shuffle, skew, partition sizing, EMR/Databricks |
| Strict audit and replay | Immutable landing plus control metadata | Manifests, checksums, lineage, atomic commits, retention |

## Athena, EMR, and Redshift/Snowflake are different tools

| Athena | EMR | Redshift/Snowflake |
|:---:|:---:|:---:|
| **S3 files**<br>↓<br>SQL query in place | **S3 files / streams**<br>↓<br>Spark and other distributed processing | **Loaded or managed tables**<br>↓<br>Warehouse SQL and BI workloads |
| Best fit: exploration, serverless SQL, occasional lake queries | Best fit: large/complex ETL, custom distributed computation | Best fit: curated, repeated analytics and data marts |
| Main cost lever: bytes processed and result reuse | Main cost lever: compute size, runtime, scaling, file layout | Main cost lever: provisioned/serverless capacity, workload design, storage and query efficiency |
| Core skill: partition-aware SQL | Core skill: Spark execution and cluster operations | Core skill: warehouse modeling and physical design |

They can coexist:

```text
                           ┌──► Athena: exploration and lake SQL
API / DB → S3 → EMR/Glue ─┤
                           └──► Redshift/Snowflake: curated marts and BI
```

## Local, AWS, GCP, and Databricks mapping

| Capability | Free/local lab | AWS-oriented option | GCP-oriented option | Databricks-oriented option |
|---|---|---|---|---|
| API extraction | Python `requests` + local API | Lambda, ECS, Glue Python shell, MWAA tasks | Cloud Run/Functions, Composer tasks | Jobs calling REST APIs |
| Object storage | Local Bronze/Silver folders | S3 | Cloud Storage | Cloud object storage behind the lakehouse |
| Catalog | File paths and explicit schemas | Glue Data Catalog | Dataplex/BigLake catalog choices | Unity Catalog |
| Distributed transform | Local PySpark | EMR or Glue | Serverless Spark / Dataproc choices | Databricks Runtime |
| Lake query | DuckDB/PyArrow | Athena | BigQuery external/BigLake patterns | Databricks SQL |
| Warehouse | DuckDB | Redshift/Snowflake | BigQuery | Databricks SQL warehouse |
| Orchestration | Python runner or local Airflow | MWAA, Step Functions, Glue workflows | Composer, Workflows | Databricks Workflows |
| Streaming | Local Kafka simulator or Docker Kafka | MSK or Kinesis | Managed Kafka or Pub/Sub | Structured Streaming with Kafka or cloud sources |
| Infrastructure as code | Local AWS CDK synthesis | CDK, CloudFormation, Terraform | Terraform and provider-native tools | Asset Bundles and Terraform |

This table maps capabilities, not exact feature equivalence. Validate security,
pricing, region availability, quotas, and organization standards before a real
deployment.

## Storage design decisions

| Decision | Good evidence | Warning sign |
|---|---|---|
| Parquet instead of JSON for analytics | Column pruning, compression, typed schema | Converting tiny one-off files without a query need |
| Partition by date | Most queries filter by date and each partition is meaningfully sized | Thousands of tiny partitions or no partition filters in queries |
| Cluster/sort by customer or status | Frequent filters/joins and measured block pruning | Selecting keys only because they “sound important” |
| Cache a Spark DataFrame | Expensive lineage reused by many actions | One or two actions where materialization costs more than recomputation |
| Broadcast a dimension | Dimension is small enough and avoids large-side shuffle | Broadcasting a table that can exhaust executor memory |
| Increase shuffle partitions | Tasks are too large and resources are underused | Many tiny tasks dominated by scheduling overhead |

## Data format selection

| Format | Good use | Limitation |
|---|---|---|
| JSON / JSONL | Source landing, nested payloads, human inspection | Larger scans, weaker typing, expensive repeated parsing |
| CSV | Simple interchange with broad compatibility | Weak schema, delimiter/quoting problems, no nested structure |
| Parquet | Analytical Silver/Gold tables | Not designed for frequent single-row transactional updates |
| Delta / Iceberg / Hudi | Table transactions, schema evolution, upserts, time travel patterns | Additional engine/catalog/operational complexity |

## Cost and performance checklist

1. Filter partitions and project only required columns.
2. Inspect the physical plan; do not assume an optimization occurred.
3. Track input bytes, output rows, file count, file-size distribution, shuffle
   bytes, spill, task duration, and skew.
4. Separate cold reads, warm cache runs, and repeated measurements.
5. Include the cost of cache materialization and data compaction.
6. Prevent accidental full scans with platform guardrails where available.
7. Optimize the business workload, not a synthetic benchmark alone.

## Junior-level evidence checklist

A strong junior project should demonstrate:

- one real HTTP request path, not only a hard-coded dictionary;
- bounded retry behavior with a forced failure test;
- immutable Bronze files plus source metadata;
- explicit schema and a visible quarantine path;
- deterministic deduplication and record-count reconciliation;
- a checkpoint committed after durable output;
- CDC replay that preserves the final snapshot;
- partition-pruning evidence and one execution-plan comparison;
- a fact table, a dimension, and a tested business mart;
- unit tests and a README with exact run instructions.

## Honest resume language

| Evidence completed | Accurate statement |
|---|---|
| Local notebooks only | “Built a local production-like data engineering capstone with PySpark, Parquet, CDC, and SQL marts.” |
| Architecture documents only | “Designed AWS and warehouse translations for the local implementation.” |
| Docker Kafka completed | “Produced and consumed events using a local Kafka broker with manual offset commit.” |
| Real S3 extension completed | “Uploaded immutable Bronze pages to S3 with checksum metadata.” |
| EMR deployment completed | “Deployed and monitored a Spark job on Amazon EMR,” followed by the exact operational evidence. |

## Official references

- [Amazon Athena documentation](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [Amazon EMR documentation](https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-what-is-emr.html)
- Redshift/Snowflake documentation: [AWS warehouse documentation](https://docs.aws.amazon.com/redshift/latest/mgmt/welcome.html) and [Snowflake key concepts](https://docs.snowflake.com/en/user-guide/intro-key-concepts)
- [AWS DMS change data capture](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Task.CDC.html)
- [Databricks medallion architecture](https://docs.databricks.com/aws/en/lakehouse/medallion)
- [BigQuery partitioned tables](https://cloud.google.com/bigquery/docs/partitioned-tables)
- [BigQuery clustered tables](https://cloud.google.com/bigquery/docs/clustered-tables)
