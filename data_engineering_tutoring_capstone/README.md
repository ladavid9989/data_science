# Production-Like Commerce Data Platform

An English, notebook-led tutoring capstone for a junior data engineer preparing
for the US job market. The project is intentionally local-first: the core path
does not require a cloud account, credit card, or paid dataset.

This is a new curriculum. It does not modify or depend on the earlier mini ETL
notebook.

## What the student builds

```text
Paginated REST API + application JSONL logs + CDC events
                         |
                         v
              Bronze / immutable raw files
                         |
                         v
       PySpark validation, flattening, deduplication
                         |
                         v
       Silver / partitioned Parquet + CDC snapshot
                         |
                         v
       DuckDB warehouse and dimensional data marts
                         |
                         v
       Airflow orchestration, tests, and run metrics

Optional: Kafka -> consumer group -> idempotent landing sink
Optional: Databricks Free Edition, BigQuery sandbox, or AWS
```

## Notebook sequence

1. `01_api_ingestion_and_reliability.ipynb`
   - Starts a deterministic local REST API over HTTP.
   - Handles cursor pagination, HTTP 429/500, retry/backoff, checkpoints,
     immutable raw pages, manifests, checksums, and JSON logs.
   - Generates realistic application JSONL logs for later notebooks.

2. `02_pyspark_lakehouse_and_cdc.ipynb`
   - Reads nested API envelopes with explicit Spark schemas.
   - Normalizes orders and items, routes bad rows to quarantine, and writes
     partitioned Parquet.
   - Applies out-of-order insert/update/delete CDC events idempotently.
   - Includes an optional Delta Lake `MERGE` exercise for Databricks.

3. `03_spark_performance_and_cost.ipynb`
   - Uses an adjustable synthetic workload rather than a toy DataFrame.
   - Compares partitioned/unpartitioned layouts, small files, repartition vs.
     coalesce, shuffle configuration, broadcast joins, built-ins vs. Python
     UDFs, and cache behavior.
   - Records evidence instead of relying only on wall-clock anecdotes.

4. `04_warehouse_elt_and_modeling.ipynb`
   - Uses DuckDB as a free local analytical warehouse.
   - Builds staging, dimensions, facts, quality checks, SCD Type 2 history, and
     business marts with SQL.
   - Shows equivalent BigQuery and Redshift/Snowflake design notes without pretending
     that DuckDB is Redshift/Snowflake.

5. `05_kafka_streaming_and_offsets.ipynb`
   - Runs in simulation mode by default so the lesson always works.
   - Can connect to the included real Apache Kafka Docker container.
   - Demonstrates keys, partitions, consumer groups, offsets, replay,
     at-least-once delivery, duplicates, late events, and an idempotent sink.

## Recommended setup

Use Python 3.10 or newer. Run commands from this project directory.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-core.txt
jupyter lab
```

For notebooks 02 and 03, install Java 17+ and the Spark requirements:

```bash
python -m pip install -r requirements-spark.txt
```

For real Kafka mode in notebook 05:

```bash
docker compose -f docker-compose.kafka.yml up -d
python -m pip install -r requirements-kafka.txt
```

For the Airflow lab:

```bash
docker compose -f docker-compose.airflow.yml up
```

Open `http://localhost:8080` and use the credentials printed by Airflow
standalone. The compose file is for local education, not production.

For the optional CDK exercise, install the AWS CDK CLI and the Python packages
in `infra/requirements.txt`, then run `cdk synth` from `infra/`. Synthesis is
local. Do not run `cdk deploy` until account permissions, budget controls,
region, and cleanup have been reviewed.

Detailed, explicitly optional cloud labs are in
`instructor/CLOUD_EXTENSION_GUIDE.md`.

## Local-first service mapping

| Resume technology | Core lab substitute | Optional real platform |
|---|---|---|
| S3 | Hive-style local object prefixes | Amazon S3 |
| Lambda | Pure event handler and unit tests | AWS Lambda |
| Glue | PySpark job and explicit schema | AWS Glue |
| Glue Catalog | Spark/DuckDB table metadata | Glue Data Catalog |
| Athena | DuckDB queries over partitioned Parquet | Amazon Athena |
| Redshift/Snowflake | DuckDB columnar warehouse concepts | Managed Redshift/Snowflake trial environment |
| EMR | Local Spark execution plans | Amazon EMR |
| CDK | Local architecture and template exercises | `cdk synth/deploy` |
| Databricks | Local PySpark | Databricks Free Edition |
| Kafka | Deterministic simulator | Apache Kafka in Docker |

Local substitutes teach transferable concepts but are not presented as actual
cloud operations experience. Notebook markdown identifies the boundary.

## Verification

Run the lightweight unit tests:

```bash
pytest -q
```

The notebooks also contain checkpoint assertions and student challenges. A
tutoring rubric and interview prompts are in `instructor/TEACHING_GUIDE.md`.

## Optional free cloud extensions

- Databricks Free Edition: https://docs.databricks.com/aws/en/getting-started/free-edition
- BigQuery sandbox: https://docs.cloud.google.com/bigquery/docs/sandbox
- AWS Free Tier: https://aws.amazon.com/free/
- Redshift/Snowflake trial options: https://aws.amazon.com/redshift/free-trial/ and https://signup.snowflake.com/

Cloud offers and limits can change. Verify current eligibility before a class,
set budgets where applicable, and remove optional resources after the lab.
