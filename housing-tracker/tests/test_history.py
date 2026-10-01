from copy import deepcopy
import gzip
import json
import sqlite3

import pytest

from tests.scenarios import snapshots
from tracker.metrics import canonical_runs, daily_metrics, filter_rows, joined, property_history
from tracker.probe import detail_year
from tracker.storage import backup, export_snapshot, import_snapshot, read_frames


@pytest.fixture
def sample():
    return next(snapshots())


def test_reimport_is_idempotent_and_payload_can_be_restored(tmp_path, sample):
    db = tmp_path / "history.sqlite3"
    run_id, inserted = import_snapshot(db, sample)
    assert inserted
    assert import_snapshot(db, sample) == (run_id, False)
    assert export_snapshot(db, run_id) == sample
    copy = tmp_path / "backup.sqlite3"
    assert len(backup(db, copy)) == 64
    assert export_snapshot(copy, run_id) == sample
    runs, rows = read_frames(copy, "observed")
    assert len(runs) == 1 and len(rows) == len(sample["listings"])
    replay = tmp_path / "replay.sqlite3"
    assert import_snapshot(replay, export_snapshot(copy, run_id)) == (run_id, True)
    assert len(read_frames(replay, "observed")[1]) == len(rows)
    with pytest.raises(ValueError, match="new backup"):
        backup(db, copy)


def test_invalid_batch_does_not_modify_database(tmp_path, sample):
    db = tmp_path / "history.sqlite3"
    import_snapshot(db, sample)
    invalid = deepcopy(sample)
    invalid["observed_at"] = "2026-09-01T10:17:00+00:00"
    invalid["listings"][1]["property_id"] = invalid["listings"][0]["property_id"]
    with pytest.raises(ValueError, match="duplicate"):
        import_snapshot(db, invalid)
    assert len(read_frames(db, "observed")[0]) == 1


@pytest.mark.parametrize("missing", ["all_pages", "all_prices", "official_zone_verified", "query_validated"])
def test_incomplete_claim_cannot_publish(tmp_path, sample, missing):
    sample["coverage"][missing] = False
    with pytest.raises(ValueError, match="verification"):
        import_snapshot(tmp_path / "x.sqlite3", sample)


def test_source_total_must_reconcile(tmp_path, sample):
    sample["expected_unique_count"] += 1
    with pytest.raises(ValueError, match="reconcile"):
        import_snapshot(tmp_path / "x.sqlite3", sample)


def test_market_day_is_eastern_and_conflicting_import_rejected(tmp_path, sample):
    db = tmp_path / "x.sqlite3"
    sample["observed_at"] = "2026-09-02T01:00:00Z"
    import_snapshot(db, sample)
    assert read_frames(db, "observed")[0].iloc[0].market_date == "2026-09-01"
    sample["note"] = "Different content at the exact same time"
    with pytest.raises(ValueError, match="Conflicting"):
        import_snapshot(db, sample)


def test_gap_is_not_zero_and_failed_retry_does_not_replace_complete(tmp_path, sample):
    db = tmp_path / "x.sqlite3"
    import_snapshot(db, sample)
    failed = deepcopy(sample)
    failed.update(observed_at="2026-08-31T22:00:00Z", quality="failed", listings=[])
    import_snapshot(db, failed)
    failed["observed_at"] = "2026-09-01T10:00:00Z"
    import_snapshot(db, failed)
    runs, rows = read_frames(db, "observed")
    assert len(canonical_runs(runs)) == 1
    metrics = daily_metrics(runs, rows, ["north_gwinnett"], "2026-08-31", "2026-09-02", price=None)
    assert metrics.iloc[0].active > 0
    assert metrics.iloc[1:].active.isna().all()
    assert not metrics.iloc[1:].complete.any()
    history = property_history(runs, rows, sample["listings"][0]["property_id"], "north_gwinnett")
    assert history.iloc[0].availability == "관측됨"


def test_price_band_uses_historical_price(tmp_path, sample):
    db = tmp_path / "x.sqlite3"
    pid = sample["listings"][0]["property_id"]
    import_snapshot(db, sample)
    later = deepcopy(sample)
    later["observed_at"] = "2026-09-01T10:17:00Z"
    later["listings"][0]["price"] = 690000
    import_snapshot(db, later)
    runs, rows = read_frames(db, "observed")
    filtered = filter_rows(joined(runs, rows))
    assert filtered[filtered.property_id == pid].market_date.tolist() == ["2026-09-01"]


def test_disappearance_never_becomes_sold(tmp_path, sample):
    db = tmp_path / "x.sqlite3"
    pid = sample["listings"][0]["property_id"]
    import_snapshot(db, sample)
    later = deepcopy(sample)
    later.update(observed_at="2026-09-01T10:17:00Z", listings=sample["listings"][1:])
    later["expected_unique_count"] -= 1
    import_snapshot(db, later)
    runs, rows = read_frames(db, "observed")
    history = property_history(runs, rows, pid, "north_gwinnett")
    assert "미관측" in history.iloc[-1].availability
    assert history.iloc[-1].status != "sold"


def test_past_sale_amount_cannot_be_attached_to_active_listing(tmp_path, sample):
    sample["listings"][0].update(sold_price=400000, sold_date="2000-01-01")
    with pytest.raises(ValueError, match="sold_price"):
        import_snapshot(tmp_path / "x.sqlite3", sample)


@pytest.mark.parametrize("nested", [False, True])
def test_both_year_built_variants_match_requested_property(nested):
    prop = {"zpid": "123", **({"resoFacts": {"yearBuilt": 1998}} if nested else {"yearBuilt": 1998})}
    data = {"props": {"pageProps": {"componentProps": {"gdpClientCache": json.dumps({"query": {"property": prop}})}}}}
    html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script>'
    assert detail_year(html, "123")[0] == 1998
    assert detail_year(html, "456")[0] is None


def test_corrupted_stored_payload_detected(tmp_path, sample):
    db = tmp_path / "x.sqlite3"
    run_id, _ = import_snapshot(db, sample)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET raw_gzip=?", (gzip.compress(b"{}"),))
    with pytest.raises(ValueError, match="checksum"):
        export_snapshot(db, run_id)
