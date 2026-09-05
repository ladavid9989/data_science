# 06 — Data Engineering Glossary

| Term | Plain-English meaning |
|---|---|
| API | A contract that lets one program request data or actions from another program. |
| REST API | An HTTP-based API commonly using methods such as GET and JSON responses. |
| Pagination | Returning a large result in smaller pages instead of one response. |
| Cursor | A token that tells an API where the next page should continue. |
| Retry | Repeating an operation after a temporary failure such as a timeout, 429, or 5xx response. |
| Backoff | Waiting progressively longer between retries to avoid increasing pressure on a failing service. |
| Checkpoint | Durable state recording where a pipeline can safely resume. |
| High watermark | The greatest source position that has been successfully committed, such as an update time or sequence. |
| Atomic write | A write that becomes visible as a complete result or not at all; readers should not see a partial file. |
| Manifest | Control metadata describing a pipeline run and its files, counts, checksums, and status. |
| Checksum | A digest such as SHA-256 used to detect an accidental file change or corruption. |
| Idempotent | Repeating the same operation produces the same final state as running it once. |
| CDC | Change Data Capture: delivering inserts, updates, and deletes instead of repeatedly copying a complete table. |
| Sequence number | A source position used to order changes more reliably than arrival order. |
| Bronze | The raw, replayable layer that preserves source truth and lineage. |
| Silver | Cleaned, typed, deduplicated, structured data suitable for analytical reuse. |
| Gold | Business-ready aggregates or marts with defined metrics and consumers. |
| Quarantine | Storage for rejected records together with failure reasons and source evidence. |
| Schema | Column/field names, data types, nullability, and nested structure expected in data. |
| Schema evolution | A source structure changing over time, such as moving `customer_id` into `customer.id`. |
| Data lineage | Evidence showing where data came from and which processing produced it. |
| Parquet | A typed columnar file format designed for efficient analytical reads and compression. |
| Partition | A physical or logical subdivision of data that can be processed separately. |
| Partition pruning | Skipping partitions that cannot match a query filter. |
| Shuffle | Moving data between Spark partitions, often required by joins and groupings. |
| Cache | Reusing a previously computed dataset from memory or other configured storage. |
| Spark | A distributed processing engine for large-scale batch, SQL, streaming, and other workloads. |
| PySpark | The Python API used to construct and run Spark computations. |
| Python UDF | A custom Python function called from Spark; flexible but often slower than built-in expressions. |
| Broadcast join | Copying a small table to workers so a large table does not need a full join shuffle. |
| Airflow | A workflow orchestrator that schedules tasks, dependencies, retries, and backfills. |
| DAG | A directed acyclic graph describing workflow task dependencies. |
| Kafka | A distributed, durable event log organized into topics and partitions. |
| Topic | A named Kafka event stream. |
| Consumer group | Consumers that cooperate to divide a topic's partitions. |
| Offset | A message position within one Kafka partition and a consumer's progress marker. |
| Event time | When the business event occurred at the source. |
| Processing time | When the processing system handled the event. |
| Watermark (streaming) | A policy for how long a streaming computation waits for late event-time data. |
| Data lake | Object-storage-based data platform supporting multiple formats and processing engines. |
| Data warehouse | A managed analytical database designed for structured SQL workloads and BI. |
| Lakehouse | An architecture adding table-management and warehouse-like capabilities to lake storage. |
| Athena | An AWS service that queries data in S3 with SQL without first loading it into a conventional warehouse. |
| EMR | Amazon EMR, a managed AWS platform for running big-data frameworks such as Spark. Its name originated from Elastic MapReduce. |
| Redshift/Snowflake | The AWS offering and Snowflake are separate cloud platforms in the same analytical warehouse category. |
| Glue Data Catalog | AWS metadata catalog describing datasets, schemas, tables, and locations. |
| Fact table | A table of measurable business events at a declared grain, such as one row per order. |
| Dimension table | Descriptive context used with facts, such as customer, product, or date. |
| Data mart | A curated dataset designed for a specific analytical subject or consumer group. |
| SCD Type 2 | A dimension pattern that preserves historical versions with effective time intervals. |
| ETL | Extract, transform, then load into the serving system. |
| ELT | Extract, load, then transform inside the analytical platform. |
| Orchestration | Coordinating when jobs run, in what order, with what retries and recovery behavior. |
| Backfill | Reprocessing a historical time interval or partition. |
| SLA/SLO | A commitment or objective for service behavior such as freshness, availability, or recovery time. |

## Terms that are easy to confuse

| Pair | Difference |
|---|---|
| Cursor vs checkpoint | A cursor usually moves between pages in one API run; a checkpoint survives between pipeline runs. |
| High watermark vs streaming watermark | A high watermark records committed source progress; a streaming watermark defines tolerated event-time lateness. |
| S3 vs Athena | S3 stores objects; Athena executes SQL over cataloged data, commonly in S3. |
| Spark vs EMR | Spark is a processing engine; EMR is an AWS platform that can run Spark. |
| Athena vs Redshift/Snowflake | Athena queries lake files in place; Redshift/Snowflake provide managed analytical warehouses. |
| Partition vs Kafka partition | A data/file partition organizes analytical data; a Kafka partition is an ordered event log and unit of consumer parallelism. |
| Retry vs replay | Retry repeats a failed operation; replay intentionally processes previously stored events again. |
| Duplicate delivery vs duplicate final state | A message may be delivered twice while an idempotent sink still stores one correct business row. |
