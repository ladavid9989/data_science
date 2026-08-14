from datetime import datetime, timezone

from src.freshness import classify_freshness, format_freshness, normalize_posted_date, source_date_quality


NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)


def test_epoch_milliseconds_normalize_to_iso_date() -> None:
    assert normalize_posted_date("1751328000000") == "2025-07-01"


def test_freshness_classifies_fresh_recent_aging_and_stale() -> None:
    assert classify_freshness("2026-06-30", now=NOW).category == "fresh"
    assert classify_freshness("2026-06-15", now=NOW).category == "recent"
    assert classify_freshness("2026-05-25", now=NOW).category == "aging"
    assert classify_freshness("2026-04-01", now=NOW).category == "stale"


def test_unknown_date_recently_seen_is_not_stale() -> None:
    freshness = classify_freshness("", first_seen_at="2026-07-01T12:00:00+00:00", now=NOW)
    assert freshness.category == "unknown_recently_seen"
    assert freshness.is_unknown
    assert not freshness.is_stale
    assert format_freshness(freshness) == "Unknown, first seen 1d ago, source: local first_seen fallback"


def test_freshness_format_includes_source_provenance() -> None:
    freshness = classify_freshness(
        "2026-06-17",
        now=NOW,
        posted_date_source="Greenhouse updated_at",
    )
    assert format_freshness(freshness) == "2026-06-17, Recent (15d old), source: Greenhouse updated_at"


def test_source_date_quality_counts_missing_posted_dates() -> None:
    quality = source_date_quality(
        [
            {"source": "A", "posted_date": "2026-07-01"},
            {"source": "A", "posted_date": ""},
            {"source": "B", "posted_date": ""},
        ]
    )
    assert quality["A"]["posted_date_rate"] == 0.5
    assert quality["B"]["posted_date_rate"] == 0
