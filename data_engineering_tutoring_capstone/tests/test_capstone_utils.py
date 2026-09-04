import json
import logging

import pandas as pd
import pytest

from src.capstone_utils import (
    JsonLogFormatter,
    apply_cdc_snapshot,
    estimate_scan_cost,
    flatten_order,
    quality_summary,
)


def test_flatten_order_supports_schema_v1_and_nested_items():
    order = {
        "order_id": "o-1",
        "customer_id": "c-1",
        "total_amount": "12.50",
        "items": [{"sku": "A", "quantity": 2, "unit_price": 6.25}],
    }
    order_row, item_rows = flatten_order(order)
    assert order_row["customer_id"] == "c-1"
    assert order_row["total_amount"] == pytest.approx(12.5)
    assert item_rows == [
        {"order_id": "o-1", "line_number": 1, "sku": "A", "quantity": 2, "unit_price": 6.25}
    ]


def test_flatten_order_accepts_schema_v2_customer_object():
    order_row, _ = flatten_order({"order_id": "o-2", "customer": {"id": "c-2"}})
    assert order_row["customer_id"] == "c-2"


def test_cdc_keeps_latest_sequence_and_applies_delete():
    current = pd.DataFrame([{"order_id": "o-1", "status": "pending"}, {"order_id": "o-2", "status": "paid"}])
    changes = pd.DataFrame(
        [
            {"order_id": "o-1", "op": "U", "sequence_no": 11, "status": "shipped"},
            {"order_id": "o-1", "op": "U", "sequence_no": 10, "status": "paid"},
            {"order_id": "o-2", "op": "D", "sequence_no": 12, "status": None},
        ]
    )
    result = apply_cdc_snapshot(current, changes)
    assert result[["order_id", "status"]].to_dict("records") == [{"order_id": "o-1", "status": "shipped"}]


def test_cdc_is_idempotent():
    current = pd.DataFrame([{"order_id": "o-1", "status": "pending"}])
    changes = pd.DataFrame([{"order_id": "o-1", "op": "U", "sequence_no": 1, "status": "paid"}])
    once = apply_cdc_snapshot(current, changes)
    twice = apply_cdc_snapshot(once, changes)
    pd.testing.assert_frame_equal(once, twice)


def test_quality_summary_reconciles_counts():
    metrics = quality_summary(90, 7, 3)
    assert metrics["input_count"] == 100
    assert metrics["quarantine_rate"] == pytest.approx(0.07)


def test_scan_cost_rejects_negative_values():
    with pytest.raises(ValueError):
        estimate_scan_cost(-1)


def test_json_log_formatter_emits_valid_json():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "loaded", (), None)
    record.run_id = "run-1"
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "loaded"
    assert payload["run_id"] == "run-1"

