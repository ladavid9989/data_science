"""Educational Airflow DAG for metadata-driven orchestration.

The heavy transformation belongs in versioned Python/Spark jobs. Airflow moves
small metadata between tasks and coordinates retries, dates, and quality gates.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import os

from airflow.sdk import dag, task


CAPSTONE_ROOT = Path(os.environ.get("CAPSTONE_ROOT", Path(__file__).resolve().parents[1]))
BRONZE_API = CAPSTONE_ROOT / "lab_data" / "bronze" / "api" / "orders"
RUN_METRICS = CAPSTONE_ROOT / "lab_data" / "pipeline_metrics"


@dag(
    dag_id="commerce_daily_quality_pipeline",
    description="Validate immutable API pages and publish daily pipeline metrics",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=True,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(seconds=20)},
    tags=["education", "data-engineering", "quality"],
)
def commerce_daily_quality_pipeline():
    @task
    def discover_raw(data_interval_start=None, data_interval_end=None) -> dict:
        pages = sorted(BRONZE_API.glob("ingestion_date=*/run_id=*/page_*.json"))
        return {
            "page_paths": [str(path) for path in pages],
            "interval_start": str(data_interval_start),
            "interval_end": str(data_interval_end),
        }

    @task
    def validate_pages(discovery: dict) -> dict:
        record_count = 0
        ids: list[str] = []
        malformed_pages = 0
        for page_name in discovery["page_paths"]:
            try:
                envelope = json.loads(Path(page_name).read_text(encoding="utf-8"))
                records = envelope["data"]
                if not isinstance(records, list):
                    raise TypeError("data must be a list")
                record_count += len(records)
                ids.extend(str(record.get("order_id")) for record in records)
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                malformed_pages += 1
        return {
            **discovery,
            "record_count": record_count,
            "duplicate_count": len(ids) - len(set(ids)),
            "malformed_pages": malformed_pages,
        }

    @task
    def quality_gate(metrics: dict) -> dict:
        if not metrics["page_paths"]:
            raise ValueError("No Bronze API pages were discovered. Run notebook 01 first.")
        if metrics["malformed_pages"]:
            raise ValueError(f"Malformed raw pages: {metrics['malformed_pages']}")
        # Duplicates are expected at the raw boundary but must remain observable.
        metrics["quality_status"] = "PASS"
        return metrics

    @task
    def publish_metrics(metrics: dict, logical_date=None) -> str:
        RUN_METRICS.mkdir(parents=True, exist_ok=True)
        date_key = str(logical_date).replace(":", "-")
        output = RUN_METRICS / f"run_{date_key}.json"
        output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        return str(output)

    publish_metrics(quality_gate(validate_pages(discover_raw())))


commerce_daily_quality_pipeline()

