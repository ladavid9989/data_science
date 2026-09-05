"""Generate the five educational notebooks without requiring nbformat."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import json


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"


def _source(text: str) -> list[str]:
    normalized = dedent(text).strip("\n") + "\n"
    return normalized.splitlines(keepends=True)


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _source(text)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": _source(text),
    }


def write_notebook(filename: str, cells: list[dict]) -> None:
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOKS.mkdir(parents=True, exist_ok=True)
    (NOTEBOOKS / filename).write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def notebook_01() -> list[dict]:
    return [
        md(r'''
        # 01 — Reliable API Ingestion and Immutable Raw Data

        ## Business scenario

        You joined a commerce company whose order service exposes a paginated REST API.
        Analytics needs every order, but the source occasionally rate-limits clients,
        returns temporary server errors, changes its JSON schema, and repeats records
        across page boundaries.

        Your job is to build the **Extract** boundary of a production-like pipeline.
        You will preserve raw API responses before transforming them so that an incident
        can be replayed and audited.

        ### Learning objectives

        By the end of this notebook, you can:

        1. Call a real HTTP endpoint and follow cursor pagination.
        2. Distinguish retryable failures (`429`, `500`) from permanent client errors.
        3. Use bounded exponential backoff and structured JSON logging.
        4. Store immutable Bronze pages, checksums, source metadata, and a run manifest.
        5. Maintain a high-watermark checkpoint with an atomic write.
        6. Explain why extraction and transformation should be separate concerns.
        7. Prove that a second run is incremental rather than duplicating data.

        > This notebook starts a deterministic API on `127.0.0.1`. It is synthetic,
        > but requests travel through the HTTP stack. This avoids API keys, cost, and
        > classroom failures caused by a changing third-party service.
        '''),
        md(r'''
        ## Target architecture

        ```mermaid
        flowchart LR
            A[Local commerce REST API] -->|HTTP GET + cursor| B[Extractor]
            B --> C[Bronze raw page JSON]
            B --> D[Run manifest]
            B --> E[Watermark checkpoint]
            F[Application JSONL logs] --> G[Bronze log files]
            C --> H[Notebook 02: Spark Silver layer]
            G --> H
        ```

        **Bronze rule:** save the source representation with ingestion metadata, but do
        not silently repair business fields at this boundary. A raw copy lets us replay
        improved transformation logic later.

        JSON is **semi-structured**, not truly unstructured: keys provide structure, but
        records can be nested or inconsistent. Free-text log messages and stack traces
        are unstructured fields embedded inside semi-structured events.
        '''),
        code(r'''
        from __future__ import annotations

        from datetime import datetime, timedelta, timezone
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from pathlib import Path
        from urllib.parse import parse_qs, urlparse
        import gzip
        import json
        import random
        import shutil
        import sys
        import threading
        import time
        import uuid

        import pandas as pd
        import requests

        PROJECT_ROOT = Path.cwd().resolve()
        if PROJECT_ROOT.name == "notebooks":
            PROJECT_ROOT = PROJECT_ROOT.parent
        sys.path.insert(0, str(PROJECT_ROOT))

        from src.capstone_utils import atomic_write_json, configure_json_logger, file_sha256

        LAB_ROOT = PROJECT_ROOT / "lab_data"
        BRONZE_API = LAB_ROOT / "bronze" / "api" / "orders"
        BRONZE_LOGS = LAB_ROOT / "bronze" / "logs"
        STATE_DIR = LAB_ROOT / "state"
        CHECKPOINT_PATH = STATE_DIR / "orders_checkpoint.json"
        LOGGER = configure_json_logger("api_ingestion")

        # This reset is deliberately explicit and narrowly scoped to this project's lab_data.
        START_FRESH = True
        if START_FRESH and LAB_ROOT.exists():
            assert LAB_ROOT.name == "lab_data" and PROJECT_ROOT in LAB_ROOT.parents
            shutil.rmtree(LAB_ROOT)

        for directory in (BRONZE_API, BRONZE_LOGS, STATE_DIR):
            directory.mkdir(parents=True, exist_ok=True)

        print(f"Project root: {PROJECT_ROOT}")
        print(f"Lab data root: {LAB_ROOT}")
        '''),
        md(r'''
        ## Build a deterministic source system

        The source contains deliberate complications:

        - API schema version 1 uses `customer_id`.
        - Version 2 uses a nested `customer.id`.
        - Some monetary values arrive as strings.
        - One page boundary repeats an order.
        - The first request for selected cursors returns `429` or `500`.

        None of these fields will be corrected during extraction. Bronze should tell the
        truth about what the source returned.
        '''),
        code(r'''
        def build_source_orders(count: int = 240, seed: int = 17) -> list[dict]:
            rng = random.Random(seed)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            records = []
            for index in range(count):
                order_id = f"ord_{index + 1:06d}"
                customer_id = f"cust_{rng.randint(1, 60):04d}"
                event_time = start + timedelta(minutes=index * 17)
                items = [
                    {
                        "sku": f"SKU-{rng.randint(1, 40):03d}",
                        "quantity": rng.randint(1, 3),
                        "unit_price": round(rng.uniform(4, 120), 2),
                    }
                    for _ in range(rng.randint(1, 4))
                ]
                total = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)
                schema_version = 2 if index % 7 == 0 else 1
                record = {
                    "order_id": order_id,
                    "event_type": "order_created",
                    "event_timestamp": event_time.isoformat(),
                    "updated_at": (event_time + timedelta(minutes=5)).isoformat(),
                    "status": rng.choice(["pending", "paid", "shipped"]),
                    "currency": "USD",
                    "total_amount": str(total) if index % 19 == 0 else total,
                    "items": items,
                    "schema_version": schema_version,
                }
                if schema_version == 1:
                    record["customer_id"] = customer_id
                else:
                    record["customer"] = {"id": customer_id, "tier": rng.choice(["standard", "plus"])}
                if index == 31:
                    record["currency"] = None
                if index == 67:
                    record["total_amount"] = "not-a-number"
                records.append(record)

            # Simulate at-least-once source delivery.
            records.insert(81, json.loads(json.dumps(records[79])))
            return records


        SOURCE_ORDERS = build_source_orders()
        len(SOURCE_ORDERS), SOURCE_ORDERS[0]
        '''),
        code(r'''
        class CommerceAPIHandler(BaseHTTPRequestHandler):
            attempts: dict[str, int] = {}

            def log_message(self, format, *args):
                # Keep notebook output readable; the client produces structured logs.
                return

            def _send_json(self, status: int, payload: dict, headers: dict | None = None):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/v1/orders":
                    self._send_json(404, {"error": "not_found"})
                    return

                query = parse_qs(parsed.query)
                cursor = query.get("cursor", ["0"])[0]
                limit = min(int(query.get("limit", ["40"])[0]), 100)
                updated_after = query.get("updated_after", [None])[0]
                request_key = f"{cursor}|{updated_after}"
                self.attempts[request_key] = self.attempts.get(request_key, 0) + 1

                # Deterministic transient failures: one retry will recover.
                if cursor == "40" and self.attempts[request_key] == 1:
                    self._send_json(429, {"error": "rate_limited"}, {"Retry-After": "0.05"})
                    return
                if cursor == "120" and self.attempts[request_key] == 1:
                    self._send_json(500, {"error": "temporary_upstream_failure"})
                    return

                records = SOURCE_ORDERS
                if updated_after:
                    records = [r for r in records if r["updated_at"] > updated_after]
                offset = int(cursor)
                page = records[offset : offset + limit]
                next_cursor = str(offset + limit) if offset + limit < len(records) else None
                self._send_json(
                    200,
                    {
                        "data": page,
                        "next_cursor": next_cursor,
                        "request_id": str(uuid.uuid4()),
                        "schema": "orders-envelope-v1",
                    },
                )


        api_server = ThreadingHTTPServer(("127.0.0.1", 0), CommerceAPIHandler)
        api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
        api_thread.start()
        API_URL = f"http://127.0.0.1:{api_server.server_port}/v1/orders"
        print(API_URL)
        '''),
        md(r'''
        ## Design retry behavior deliberately

        A retry is appropriate when a failure is likely temporary. Common examples are
        `429 Too Many Requests`, `500`, `502`, `503`, `504`, connection resets, and
        timeouts. Retrying most `4xx` errors is wasteful because a bad credential or
        invalid request will not repair itself.

        Production guardrails include:

        - a maximum number of attempts;
        - bounded exponential backoff;
        - server-provided `Retry-After` when available;
        - connect/read timeouts;
        - structured logs containing attempt and request metadata;
        - a final exception rather than silently returning incomplete data.
        '''),
        code(r'''
        RETRYABLE_STATUS = {429, 500, 502, 503, 504}


        def get_json_with_retry(
            session: requests.Session,
            url: str,
            *,
            params: dict,
            max_attempts: int = 4,
            base_delay_seconds: float = 0.05,
        ) -> dict:
            for attempt in range(1, max_attempts + 1):
                try:
                    response = session.get(url, params=params, timeout=(2, 5))
                    if response.status_code not in RETRYABLE_STATUS:
                        response.raise_for_status()
                        return response.json()

                    if attempt == max_attempts:
                        response.raise_for_status()
                    delay = float(response.headers.get("Retry-After", base_delay_seconds * 2 ** (attempt - 1)))
                    delay = min(delay, 1.0)
                    LOGGER.warning(
                        "retryable HTTP response",
                        extra={"step": "extract", "attempt": attempt, "source": response.url},
                    )
                    time.sleep(delay)
                except (requests.Timeout, requests.ConnectionError):
                    if attempt == max_attempts:
                        raise
                    delay = min(base_delay_seconds * 2 ** (attempt - 1), 1.0)
                    LOGGER.warning(
                        "retryable network exception",
                        extra={"step": "extract", "attempt": attempt, "source": url},
                    )
                    time.sleep(delay)

            raise RuntimeError("unreachable: retry loop exhausted")


        with requests.Session() as session:
            sample = get_json_with_retry(session, API_URL, params={"limit": 2})
        sample
        '''),
        md(r'''
        ## Extract pages into an immutable Bronze run

        The checkpoint answers, “What source update time was successfully committed?”
        It is updated **after** every page and manifest are durable. Moving the checkpoint
        too early can permanently skip data after a crash.

        A `run_id` separates attempts. We do not overwrite an earlier raw page. The
        manifest provides control-plane metadata: counts, checksums, request IDs, and the
        watermark used by downstream jobs.
        '''),
        code(r'''
        def read_checkpoint() -> dict:
            if not CHECKPOINT_PATH.exists():
                return {"updated_after": None}
            return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))


        def extract_orders(page_size: int = 40) -> dict:
            started_at = datetime.now(timezone.utc)
            run_id = started_at.strftime("%Y%m%dT%H%M%S_%fZ")
            run_dir = BRONZE_API / f"ingestion_date={started_at.date()}" / f"run_id={run_id}"
            run_dir.mkdir(parents=True, exist_ok=False)

            prior_checkpoint = read_checkpoint()
            updated_after = prior_checkpoint.get("updated_after")
            cursor = None
            page_number = 0
            rows_seen = 0
            max_updated_at = updated_after
            pages = []

            LOGGER.info("extraction started", extra={"run_id": run_id, "step": "extract", "source": API_URL})
            with requests.Session() as session:
                while True:
                    params = {"limit": page_size}
                    if cursor is not None:
                        params["cursor"] = cursor
                    if updated_after:
                        params["updated_after"] = updated_after

                    envelope = get_json_with_retry(session, API_URL, params=params)
                    records = envelope.get("data")
                    if not isinstance(records, list):
                        raise TypeError("API contract violation: 'data' must be a list")
                    if not records:
                        break

                    page_number += 1
                    page_path = run_dir / f"page_{page_number:04d}.json"
                    atomic_write_json(page_path, envelope)
                    rows_seen += len(records)
                    page_max = max(record["updated_at"] for record in records)
                    max_updated_at = max(filter(None, [max_updated_at, page_max]))
                    pages.append(
                        {
                            "path": str(page_path.relative_to(PROJECT_ROOT)),
                            "row_count": len(records),
                            "bytes": page_path.stat().st_size,
                            "sha256": file_sha256(page_path),
                            "request_id": envelope.get("request_id"),
                        }
                    )
                    cursor = envelope.get("next_cursor")
                    if cursor is None:
                        break

            manifest = {
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "source": API_URL,
                "starting_watermark": updated_after,
                "ending_watermark": max_updated_at,
                "page_count": page_number,
                "record_count": rows_seen,
                "pages": pages,
                "status": "SUCCESS",
            }
            atomic_write_json(run_dir / "manifest.json", manifest)
            if max_updated_at != updated_after:
                atomic_write_json(CHECKPOINT_PATH, {"updated_after": max_updated_at, "committed_run_id": run_id})
            LOGGER.info(
                "extraction completed",
                extra={"run_id": run_id, "step": "extract", "record_count": rows_seen, "source": API_URL},
            )
            return manifest


        first_run = extract_orders()
        first_run
        '''),
        code(r'''
        # Checkpoint: the first run saved every source record and multiple raw pages.
        assert first_run["record_count"] == len(SOURCE_ORDERS)
        assert first_run["page_count"] > 1
        assert all(len(page["sha256"]) == 64 for page in first_run["pages"])
        assert CHECKPOINT_PATH.exists()

        # A second run uses the committed high watermark and finds no new records.
        second_run = extract_orders()
        assert second_run["record_count"] == 0
        assert second_run["starting_watermark"] == first_run["ending_watermark"]
        print("PASS: raw pages are auditable and the second run is incremental.")
        '''),
        md(r'''
        ## Ingest application logs as a file source

        APIs are only one source type. Companies also receive JSONL log files from
        services, agents, or object storage delivery jobs. The generator below includes
        nested context, a free-text message, an optional stack trace, and one malformed
        JSON line. Notebook 02 must parse good records without losing evidence of the bad
        record.
        '''),
        code(r'''
        rng = random.Random(29)
        log_path = BRONZE_LOGS / "event_date=2026-01-03" / "application_logs.jsonl.gz"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with gzip.open(log_path, "wt", encoding="utf-8") as destination:
            for index in range(250):
                level = "ERROR" if index % 31 == 0 else rng.choice(["INFO", "INFO", "WARN"])
                log_event = {
                    "event_id": f"log-{index:05d}",
                    "timestamp": (datetime(2026, 1, 3, tzinfo=timezone.utc) + timedelta(seconds=index * 13)).isoformat(),
                    "service": rng.choice(["checkout", "catalog", "payments"]),
                    "level": level,
                    "trace_id": f"trace-{rng.randint(1, 90):05d}",
                    "message": "Payment authorization failed" if level == "ERROR" else "Request completed",
                    "context": {
                        "customer_id": f"cust_{rng.randint(1, 60):04d}",
                        "latency_ms": rng.randint(5, 900),
                        "http": {"status": 503 if level == "ERROR" else 200},
                    },
                    "exception": {
                        "type": "PaymentGatewayError",
                        "stack_trace": "PaymentGatewayError: upstream unavailable\\n  at authorize(payment.py:81)",
                    } if level == "ERROR" else None,
                }
                destination.write(json.dumps(log_event) + "\n")
            destination.write('{"event_id": "broken", "timestamp": ')  # deliberate malformed line

        log_metadata = {
            "path": str(log_path.relative_to(PROJECT_ROOT)),
            "compressed_bytes": log_path.stat().st_size,
            "sha256": file_sha256(log_path),
        }
        log_metadata
        '''),
        md(r'''
        ## Optional real AWS S3 upload

        Local folders teach object-prefix design but do not count as AWS usage. If the
        student has an approved AWS learning account, an existing private bucket, budget
        controls, and `boto3`, set the environment variable `CAPSTONE_S3_BUCKET` and enable
        the cell below. Credentials must come from the standard AWS credential chain—never
        paste access keys into a notebook.

        The code uploads immutable Bronze pages and attaches their checksum as object
        metadata. It deliberately does not create or delete a bucket.
        '''),
        code(r'''
        import os

        RUN_AWS_S3_EXTENSION = False
        if RUN_AWS_S3_EXTENSION:
            import boto3

            bucket = os.environ["CAPSTONE_S3_BUCKET"]
            s3 = boto3.client("s3")
            uploaded = []
            for page in first_run["pages"]:
                local_path = PROJECT_ROOT / page["path"]
                key = f"bronze/api/orders/{local_path.parent.name}/{local_path.name}"
                s3.upload_file(
                    str(local_path),
                    bucket,
                    key,
                    ExtraArgs={"Metadata": {"sha256": page["sha256"]}},
                )
                uploaded.append(f"s3://{bucket}/{key}")
            print(f"Uploaded {len(uploaded)} immutable pages")
        else:
            print("AWS extension disabled; the zero-cost local Bronze layer remains active.")
        '''),
        md(r'''
        ## Operational reasoning

        **Why not flatten inside `extract_orders()`?** Extraction failures and business
        transformation failures have different recovery paths. Preserving the source
        envelope also protects us when transformation rules change.

        **Is the high watermark sufficient for every source?** No. If multiple records can
        share a timestamp or the source can publish late updates behind the watermark, use
        a composite cursor, overlap window, source sequence, or CDC log position.

        **Is a checksum a data-quality test?** It proves file integrity and helps detect
        accidental changes. It does not prove that the business values are correct.

        **Why not retry forever?** Infinite retry hides incidents, consumes resources, and
        can prevent downstream freshness guarantees. Exhausted retries should fail visibly.
        '''),
        md(r'''
        ## Your turn

        1. Modify the API to return `401` once. Confirm that the client does **not** retry it.
        2. Add a page-level record-count reconciliation to the manifest.
        3. Simulate a crash immediately before checkpoint commit. Explain what the next run
           will repeat and why downstream deduplication is still necessary.
        4. Replace timestamp-only state with `(updated_at, order_id)` state.
        5. Write a unit test using a fake session so retry behavior does not need a server.

        ### Two-minute interview answer

        Explain the source contract, transient failures, raw layout, checkpoint commit
        point, and evidence that the second run did not duplicate source data. Avoid saying
        “S3” unless you actually run the optional S3 extension; this core lab uses a local
        object-storage layout.
        '''),
        code(r'''
        # Release the local port. The raw files remain available to later notebooks.
        api_server.shutdown()
        api_server.server_close()
        api_thread.join(timeout=2)
        print("Local API stopped cleanly.")
        '''),
    ]


def notebook_02() -> list[dict]:
    return [
        md(r'''
        # 02 — PySpark Lakehouse Processing and CDC

        ## Business scenario

        Bronze now contains immutable API envelopes and compressed application logs. We
        need analytics-ready Silver tables without silently discarding malformed records.
        We also receive change-data-capture events for order updates and deletes.

        ### Learning objectives

        - Read nested JSON with an explicit Spark schema.
        - Handle schema evolution from `customer_id` to `customer.id`.
        - Normalize an order array into order and order-item tables.
        - Quarantine invalid records with reasons and source metadata.
        - Deduplicate at-least-once source delivery deterministically.
        - Write Hive-style partitioned Parquet.
        - Resolve out-of-order CDC events and prove idempotency.
        - Translate the rules to Delta Lake `MERGE` on Databricks.

        Run Notebook 01 first. Local PySpark requires Java 17+ and the packages in
        `requirements-spark.txt`.
        '''),
        code(r'''
        from pathlib import Path
        import json
        import sys

        PROJECT_ROOT = Path.cwd().resolve()
        if PROJECT_ROOT.name == "notebooks":
            PROJECT_ROOT = PROJECT_ROOT.parent
        sys.path.insert(0, str(PROJECT_ROOT))

        LAB_ROOT = PROJECT_ROOT / "lab_data"
        BRONZE_API = LAB_ROOT / "bronze" / "api" / "orders"
        BRONZE_LOGS = LAB_ROOT / "bronze" / "logs"
        SILVER_ROOT = LAB_ROOT / "silver"
        ORDERS_PATH = SILVER_ROOT / "orders"
        ITEMS_PATH = SILVER_ROOT / "order_items"
        QUARANTINE_PATH = SILVER_ROOT / "quarantine_orders"
        LOGS_PATH = SILVER_ROOT / "application_logs"
        CDC_PATH = LAB_ROOT / "bronze" / "cdc" / "orders_cdc.jsonl"

        raw_pages = sorted(BRONZE_API.glob("ingestion_date=*/run_id=*/page_*.json"))
        if not raw_pages:
            raise FileNotFoundError("No Bronze API pages found. Run notebook 01 first.")
        print(f"Discovered {len(raw_pages)} raw API pages")
        '''),
        md(r'''
        ## Start Spark intentionally

        `local[*]` uses multiple threads on one machine. It is valuable for learning Spark
        execution, partitions, lazy evaluation, and shuffle behavior, but it is **not** a
        multi-node cluster and should not be described as EMR operations experience.
        '''),
        code(r'''
        try:
            from pyspark.sql import SparkSession, Window
            from pyspark.sql import functions as F
            from pyspark.sql import types as T
        except ImportError as exc:
            raise RuntimeError(
                "PySpark is not installed. Run: python -m pip install -r requirements-spark.txt"
            ) from exc

        spark = (
            SparkSession.builder
            .master("local[*]")
            .appName("commerce-lakehouse-cdc")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.shuffle.partitions", "8")
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("WARN")
        print(spark.version)
        '''),
        md(r'''
        ## Use an explicit source schema

        Schema inference scans data and can make inconsistent choices when fields contain
        mixed types. A production ingestion contract should declare expected fields and
        preserve unknown or invalid values for investigation.

        `total_amount` is read as a string first. Casting belongs in transformation so a
        value such as `"not-a-number"` can be quarantined rather than turned into an
        unexplained null.
        '''),
        code(r'''
        item_schema = T.StructType([
            T.StructField("sku", T.StringType()),
            T.StructField("quantity", T.LongType()),
            T.StructField("unit_price", T.StringType()),
        ])
        customer_schema = T.StructType([
            T.StructField("id", T.StringType()),
            T.StructField("tier", T.StringType()),
        ])
        order_schema = T.StructType([
            T.StructField("order_id", T.StringType()),
            T.StructField("customer_id", T.StringType()),
            T.StructField("customer", customer_schema),
            T.StructField("event_type", T.StringType()),
            T.StructField("event_timestamp", T.StringType()),
            T.StructField("updated_at", T.StringType()),
            T.StructField("status", T.StringType()),
            T.StructField("currency", T.StringType()),
            T.StructField("total_amount", T.StringType()),
            T.StructField("items", T.ArrayType(item_schema)),
            T.StructField("schema_version", T.LongType()),
        ])
        envelope_schema = T.StructType([
            T.StructField("data", T.ArrayType(order_schema)),
            T.StructField("next_cursor", T.StringType()),
            T.StructField("request_id", T.StringType()),
            T.StructField("schema", T.StringType()),
        ])

        page_names = [str(path) for path in raw_pages]
        envelopes = (
            spark.read
            .schema(envelope_schema)
            .option("multiLine", True)
            .json(page_names)
            .withColumn("source_file", F.input_file_name())
        )
        orders_raw = envelopes.select(
            F.explode_outer("data").alias("order"), "request_id", "source_file"
        )
        orders_raw.printSchema()
        '''),
        code(r'''
        normalized = orders_raw.select(
            F.col("order.order_id").alias("order_id"),
            F.coalesce(F.col("order.customer_id"), F.col("order.customer.id")).alias("customer_id"),
            F.col("order.event_type").alias("event_type"),
            F.to_timestamp("order.event_timestamp").alias("event_timestamp"),
            F.to_timestamp("order.updated_at").alias("updated_at"),
            F.col("order.status").alias("status"),
            F.col("order.currency").alias("currency"),
            F.col("order.total_amount").alias("raw_total_amount"),
            F.col("order.total_amount").cast("decimal(18,2)").alias("total_amount"),
            F.col("order.items").alias("items"),
            F.col("order.schema_version").alias("schema_version"),
            "request_id",
            "source_file",
        ).withColumn("event_date", F.to_date("event_timestamp"))

        reason = (
            F.when(F.col("order_id").isNull(), F.lit("missing_order_id"))
            .when(F.col("customer_id").isNull(), F.lit("missing_customer_id"))
            .when(F.col("event_timestamp").isNull(), F.lit("invalid_event_timestamp"))
            .when(F.col("currency").isNull(), F.lit("missing_currency"))
            .when(F.col("total_amount").isNull(), F.lit("invalid_total_amount"))
            .when(F.size(F.coalesce(F.col("items"), F.array())) == 0, F.lit("missing_items"))
        )
        classified = normalized.withColumn("quarantine_reason", reason)
        quarantine = classified.filter(F.col("quarantine_reason").isNotNull())
        candidates = classified.filter(F.col("quarantine_reason").isNull()).drop("quarantine_reason")

        print("Raw rows:", normalized.count())
        print("Quarantined rows:", quarantine.count())
        quarantine.groupBy("quarantine_reason").count().orderBy("quarantine_reason").show(truncate=False)
        '''),
        md(r'''
        ## Deterministic deduplication

        `dropDuplicates("order_id")` does not express which duplicate wins. We define a
        stable ordering: latest source `updated_at`, then source file. This matters because
        Spark task order is not a business rule.
        '''),
        code(r'''
        dedupe_window = Window.partitionBy("order_id").orderBy(
            F.col("updated_at").desc_nulls_last(), F.col("source_file").desc()
        )
        ranked = candidates.withColumn("dedupe_rank", F.row_number().over(dedupe_window))
        duplicates = ranked.filter(F.col("dedupe_rank") > 1)
        valid_orders = ranked.filter(F.col("dedupe_rank") == 1).drop("dedupe_rank")

        valid_order_items = (
            valid_orders
            .select("order_id", "event_date", F.posexplode("items").alias("line_offset", "item"))
            .select(
                "order_id",
                "event_date",
                (F.col("line_offset") + 1).alias("line_number"),
                F.col("item.sku").alias("sku"),
                F.col("item.quantity").cast("long").alias("quantity"),
                F.col("item.unit_price").cast("decimal(18,2)").alias("unit_price"),
            )
        )

        quality_metrics = {
            "input_count": normalized.count(),
            "valid_order_count": valid_orders.count(),
            "quarantine_count": quarantine.count(),
            "duplicate_count": duplicates.count(),
            "item_count": valid_order_items.count(),
        }
        assert quality_metrics["input_count"] == (
            quality_metrics["valid_order_count"]
            + quality_metrics["quarantine_count"]
            + quality_metrics["duplicate_count"]
        )
        quality_metrics
        '''),
        md(r'''
        ## Write Silver tables with useful partitions

        We partition orders by `event_date`, a low-cardinality field commonly used by
        incremental jobs and date-range queries. We do **not** partition by high-cardinality
        `order_id`; that would create excessive directories and small files.

        `mode("overwrite")` is acceptable for this controlled rebuild lesson. A production
        job should overwrite only affected partitions or use a transactional table format.
        '''),
        code(r'''
        (
            valid_orders.drop("items")
            .repartition("event_date")
            .write.mode("overwrite")
            .partitionBy("event_date")
            .parquet(str(ORDERS_PATH))
        )
        (
            valid_order_items
            .repartition("event_date")
            .write.mode("overwrite")
            .partitionBy("event_date")
            .parquet(str(ITEMS_PATH))
        )
        quarantine.write.mode("overwrite").json(str(QUARANTINE_PATH))

        print("Order partitions:")
        for path in sorted(ORDERS_PATH.glob("event_date=*")):
            print(" -", path.name)
        '''),
        md(r'''
        ## Parse nested application logs and preserve corrupt input

        A malformed log line must not terminate the entire batch, but it also must not
        disappear. Spark's permissive parser can retain the original line in a corrupt
        record column. That record goes to quarantine with source metadata.
        '''),
        code(r'''
        log_schema = T.StructType([
            T.StructField("event_id", T.StringType()),
            T.StructField("timestamp", T.StringType()),
            T.StructField("service", T.StringType()),
            T.StructField("level", T.StringType()),
            T.StructField("trace_id", T.StringType()),
            T.StructField("message", T.StringType()),
            T.StructField("context", T.StructType([
                T.StructField("customer_id", T.StringType()),
                T.StructField("latency_ms", T.LongType()),
                T.StructField("http", T.StructType([T.StructField("status", T.LongType())])),
            ])),
            T.StructField("exception", T.StructType([
                T.StructField("type", T.StringType()),
                T.StructField("stack_trace", T.StringType()),
            ])),
            T.StructField("_corrupt_record", T.StringType()),
        ])
        log_files = [str(path) for path in BRONZE_LOGS.glob("event_date=*/*.jsonl.gz")]
        logs_raw = (
            spark.read.schema(log_schema)
            .option("mode", "PERMISSIVE")
            .option("columnNameOfCorruptRecord", "_corrupt_record")
            .json(log_files)
            .withColumn("source_file", F.input_file_name())
        ).cache()
        logs_raw.count()  # Materialize before querying the corrupt-record column alone.
        clean_logs = logs_raw.filter(F.col("_corrupt_record").isNull()).select(
            "event_id",
            F.to_timestamp("timestamp").alias("event_timestamp"),
            "service", "level", "trace_id", "message",
            F.col("context.customer_id").alias("customer_id"),
            F.col("context.latency_ms").alias("latency_ms"),
            F.col("context.http.status").alias("http_status"),
            F.col("exception.type").alias("exception_type"),
            F.col("exception.stack_trace").alias("stack_trace"),
            "source_file",
        ).withColumn("event_date", F.to_date("event_timestamp"))
        corrupt_logs = logs_raw.filter(F.col("_corrupt_record").isNotNull())

        clean_logs.write.mode("overwrite").partitionBy("event_date").parquet(str(LOGS_PATH))
        print("Clean logs:", clean_logs.count(), "Corrupt logs:", corrupt_logs.count())
        assert corrupt_logs.count() == 1
        '''),
        md(r'''
        ## Change data capture: define ordering before code

        Each event has an operation (`I`, `U`, `D`) and a monotonically increasing source
        `sequence_no`. Arrival order is deliberately scrambled. For each `order_id`, the
        greatest sequence is authoritative. Deletes remove the current row.

        Event time alone is not a safe tiebreaker. Database log sequence numbers or source
        offsets are stronger when available.
        '''),
        code(r'''
        seed_orders = valid_orders.select(
            "order_id", "customer_id", "status", "currency", "total_amount", "updated_at"
        ).limit(12)
        seed_ids = [row.order_id for row in seed_orders.select("order_id").collect()]

        cdc_events = [
            {"order_id": seed_ids[0], "op": "U", "sequence_no": 102, "status": "shipped", "total_amount": "88.00"},
            {"order_id": seed_ids[0], "op": "U", "sequence_no": 101, "status": "paid", "total_amount": "88.00"},
            {"order_id": seed_ids[1], "op": "D", "sequence_no": 103, "status": None, "total_amount": None},
            {"order_id": "ord_999999", "op": "I", "sequence_no": 104, "status": "paid", "total_amount": "42.50"},
            {"order_id": "ord_999999", "op": "I", "sequence_no": 104, "status": "paid", "total_amount": "42.50"},
        ]
        CDC_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CDC_PATH.open("w", encoding="utf-8") as destination:
            for event in cdc_events:
                destination.write(json.dumps(event) + "\n")

        cdc_schema = "order_id string, op string, sequence_no long, status string, total_amount decimal(18,2)"
        changes = spark.read.schema(cdc_schema).json(str(CDC_PATH))
        changes.orderBy("sequence_no", "order_id").show()
        '''),
        code(r'''
        def apply_cdc(current_df, change_df):
            latest = (
                change_df
                .withColumn(
                    "rn",
                    F.row_number().over(
                        Window.partitionBy("order_id").orderBy(F.col("sequence_no").desc())
                    ),
                )
                .filter("rn = 1")
                .drop("rn")
            )
            delete_ids = latest.filter("op = 'D'").select("order_id")
            survivors = current_df.join(delete_ids, "order_id", "left_anti")
            upserts = latest.filter("op IN ('I', 'U')").select(
                "order_id", "status", "total_amount", "sequence_no"
            )

            unchanged = survivors.join(upserts.select("order_id"), "order_id", "left_anti").select(
                "order_id", "status", "total_amount"
            ).withColumn("sequence_no", F.lit(0).cast("long"))
            return unchanged.unionByName(upserts).orderBy("order_id")


        current = seed_orders.select("order_id", "status", "total_amount")
        snapshot_once = apply_cdc(current, changes)
        snapshot_twice = apply_cdc(snapshot_once.select("order_id", "status", "total_amount"), changes)

        assert snapshot_once.collect() == snapshot_twice.collect()
        assert snapshot_once.filter(F.col("order_id") == seed_ids[1]).count() == 0
        assert snapshot_once.filter(F.col("order_id") == "ord_999999").count() == 1
        snapshot_once.show(truncate=False)
        print("PASS: the CDC snapshot is idempotent for this event set.")
        '''),
        md(r'''
        ## Optional Databricks Free Edition: Delta Lake MERGE

        The local reference function rebuilds a tiny current snapshot so the logic remains
        dependency-free. On Databricks, write `current` as Delta and use a transactional
        `MERGE`:

        ```sql
        MERGE INTO silver.orders_current AS target
        USING latest_cdc AS source
        ON target.order_id = source.order_id
        WHEN MATCHED AND source.op = 'D' THEN DELETE
        WHEN MATCHED AND source.op = 'U' THEN UPDATE SET *
        WHEN NOT MATCHED AND source.op = 'I' THEN INSERT *
        ```

        Before `MERGE`, reduce multiple events per key to the greatest `sequence_no`.
        Otherwise multiple source rows can attempt to mutate the same target row.

        Databricks Free Edition is suitable for this educational extension. It is a real
        managed workspace with quotas, not production platform administration experience.
        '''),
        md(r'''
        ## Your turn

        1. Add an unknown `op = 'X'` event and quarantine it.
        2. Add a source sequence checkpoint so events at or below the committed sequence
           are ignored safely.
        3. Compare the physical plan of the CDC window with the final anti join.
        4. Implement the same current-state result with Delta `MERGE` in Databricks.
        5. Write tests for a delete of a missing key and two events sharing a timestamp.

        ### Interview checkpoint

        Be ready to explain explicit schemas, schema evolution, deterministic deduplication,
        quarantine, partition choice, late CDC events, and the exact reason the sink is
        idempotent.
        '''),
    ]


def notebook_03() -> list[dict]:
    return [
        md(r'''
        # 03 — Spark Performance, Partitioning, Caching, and Cost

        ## The engineering question

        “Partitioning is faster” and “cache improves performance” are incomplete answers.
        Performance depends on query predicates, cardinality, file sizes, reuse, memory,
        serialization, and shuffle boundaries. This lab collects evidence for each choice.

        ### Learning objectives

        - Separate Spark partitions from storage partitions.
        - Identify exchanges and scans in a physical plan.
        - Measure file count, bytes, and repeated-action time.
        - Demonstrate partition pruning.
        - Compare repartition and coalesce.
        - Use broadcast joins intentionally.
        - Explain when caching helps and when it wastes memory.
        - Convert bytes scanned into a configurable cost estimate.
        '''),
        code(r'''
        from pathlib import Path
        from time import perf_counter
        import shutil

        PROJECT_ROOT = Path.cwd().resolve()
        if PROJECT_ROOT.name == "notebooks":
            PROJECT_ROOT = PROJECT_ROOT.parent
        PERF_ROOT = PROJECT_ROOT / "lab_data" / "performance"
        if PERF_ROOT.exists():
            assert PERF_ROOT.name == "performance" and PROJECT_ROOT in PERF_ROOT.parents
            shutil.rmtree(PERF_ROOT)
        PERF_ROOT.mkdir(parents=True)

        try:
            from pyspark.sql import SparkSession
            from pyspark.sql import functions as F
            from pyspark.sql import types as T
        except ImportError as exc:
            raise RuntimeError("Install requirements-spark.txt before this lab") from exc

        spark = (
            SparkSession.builder.master("local[*]")
            .appName("spark-performance-cost-lab")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.shuffle.partitions", "16")
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("WARN")
        '''),
        md(r'''
        ## Generate a scalable workload without driver memory pressure

        `spark.range()` creates data across Spark partitions. We avoid constructing a
        million Python dictionaries on the driver. Increase `ROW_COUNT` only after the
        baseline works on the student's machine.
        '''),
        code(r'''
        ROW_COUNT = 1_000_000  # Try 3–10 million on a machine with adequate memory.
        INITIAL_PARTITIONS = max(4, spark.sparkContext.defaultParallelism * 2)
        base_epoch = 1767225600  # 2026-01-01T00:00:00Z

        events = (
            spark.range(ROW_COUNT, numPartitions=INITIAL_PARTITIONS)
            .withColumn("event_id", F.concat(F.lit("evt-"), F.lpad(F.col("id"), 10, "0")))
            .withColumn("customer_id", F.concat(F.lit("cust-"), F.lpad((F.col("id") % 50_000), 6, "0")))
            .withColumn("event_timestamp", F.timestamp_seconds(F.lit(base_epoch) + (F.col("id") % (30 * 86400))))
            .withColumn("event_date", F.to_date("event_timestamp"))
            .withColumn("event_type", F.expr("CASE WHEN id % 20 = 0 THEN 'purchase' WHEN id % 4 = 0 THEN 'cart' ELSE 'view' END"))
            .withColumn("region", F.expr("CASE WHEN id % 10 < 6 THEN 'US-EAST' WHEN id % 10 < 8 THEN 'US-WEST' ELSE 'OTHER' END"))
            .withColumn("amount", F.when(F.col("event_type") == "purchase", (F.col("id") % 200 + 1).cast("double")).otherwise(0.0))
            .drop("id")
        )
        print("Logical partitions:", events.rdd.getNumPartitions())
        events.printSchema()
        '''),
        md(r'''
        ## Storage layout experiment

        Both datasets contain the same rows. One is a set of Parquet files in one
        directory; the other uses Hive-style `event_date=...` prefixes. A date predicate
        can prune unrelated storage partitions only in the second layout.
        '''),
        code(r'''
        UNPARTITIONED = PERF_ROOT / "events_unpartitioned"
        PARTITIONED = PERF_ROOT / "events_partitioned"

        events.repartition(8).write.mode("overwrite").parquet(str(UNPARTITIONED))
        (
            events.repartition("event_date")
            .write.mode("overwrite")
            .partitionBy("event_date")
            .parquet(str(PARTITIONED))
        )


        def parquet_stats(path: Path) -> dict:
            files = list(path.rglob("*.parquet"))
            total_bytes = sum(file.stat().st_size for file in files)
            return {
                "files": len(files),
                "total_mb": round(total_bytes / 1024**2, 2),
                "average_file_mb": round(total_bytes / max(len(files), 1) / 1024**2, 2),
            }


        layout_stats = {
            "unpartitioned": parquet_stats(UNPARTITIONED),
            "partitioned": parquet_stats(PARTITIONED),
        }
        layout_stats
        '''),
        code(r'''
        def timed_count(frame, label: str) -> dict:
            started = perf_counter()
            rows = frame.count()
            elapsed = perf_counter() - started
            result = {"label": label, "rows": rows, "seconds": round(elapsed, 3)}
            print(result)
            return result


        target_date = "2026-01-07"
        unpartitioned_read = spark.read.parquet(str(UNPARTITIONED)).filter(F.col("event_date") == target_date)
        partitioned_read = spark.read.parquet(str(PARTITIONED)).filter(F.col("event_date") == target_date)

        unpartitioned_result = timed_count(unpartitioned_read, "unpartitioned date filter")
        partitioned_result = timed_count(partitioned_read, "partitioned date filter")
        assert unpartitioned_result["rows"] == partitioned_result["rows"]

        print("\nPartitioned physical plan:")
        partitioned_read.explain("formatted")
        '''),
        md(r'''
        ### Read the plan, not just the stopwatch

        Local timings vary because of operating-system cache, JIT warm-up, background
        work, and file-system behavior. In the formatted plan, find `PartitionFilters`.
        That is stronger evidence that Spark can skip unrelated date directories.

        Partitioning has a cost: too many partition keys produce many directories and tiny
        files. Choose keys used frequently in filters and avoid high-cardinality identifiers.
        '''),
        md(r'''
        ## Shuffle, repartition, and coalesce

        - `repartition(n)` can increase or decrease partitions and normally performs a full
          shuffle.
        - `coalesce(n)` usually reduces partitions without a full shuffle, but may create
          uneven work.
        - `groupBy`, `distinct`, joins, and window functions commonly create exchanges.

        Search the plans below for `Exchange`.
        '''),
        code(r'''
        print("Partitions before:", events.rdd.getNumPartitions())
        print("After repartition(24):", events.repartition(24).rdd.getNumPartitions())
        print("After coalesce(4):", events.coalesce(4).rdd.getNumPartitions())

        revenue_by_customer = events.groupBy("customer_id").agg(F.sum("amount").alias("revenue"))
        revenue_by_customer.explain("formatted")

        for shuffle_partitions in (4, 16, 64):
            spark.conf.set("spark.sql.shuffle.partitions", shuffle_partitions)
            result = timed_count(revenue_by_customer, f"groupBy with {shuffle_partitions} shuffle partitions")
        '''),
        md(r'''
        ## Broadcast a genuinely small dimension

        A broadcast join sends the small relation to executors and avoids shuffling the
        large fact relation. Broadcasting a table that does not fit executor memory can
        fail the job, so “always broadcast dimensions” is not a valid rule.
        '''),
        code(r'''
        regions = spark.createDataFrame(
            [("US-EAST", "North America"), ("US-WEST", "North America"), ("OTHER", "Other")],
            ["region", "market"],
        )
        normal_join = events.join(regions, "region")
        broadcast_join = events.join(F.broadcast(regions), "region")

        print("Normal join plan:")
        normal_join.explain("formatted")
        print("Broadcast join plan:")
        broadcast_join.explain("formatted")
        assert normal_join.count() == broadcast_join.count() == ROW_COUNT
        '''),
        md(r'''
        ## Built-in expressions versus Python UDFs

        Spark can optimize built-in SQL expressions. A standard Python UDF crosses a
        serialization boundary and hides logic from Catalyst. Use one only when the logic
        cannot be expressed with supported functions, then measure it.
        '''),
        code(r'''
        @F.udf(returnType=T.StringType())
        def python_value_band(amount):
            if amount is None or amount == 0:
                return "none"
            return "high" if amount >= 100 else "low"


        builtin = events.withColumn(
            "value_band",
            F.when(F.col("amount") == 0, "none").when(F.col("amount") >= 100, "high").otherwise("low"),
        )
        udf_version = events.withColumn("value_band", python_value_band("amount"))

        timed_count(builtin.groupBy("value_band").count(), "Spark built-in expression")
        timed_count(udf_version.groupBy("value_band").count(), "Python UDF")
        '''),
        md(r'''
        ## Cache only reused, expensive intermediate results

        Spark is lazy. `cache()` marks a DataFrame for persistence, but the first action
        materializes it. A one-use DataFrame often becomes slower because cache population
        itself costs CPU and memory. We reuse the same filtered relation twice.
        '''),
        code(r'''
        purchases = events.filter(F.col("event_type") == "purchase")

        uncached_a = timed_count(purchases.groupBy("region").count(), "uncached action 1")
        uncached_b = timed_count(purchases.groupBy("event_date").count(), "uncached action 2")

        cached_purchases = purchases.cache()
        materialize = timed_count(cached_purchases, "cache materialization")
        cached_a = timed_count(cached_purchases.groupBy("region").count(), "cached action 1")
        cached_b = timed_count(cached_purchases.groupBy("event_date").count(), "cached action 2")
        cached_purchases.unpersist()
        '''),
        md(r'''
        ## Translate scan reduction into a cost model

        Query services such as Athena charge primarily by bytes scanned. The function below
        is an educational estimate, not a pricing promise. Supply the vendor's current
        price and use engine-reported scanned bytes when available.
        '''),
        code(r'''
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.capstone_utils import estimate_scan_cost

        PRICE_PER_TB_EXAMPLE = 5.00
        all_bytes = sum(file.stat().st_size for file in PARTITIONED.rglob("*.parquet"))
        selected_partition = PARTITIONED / f"event_date={target_date}"
        selected_bytes = sum(file.stat().st_size for file in selected_partition.rglob("*.parquet"))

        cost_comparison = {
            "all_data_bytes": all_bytes,
            "selected_partition_bytes": selected_bytes,
            "estimated_full_scan_cost": estimate_scan_cost(all_bytes, PRICE_PER_TB_EXAMPLE),
            "estimated_pruned_scan_cost": estimate_scan_cost(selected_bytes, PRICE_PER_TB_EXAMPLE),
            "estimated_bytes_reduction_pct": round((1 - selected_bytes / all_bytes) * 100, 2),
        }
        cost_comparison
        '''),
        md(r'''
        ## Your turn

        1. Partition by `customer_id` and document the small-file problem.
        2. Create one customer responsible for 40% of events. Diagnose skew in the Spark UI.
        3. Try salting the skewed join and compare correctness and plan complexity.
        4. Run the cache experiment with only one action. Explain the result.
        5. Record cold and warm runs separately in a Pandas results table.
        6. Use the Spark UI SQL tab to capture scan, shuffle-read, and shuffle-write metrics.

        ### Interview checkpoint

        Do not say “partitioning makes queries faster.” State the filter pattern, partition
        cardinality, pruning evidence, file-count trade-off, and measured outcome.
        '''),
    ]


def notebook_04() -> list[dict]:
    return [
        md(r'''
        # 04 — Warehouse ELT, Dimensional Modeling, and Cloud Translation

        ## Business scenario

        Analysts need stable SQL tables for daily revenue, customer behavior, and service
        reliability. Silver Parquet is clean enough to reuse, but it is not yet a governed
        business model.

        This notebook uses DuckDB as a free local columnar analytical engine. DuckDB is not
        Redshift/Snowflake or BigQuery; it lets us practice ELT SQL and inspect plans before translating
        the design to a managed warehouse.

        ### Learning objectives

        - Query partitioned Parquet without loading it into Pandas.
        - Separate staging, dimensions, facts, and marts.
        - Enforce grain and reconciliation checks.
        - Build an SCD Type 2 customer history.
        - inspect `EXPLAIN` output.
        - Translate storage choices to BigQuery partitions/clusters, AWS sort/dist keys,
          and Snowflake clustering and micro-partition pruning.
        - Understand how Airflow should orchestrate these jobs.
        '''),
        code(r'''
        from pathlib import Path
        import sys

        import pandas as pd

        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("Install requirements-core.txt before this lab") from exc

        PROJECT_ROOT = Path.cwd().resolve()
        if PROJECT_ROOT.name == "notebooks":
            PROJECT_ROOT = PROJECT_ROOT.parent
        LAB_ROOT = PROJECT_ROOT / "lab_data"
        SILVER_ORDERS = LAB_ROOT / "silver" / "orders"
        SILVER_ITEMS = LAB_ROOT / "silver" / "order_items"
        WAREHOUSE_PATH = LAB_ROOT / "warehouse" / "commerce.duckdb"
        GOLD_ROOT = LAB_ROOT / "gold"
        WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLD_ROOT.mkdir(parents=True, exist_ok=True)

        if not list(SILVER_ORDERS.rglob("*.parquet")):
            raise FileNotFoundError("Silver Parquet not found. Run notebooks 01 and 02 first.")

        connection = duckdb.connect(str(WAREHOUSE_PATH))
        orders_glob = (SILVER_ORDERS / "**" / "*.parquet").as_posix()
        items_glob = (SILVER_ITEMS / "**" / "*.parquet").as_posix()
        '''),
        md(r'''
        ## Define table grain before writing SQL

        - `stg_orders`: one row per `order_id`.
        - `stg_order_items`: one row per (`order_id`, `line_number`).
        - `dim_customer`: one row per current customer.
        - `dim_date`: one row per calendar date.
        - `fact_order`: one row per order.
        - `fact_order_item`: one row per order line.

        Grain is a contract. If two rows unexpectedly represent the same order, sums can
        double even though the SQL query succeeds.
        '''),
        code(r'''
        connection.execute(f"""
            CREATE OR REPLACE TABLE stg_orders AS
            SELECT *
            FROM read_parquet('{orders_glob}', hive_partitioning = true)
        """)
        connection.execute(f"""
            CREATE OR REPLACE TABLE stg_order_items AS
            SELECT *
            FROM read_parquet('{items_glob}', hive_partitioning = true)
        """)

        staging_counts = connection.execute("""
            SELECT
                (SELECT COUNT(*) FROM stg_orders) AS order_rows,
                (SELECT COUNT(DISTINCT order_id) FROM stg_orders) AS distinct_orders,
                (SELECT COUNT(*) FROM stg_order_items) AS item_rows
        """).df()
        staging_counts
        '''),
        code(r'''
        connection.execute("""
            CREATE OR REPLACE TABLE dim_customer AS
            SELECT
                ROW_NUMBER() OVER (ORDER BY customer_id) AS customer_key,
                customer_id,
                MIN(event_timestamp) AS first_seen_at,
                MAX(updated_at) AS last_seen_at
            FROM stg_orders
            GROUP BY customer_id
        """)

        connection.execute("""
            CREATE OR REPLACE TABLE dim_date AS
            SELECT
                CAST(d AS DATE) AS date_key,
                EXTRACT(year FROM d)::INTEGER AS year,
                EXTRACT(month FROM d)::INTEGER AS month,
                EXTRACT(day FROM d)::INTEGER AS day,
                STRFTIME(d, '%A') AS day_name
            FROM GENERATE_SERIES(DATE '2026-01-01', DATE '2026-12-31', INTERVAL 1 DAY) t(d)
        """)

        connection.execute("""
            CREATE OR REPLACE TABLE fact_order AS
            SELECT
                o.order_id,
                c.customer_key,
                o.customer_id,
                CAST(o.event_date AS DATE) AS order_date,
                o.status,
                o.currency,
                o.total_amount,
                o.updated_at
            FROM stg_orders o
            JOIN dim_customer c USING (customer_id)
        """)

        connection.execute("""
            CREATE OR REPLACE TABLE fact_order_item AS
            SELECT
                i.order_id,
                i.line_number,
                i.sku,
                i.quantity,
                i.unit_price,
                i.quantity * i.unit_price AS line_amount,
                CAST(i.event_date AS DATE) AS order_date
            FROM stg_order_items i
        """)
        '''),
        md(r'''
        ## Quality gates belong next to the model

        Tests should describe business invariants, not merely confirm that a DataFrame
        exists. These checks fail loudly when the declared grains or relationships break.
        '''),
        code(r'''
        quality_checks = {
            "duplicate_order_ids": connection.execute(
                "SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM fact_order"
            ).fetchone()[0],
            "orphan_order_items": connection.execute("""
                SELECT COUNT(*)
                FROM fact_order_item i
                LEFT JOIN fact_order o USING (order_id)
                WHERE o.order_id IS NULL
            """).fetchone()[0],
            "missing_customer_keys": connection.execute(
                "SELECT COUNT(*) FROM fact_order WHERE customer_key IS NULL"
            ).fetchone()[0],
            "nonpositive_item_values": connection.execute(
                "SELECT COUNT(*) FROM fact_order_item WHERE quantity <= 0 OR unit_price < 0"
            ).fetchone()[0],
        }
        assert all(value == 0 for value in quality_checks.values()), quality_checks
        quality_checks
        '''),
        md(r'''
        ## Build a business mart and reconcile money

        An order total and the sum of its lines can differ because of tax, shipping,
        discounts, or bad source data. A data engineer should make the expected rule
        explicit rather than assume equality silently. Here the source generator defines
        total as the item sum, so we test a small decimal tolerance.
        '''),
        code(r'''
        reconciliation = connection.execute("""
            WITH item_totals AS (
                SELECT order_id, SUM(line_amount) AS item_total
                FROM fact_order_item
                GROUP BY order_id
            )
            SELECT
                COUNT(*) FILTER (WHERE ABS(o.total_amount - i.item_total) > 0.01) AS mismatched_orders,
                MAX(ABS(o.total_amount - i.item_total)) AS maximum_difference
            FROM fact_order o
            JOIN item_totals i USING (order_id)
        """).df()
        assert reconciliation.loc[0, "mismatched_orders"] == 0
        reconciliation
        '''),
        code(r'''
        connection.execute("""
            CREATE OR REPLACE TABLE mart_daily_sales AS
            SELECT
                o.order_date,
                COUNT(*) AS order_count,
                COUNT(DISTINCT o.customer_id) AS purchasing_customers,
                SUM(o.total_amount) AS gross_revenue,
                AVG(o.total_amount) AS average_order_value,
                SUM(CASE WHEN o.status = 'shipped' THEN o.total_amount ELSE 0 END) AS shipped_revenue
            FROM fact_order o
            GROUP BY o.order_date
            ORDER BY o.order_date
        """)
        connection.execute("SELECT * FROM mart_daily_sales ORDER BY order_date LIMIT 10").df()
        '''),
        md(r'''
        ## Slowly changing dimension Type 2

        SCD2 preserves attribute history rather than overwriting the old value. Each
        customer version has an effective interval and one current row. The example uses
        a customer tier change; in a real load, the transaction must make the expiration
        and insertion atomic.
        '''),
        code(r'''
        connection.execute("""
            CREATE OR REPLACE TABLE dim_customer_scd AS
            SELECT
                customer_key * 10 AS customer_version_key,
                customer_id,
                'standard'::VARCHAR AS customer_tier,
                TIMESTAMP '2026-01-01 00:00:00' AS effective_from,
                TIMESTAMP '9999-12-31 00:00:00' AS effective_to,
                TRUE AS is_current
            FROM dim_customer
        """)

        changed_customer = connection.execute(
            "SELECT customer_id FROM dim_customer ORDER BY customer_id LIMIT 1"
        ).fetchone()[0]
        effective_time = "2026-02-01 09:00:00"

        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(
                """UPDATE dim_customer_scd
                   SET effective_to = ?::TIMESTAMP, is_current = FALSE
                   WHERE customer_id = ? AND is_current = TRUE""",
                [effective_time, changed_customer],
            )
            next_key = connection.execute(
                "SELECT COALESCE(MAX(customer_version_key), 0) + 1 FROM dim_customer_scd"
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO dim_customer_scd VALUES
                   (?, ?, 'plus', ?::TIMESTAMP, TIMESTAMP '9999-12-31 00:00:00', TRUE)""",
                [next_key, changed_customer, effective_time],
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise

        history = connection.execute(
            """SELECT customer_version_key, customer_id, customer_tier,
                      CAST(effective_from AS VARCHAR) AS effective_from,
                      CAST(effective_to AS VARCHAR) AS effective_to,
                      is_current
               FROM dim_customer_scd
               WHERE customer_id = ?
               ORDER BY effective_from""",
            [changed_customer],
        ).df()
        assert len(history) == 2 and history["is_current"].sum() == 1
        history
        '''),
        md(r'''
        ## Inspect the query plan

        Managed MPP warehouses and DuckDB have different optimizers and execution
        architectures. The transferable habit is to inspect the plan for scans, filters,
        join strategy, and cardinality rather than tuning from folklore.
        '''),
        code(r'''
        explain_rows = connection.execute("""
            EXPLAIN ANALYZE
            SELECT c.customer_id, SUM(o.total_amount) AS revenue
            FROM fact_order o
            JOIN dim_customer c USING (customer_key)
            WHERE o.order_date BETWEEN DATE '2026-01-01' AND DATE '2026-01-07'
            GROUP BY c.customer_id
            ORDER BY revenue DESC
            LIMIT 10
        """).fetchall()
        print("\n".join(str(row[1]) for row in explain_rows))
        '''),
        code(r'''
        gold_path = (GOLD_ROOT / "mart_daily_sales.parquet").as_posix()
        connection.execute(f"COPY mart_daily_sales TO '{gold_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        print(f"Published: {gold_path}")
        '''),
        md(r'''
        ## Translate the design to BigQuery and Redshift/Snowflake

        ### BigQuery

        - Partition `fact_order` by `order_date`.
        - Cluster by frequently filtered/joined columns such as `customer_id` and `status`.
        - Preview estimated bytes before running a query.
        - Use the no-credit-card BigQuery sandbox for a small real-cloud exercise.

        See `sql/bigquery_reference.sql`.

        ### Redshift/Snowflake

        - On the AWS platform, choose `DISTKEY` or `SORTKEY` from workload evidence.
        - On Snowflake, inspect automatic micro-partition pruning before adding clustering keys.
        - Load columnar files through each platform's `COPY` or staged-file workflow.
        - Analyze query plans and table statistics.
        - A local DuckDB run does not prove Redshift/Snowflake administration experience.

        See `sql/redshift_reference.sql` for AWS-specific DDL and adapt the concepts rather
        than copying that syntax into Snowflake. Redshift/Snowflake cloud trials are optional,
        time-limited exercises because eligibility and cost controls differ from the core free lab.
        '''),
        md(r'''
        ## Airflow orchestration

        The included `dags/commerce_pipeline_dag.py` demonstrates:

        - a daily logical data interval;
        - catchup/backfill;
        - bounded task retries;
        - small metadata passed between tasks;
        - a quality gate that fails visibly;
        - persisted run metrics.

        Start it with `docker compose -f docker-compose.airflow.yml up`. Airflow should
        orchestrate versioned jobs; production transformations should not live only inside
        notebook cells.

        ### Your turn

        1. Add a uniqueness failure and confirm the quality gate blocks publication.
        2. Make the SCD2 change idempotent for a repeated change event.
        3. Add a `fact_application_error` table from the Silver logs.
        4. Port `mart_daily_sales` to BigQuery sandbox and compare SQL differences.
        5. Explain how you would backfill only `2026-01-07` in Airflow.
        '''),
    ]


def notebook_05() -> list[dict]:
    return [
        md(r'''
        # 05 — Kafka Streaming, Offsets, Replay, and Idempotent Sinks

        ## Business scenario

        Checkout services publish order-status events continuously. A consumer can crash
        after writing output but before committing its offset, so a record may be delivered
        again. The sink must remain correct under at-least-once delivery.

        This notebook runs in deterministic simulation mode by default. That mode teaches
        the state transitions without Docker. The optional section uses the included real
        Apache Kafka container. Do not describe simulation mode as Kafka broker experience.

        ### Learning objectives

        - Explain topics, keys, partitions, consumer groups, and offsets.
        - Observe how a key provides stable partition affinity.
        - Separate processing from offset commit.
        - Replay a batch and keep an idempotent sink correct.
        - Distinguish event time from processing time and identify late events.
        - Run the same ideas against a real local Kafka broker.
        '''),
        code(r'''
        from dataclasses import dataclass
        from datetime import datetime, timedelta, timezone
        from hashlib import sha256
        from pathlib import Path
        from typing import Any
        import json
        import random
        import time

        PROJECT_ROOT = Path.cwd().resolve()
        if PROJECT_ROOT.name == "notebooks":
            PROJECT_ROOT = PROJECT_ROOT.parent
        STREAM_ROOT = PROJECT_ROOT / "lab_data" / "streaming"
        STREAM_ROOT.mkdir(parents=True, exist_ok=True)
        '''),
        md(r'''
        ## A small simulator with Kafka-like state

        The simulator is intentionally limited; it is not a broker. It makes three pieces
        of state visible:

        - an append-only log for each partition;
        - the next offset for each consumer group and partition;
        - a sink keyed by unique `event_id`.

        We use SHA-256 rather than Python's built-in `hash()` so key-to-partition mapping is
        stable across interpreter restarts.
        '''),
        code(r'''
        @dataclass(frozen=True)
        class Message:
            topic: str
            partition: int
            offset: int
            key: str
            value: dict[str, Any]


        class LocalKafkaSimulator:
            def __init__(self, topic: str, partitions: int = 3):
                self.topic = topic
                self.logs: list[list[Message]] = [[] for _ in range(partitions)]
                self.group_offsets: dict[tuple[str, int], int] = {}

            def _partition_for(self, key: str) -> int:
                return int(sha256(key.encode()).hexdigest(), 16) % len(self.logs)

            def produce(self, key: str, value: dict[str, Any]) -> Message:
                partition = self._partition_for(key)
                message = Message(self.topic, partition, len(self.logs[partition]), key, value)
                self.logs[partition].append(message)
                return message

            def poll(self, group_id: str, max_records: int = 10) -> list[Message]:
                result = []
                for partition, log in enumerate(self.logs):
                    next_offset = self.group_offsets.get((group_id, partition), 0)
                    for message in log[next_offset:]:
                        result.append(message)
                        if len(result) == max_records:
                            return result
                return result

            def commit(self, group_id: str, messages: list[Message]) -> None:
                for message in messages:
                    key = (group_id, message.partition)
                    self.group_offsets[key] = max(self.group_offsets.get(key, 0), message.offset + 1)

            def reset_group(self, group_id: str) -> None:
                for partition in range(len(self.logs)):
                    self.group_offsets[(group_id, partition)] = 0


        broker = LocalKafkaSimulator("order-status", partitions=3)
        '''),
        code(r'''
        rng = random.Random(41)
        start = datetime(2026, 1, 5, tzinfo=timezone.utc)
        source_events = []
        for index in range(45):
            event_time = start + timedelta(seconds=index * 20)
            if index == 40:
                event_time = start + timedelta(minutes=1)  # late event arriving near the end
            event = {
                "event_id": f"status-{index:04d}",
                "order_id": f"ord_{rng.randint(1, 12):06d}",
                "status": rng.choice(["paid", "packed", "shipped"]),
                "event_time": event_time.isoformat(),
                "produced_at": datetime.now(timezone.utc).isoformat(),
            }
            source_events.append(event)

        # Produce every event and repeat two to simulate at-least-once publication.
        for event in source_events + [source_events[8], source_events[17]]:
            broker.produce(key=event["order_id"], value=event)

        partition_sizes = [len(log) for log in broker.logs]
        partition_sizes, sum(partition_sizes)
        '''),
        md(r'''
        ## Processing and commit are separate failure points

        The consumer writes records to an idempotent sink keyed by `event_id`. Imagine it
        crashes after the write but before `commit()`. The next poll returns those messages
        again. Correctness must not depend on exactly-once delivery from the network.
        '''),
        code(r'''
        GROUP_ID = "silver-order-status-v1"
        sink: dict[str, dict] = {}


        def write_idempotently(messages: list[Message]) -> dict:
            inserted = 0
            duplicates = 0
            for message in messages:
                event_id = message.value["event_id"]
                if event_id in sink:
                    duplicates += 1
                else:
                    sink[event_id] = {
                        **message.value,
                        "kafka_partition": message.partition,
                        "kafka_offset": message.offset,
                    }
                    inserted += 1
            return {"inserted": inserted, "duplicates": duplicates}


        first_batch = broker.poll(GROUP_ID, max_records=12)
        first_write = write_idempotently(first_batch)
        # Deliberate crash: do not commit.
        replayed_batch = broker.poll(GROUP_ID, max_records=12)
        replay_write = write_idempotently(replayed_batch)
        broker.commit(GROUP_ID, replayed_batch)

        assert [m.offset for m in first_batch] == [m.offset for m in replayed_batch]
        assert replay_write["inserted"] == 0
        first_write, replay_write, len(sink)
        '''),
        code(r'''
        # Drain and commit the remaining topic.
        while True:
            batch = broker.poll(GROUP_ID, max_records=10)
            if not batch:
                break
            write_idempotently(batch)
            broker.commit(GROUP_ID, batch)

        assert len(sink) == len({event["event_id"] for event in source_events})

        # Full replay: offsets go back to zero; the sink stays correct.
        count_before_replay = len(sink)
        broker.reset_group(GROUP_ID)
        replay_duplicates = 0
        while True:
            batch = broker.poll(GROUP_ID, max_records=25)
            if not batch:
                break
            replay_duplicates += write_idempotently(batch)["duplicates"]
            broker.commit(GROUP_ID, batch)

        assert len(sink) == count_before_replay
        print({"unique_sink_rows": len(sink), "duplicates_observed_during_replay": replay_duplicates})
        '''),
        md(r'''
        ## Event time and late data

        Processing time tells us when the consumer saw an event. Event time tells us when
        the business action happened. A watermark allows bounded waiting for late data and
        limits state. Events later than the allowed lateness need an explicit policy:
        update a prior window, route to a late-data table, or reject with monitoring.
        '''),
        code(r'''
        allowed_lateness = timedelta(minutes=3)
        # Use producer arrival order. Iterating partition logs would group records by
        # partition and would not reconstruct the original cross-partition arrival order.
        arrival_order = source_events
        max_event_time = None
        late_events = []
        for event in arrival_order:
            event_time = datetime.fromisoformat(event["event_time"])
            if max_event_time is not None and event_time < max_event_time - allowed_lateness:
                late_events.append(event)
            max_event_time = max(filter(None, [max_event_time, event_time]))

        print("Late events beyond watermark:", len(late_events))
        assert len(late_events) == 1
        late_events[:2]
        '''),
        md(r'''
        ## Optional: run against real Apache Kafka

        From the project directory:

        ```bash
        docker compose -f docker-compose.kafka.yml up -d
        python -m pip install -r requirements-kafka.txt
        ```

        Set `RUN_REAL_KAFKA = True` below. The code creates a three-partition topic,
        publishes the same events with `order_id` keys, and consumes with manual commit.
        Stop the broker later with:

        ```bash
        docker compose -f docker-compose.kafka.yml down
        ```
        '''),
        code(r'''
        RUN_REAL_KAFKA = False

        if RUN_REAL_KAFKA:
            from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
            from kafka.admin import NewTopic
            from kafka.errors import TopicAlreadyExistsError

            bootstrap = "localhost:9092"
            topic = "order-status"
            admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="capstone-admin")
            try:
                admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)])
            except TopicAlreadyExistsError:
                pass
            finally:
                admin.close()

            producer = KafkaProducer(
                bootstrap_servers=bootstrap,
                key_serializer=lambda value: value.encode("utf-8"),
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
                acks="all",
                retries=3,
            )
            futures = [producer.send(topic, key=e["order_id"], value=e) for e in source_events]
            for future in futures:
                metadata = future.get(timeout=10)
                print(metadata.topic, metadata.partition, metadata.offset)
            producer.flush()
            producer.close()

            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=bootstrap,
                group_id="notebook-real-consumer-v1",
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=lambda value: json.loads(value.decode("utf-8")),
                consumer_timeout_ms=5000,
            )
            real_sink = {}
            for message in consumer:
                real_sink[message.value["event_id"]] = {
                    **message.value,
                    "kafka_partition": message.partition,
                    "kafka_offset": message.offset,
                }
            consumer.commit()
            consumer.close()
            print(f"Real Kafka sink rows: {len(real_sink)}")
        else:
            print("Simulation mode complete. Set RUN_REAL_KAFKA=True after starting Docker.")
        '''),
        md(r'''
        ## Production boundaries

        - A Kafka partition is an ordered log, but order is guaranteed only within that
          partition.
        - Consumer-group members divide partitions; adding consumers beyond the partition
          count does not increase parallelism for that topic.
        - Commit after durable output. A crash before commit causes replay; a commit before
          output can lose data.
        - Idempotency can use a unique event key, database `MERGE`, transactional sink, or
          another deduplication state strategy.
        - Exactly-once claims must name their boundary. End-to-end behavior includes the
          source, broker, processor, and sink.

        ## Your turn

        1. Commit before writing, inject a crash, and show the lost record.
        2. Use `customer_id` instead of `order_id` as the key and discuss ordering impact.
        3. Start a second real consumer in the same group and inspect partition assignment.
        4. Reset offsets and prove the real sink remains idempotent.
        5. Design a dead-letter topic for records that fail schema validation.

        ### Final interview story

        Connect the entire capstone: resilient API extraction, immutable Bronze data,
        Spark validation and partitioned Silver output, ordered CDC, dimensional warehouse
        models, Airflow recovery, and Kafka replay. State clearly which optional managed
        services you actually used.
        '''),
    ]


if __name__ == "__main__":
    write_notebook("01_api_ingestion_and_reliability.ipynb", notebook_01())
    write_notebook("02_pyspark_lakehouse_and_cdc.ipynb", notebook_02())
    write_notebook("03_spark_performance_and_cost.ipynb", notebook_03())
    write_notebook("04_warehouse_elt_and_modeling.ipynb", notebook_04())
    write_notebook("05_kafka_streaming_and_offsets.ipynb", notebook_05())
    print(f"Generated 5 notebooks in {NOTEBOOKS}")
