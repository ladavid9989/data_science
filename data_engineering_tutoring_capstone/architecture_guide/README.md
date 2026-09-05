# Data Engineering Architecture and Stack Guide

This folder explains how data architecture changes with company size, industry,
workload, cost, and operational requirements. It connects architecture diagrams
to the executable labs in the parent project.

The diagrams are intentionally horizontal where comparison matters. They are
reference patterns, not mandatory maturity stages. A small company can have a
high-volume streaming problem, while a large company can solve a simple reporting
problem with a small serverless stack.

## Learning path

| Module | Main question | Practical connection |
|---|---|---|
| [01 — Company and industry patterns](01_company_and_industry_patterns.md) | Why do organizations choose different architectures? | Compare batch, warehouse, lakehouse, and streaming patterns. |
| [02 — End-to-end data lifecycle](02_end_to_end_data_lifecycle.md) | What happens between a source API and a dashboard? | Trace one order through Bronze, Silver, Gold, and BI. |
| [03 — Ingestion and structuring patterns](03_ingestion_and_structuring_patterns.md) | How do REST, JSON, S3, Athena, and CDC become tables? | Read compact Python, PySpark, and SQL patterns. |
| [04 — Stack selection and trade-offs](04_stack_selection_and_tradeoffs.md) | When should we use Athena, EMR, Redshift/Snowflake, or another platform? | Use decision matrices and local-to-cloud mappings. |
| [05 — Case studies and exercises](05_case_studies_and_exercises.md) | Can the student justify an architecture? | Design systems for commerce, SaaS, finance, and IoT. |
| [06 — Glossary](06_glossary.md) | What do the common terms mean? | Review concise definitions before interviews. |

## Capstone lab map

| Executable notebook | Architecture capability demonstrated |
|---|---|
| [`01_api_ingestion_and_reliability.ipynb`](../notebooks/01_api_ingestion_and_reliability.ipynb) | REST API, cursor pagination, retries, Bronze storage, manifest, checksum, high-watermark checkpoint, atomic write |
| [`02_pyspark_lakehouse_and_cdc.ipynb`](../notebooks/02_pyspark_lakehouse_and_cdc.ipynb) | Explicit schemas, nested JSON, quarantine, deduplication, Silver Parquet, CDC, idempotency |
| [`03_spark_performance_and_cost.ipynb`](../notebooks/03_spark_performance_and_cost.ipynb) | Partition pruning, shuffle, broadcast join, caching, built-in expressions versus Python UDFs |
| [`04_warehouse_elt_and_modeling.ipynb`](../notebooks/04_warehouse_elt_and_modeling.ipynb) | Fact and dimension tables, SQL ELT, SCD Type 2, data marts, warehouse quality gates |
| [`05_kafka_streaming_and_offsets.ipynb`](../notebooks/05_kafka_streaming_and_offsets.ipynb) | Topics, partitions, offsets, consumer groups, replay, late events, idempotent sinks |

## One project, several production translations

| Local capstone | AWS-oriented production equivalent | Other common equivalents |
|---|---|---|
| Local Bronze folders | Amazon S3 raw prefixes | Google Cloud Storage, Azure Data Lake Storage |
| Local PySpark | Spark on Amazon EMR or AWS Glue | Databricks, Google Cloud Serverless for Apache Spark |
| DuckDB warehouse | Redshift/Snowflake | BigQuery, Databricks SQL |
| Local API server | Internal application API or third-party SaaS API | Shopify, Stripe, Salesforce, partner APIs |
| Local Kafka simulator | Amazon MSK or self-managed Kafka | Confluent Cloud, Google Cloud Managed Service for Apache Kafka |
| Local files for state | Durable checkpoint table or object | DynamoDB, relational metadata table, streaming checkpoint storage |

## How to use this guide

1. Read Modules 01 and 02 before choosing technologies.
2. Use Module 03 while running Notebooks 01 and 02.
3. Use Module 04 while running Notebooks 03 and 04.
4. Complete one case study from Module 05 and defend every service choice.
5. Use the glossary only as a quick reference; explain terms with concrete failure
   and recovery examples during tutoring.

## Evidence boundary

Architecture knowledge and local simulation are valuable, but they are not the
same as operating a production cloud platform. State the evidence precisely:

- “implemented locally” for code executed in these notebooks;
- “designed a production translation” for diagrams and cloud SQL examples;
- “deployed on AWS/GCP/Databricks” only after running the optional cloud exercise.
