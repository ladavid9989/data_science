# Instructor Guide

## Teaching philosophy

Do not use these notebooks as a long live-coding slideshow. Each lesson follows
the same cycle:

1. State a production failure scenario.
2. Let the student predict the result.
3. Run the deliberately imperfect case.
4. Ask the student to implement or explain the guardrail.
5. Run the checkpoint tests.
6. Have the student give a two-minute interview explanation using evidence.

## Suggested eight-session plan

| Session | Material | Student exit ticket |
|---|---|---|
| 1 | Architecture and Notebook 01 through raw pages | Explain why raw responses are immutable |
| 2 | Notebook 01 reliability and manifests | Defend retry, checkpoint, and idempotency choices |
| 3 | Notebook 02 schemas and normalization | Explain corrupt-record quarantine and schema drift |
| 4 | Notebook 02 CDC | Correctly resolve duplicate/out-of-order I/U/D events |
| 5 | Notebook 03 | Read a physical plan and identify a shuffle |
| 6 | Notebook 04 | Build and defend the star schema and SCD2 logic |
| 7 | Airflow DAG and tests | Backfill one date and diagnose a failed quality gate |
| 8 | Notebook 05 and interview review | Explain offsets, replay, and idempotent consumption |

Use `infra/app.py` as an optional infrastructure-as-code review. First run only
`cdk synth`, inspect the generated CloudFormation resources and IAM grants, and
ask the student to identify which action (`cdk deploy`) would mutate AWS.

## Assessment rubric (100 points)

- Reliable extraction and raw-data preservation: 15
- Explicit schemas, normalization, and data-quality handling: 15
- Incremental processing, CDC correctness, and idempotency: 20
- Spark partition/shuffle/cache reasoning supported by evidence: 15
- Warehouse modeling and SQL quality: 15
- Airflow retry/backfill/logging understanding: 10
- Kafka offset and delivery-semantics understanding: 5
- Clear two-minute project explanation and honest scope: 5

## Failure injections

- Change the API's first page to return a malformed payload.
- Delete the checkpoint after raw files exist.
- Add two CDC events with the same timestamp but different sequence numbers.
- Make one customer own 40% of generated events and inspect join skew.
- Write one Parquet file per record and compare file-discovery overhead.
- Re-run a Kafka batch after committing no offset.
- Make the Airflow quality threshold stricter than the observed data.

## Interview prompts

1. Why save the raw API page before flattening it?
2. What exactly makes the extraction idempotent?
3. How do retryable and non-retryable HTTP errors differ?
4. Why is JSON semi-structured rather than unstructured?
5. What happens if a CDC delete arrives before an older update?
6. When does partitioning reduce cost, and when does it create small files?
7. What creates a Spark shuffle in this pipeline?
8. Why can caching make a job slower?
9. How would the local warehouse design change on Redshift/Snowflake?
10. Why does at-least-once delivery require an idempotent sink?

## Resume guardrail

Require the student to describe what was actually run:

- Local Spark is not multi-node cluster operations.
- A local S3-compatible layout is not an AWS deployment.
- A generated CDK template is not a deployed AWS stack.
- Kafka simulation mode is not Kafka broker experience.
- Databricks Free Edition and BigQuery sandbox are real managed platforms, but
  they are not production administration experience.

The final resume bullets should name metrics observed in the project and should
not claim services that the student did not run.
