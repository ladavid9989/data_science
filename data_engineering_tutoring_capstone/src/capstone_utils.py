"""Small, testable helpers shared by the educational notebooks.

The notebooks intentionally show the concepts first. These helpers demonstrate
how production code can be moved out of a notebook and covered by unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json
import logging
import os
import tempfile

import pandas as pd


class JsonLogFormatter(logging.Formatter):
    """Render one valid JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("run_id", "step", "record_count", "source", "attempt"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logger(name: str = "capstone", level: int = logging.INFO) -> logging.Logger:
    """Return a logger with exactly one JSON console handler."""

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    return logger


def file_sha256(path: Path) -> str:
    """Calculate a file checksum without loading the full file into memory."""

    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically so readers never observe a partial checkpoint."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as destination:
            json.dump(payload, destination, indent=2, default=str)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def flatten_order(order: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize one nested order into an order row and zero or more item rows."""

    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    customer_id = order.get("customer_id") or customer.get("id")
    order_row = {
        "order_id": order.get("order_id"),
        "customer_id": customer_id,
        "event_type": order.get("event_type", "order_created"),
        "event_timestamp": order.get("event_timestamp"),
        "updated_at": order.get("updated_at"),
        "status": order.get("status"),
        "currency": order.get("currency"),
        "total_amount": pd.to_numeric(order.get("total_amount"), errors="coerce"),
        "schema_version": order.get("schema_version", 1),
    }
    item_rows = []
    for position, item in enumerate(order.get("items") or [], start=1):
        if not isinstance(item, dict):
            continue
        item_rows.append(
            {
                "order_id": order.get("order_id"),
                "line_number": position,
                "sku": item.get("sku"),
                "quantity": pd.to_numeric(item.get("quantity"), errors="coerce"),
                "unit_price": pd.to_numeric(item.get("unit_price"), errors="coerce"),
            }
        )
    return order_row, item_rows


def apply_cdc_snapshot(current: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    """Apply ordered I/U/D changes to a current-state Pandas snapshot.

    This reference implementation is deliberately small. Notebook 02 translates
    the same rules into Spark and discusses how Delta Lake MERGE implements them.
    """

    required = {"order_id", "op", "sequence_no"}
    missing = required.difference(changes.columns)
    if missing:
        raise ValueError(f"CDC input is missing columns: {sorted(missing)}")

    base = current.copy()
    if base.empty:
        base = pd.DataFrame(columns=["order_id"])
    base = base.drop_duplicates("order_id", keep="last").set_index("order_id", drop=False)

    ordered = changes.sort_values(["sequence_no", "order_id"], kind="stable")
    ordered = ordered.drop_duplicates("order_id", keep="last")
    for record in ordered.to_dict("records"):
        order_id = record["order_id"]
        if record["op"] == "D":
            base = base.drop(index=order_id, errors="ignore")
            continue
        values = {key: value for key, value in record.items() if key not in {"op", "sequence_no"}}
        values["order_id"] = order_id
        for column in values:
            if column not in base.columns:
                base[column] = pd.NA
        base.loc[order_id, list(values)] = list(values.values())

    return base.reset_index(drop=True).sort_values("order_id").reset_index(drop=True)


def quality_summary(
    valid_count: int,
    quarantined_count: int,
    duplicate_count: int,
) -> dict[str, float | int]:
    """Create reconciled pipeline quality metrics."""

    total = valid_count + quarantined_count + duplicate_count
    return {
        "input_count": total,
        "valid_count": valid_count,
        "quarantined_count": quarantined_count,
        "duplicate_count": duplicate_count,
        "quarantine_rate": quarantined_count / total if total else 0.0,
    }


def estimate_scan_cost(bytes_scanned: int, price_per_tb: float = 5.0) -> float:
    """Return a teaching estimate; callers must supply the current vendor price."""

    if bytes_scanned < 0 or price_per_tb < 0:
        raise ValueError("Inputs must be non-negative")
    tebibyte = 1024**4
    return bytes_scanned / tebibyte * price_per_tb


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    """Write iterable records as JSON Lines and return the row count."""

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as destination:
        for record in records:
            destination.write(json.dumps(record, default=str) + "\n")
            count += 1
    return count

