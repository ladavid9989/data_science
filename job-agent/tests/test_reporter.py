from pathlib import Path

from src.reporter import generate_report


REPORTING_CONFIG = {
    "min_score_to_show": 60,
    "max_jobs_to_show": 50,
    "strict_location_gate": True,
    "broad_us_min_score_to_show": 95,
}


def test_report_location_gate_keeps_georgia_and_remote_us(tmp_path: Path) -> None:
    report_path = tmp_path / "ranked_jobs.md"
    generate_report(
        [
            _job("Atlanta Data Scientist", "Atlanta, GA", 80),
            _job("Remote US Data Scientist", "Remote - USA", 80),
        ],
        report_path,
        REPORTING_CONFIG,
    )
    report = report_path.read_text(encoding="utf-8")
    assert "Atlanta Data Scientist" in report
    assert "Remote US Data Scientist" in report
    assert "Jobs shown: 2" in report


def test_report_location_gate_hides_broad_us_below_exceptional_score(tmp_path: Path) -> None:
    report_path = tmp_path / "ranked_jobs.md"
    generate_report(
        [_job("Broad US Data Engineer", "United States", 91)],
        report_path,
        REPORTING_CONFIG,
    )
    report = report_path.read_text(encoding="utf-8")
    assert "Broad US Data Engineer" not in report
    assert "Jobs shown: 0" in report
    assert "Jobs hidden by location gate: 1" in report


def test_report_location_gate_allows_exceptional_broad_us_score(tmp_path: Path) -> None:
    report_path = tmp_path / "ranked_jobs.md"
    generate_report(
        [_job("Exceptional Broad US Data Engineer", "United States", 96)],
        report_path,
        REPORTING_CONFIG,
    )
    report = report_path.read_text(encoding="utf-8")
    assert "Exceptional Broad US Data Engineer" in report


def test_report_location_gate_hides_remote_north_america_and_toronto(tmp_path: Path) -> None:
    report_path = tmp_path / "ranked_jobs.md"
    generate_report(
        [
            _job("North America Data Scientist", "Remote, North America", 93),
            _job("Toronto Data Scientist", "Toronto", 85),
        ],
        report_path,
        REPORTING_CONFIG,
    )
    report = report_path.read_text(encoding="utf-8")
    assert "North America Data Scientist" not in report
    assert "Toronto Data Scientist" not in report
    assert "Jobs shown: 0" in report
    assert "Jobs hidden by location gate: 2" in report


def test_report_hides_stale_jobs_when_freshness_gate_is_enabled(tmp_path: Path) -> None:
    report_path = tmp_path / "ranked_jobs.md"
    config = {**REPORTING_CONFIG, "hide_stale_jobs": True}
    generate_report(
        [
            _job("Fresh Atlanta Data Scientist", "Atlanta, GA", 80, posted_date="2026-07-01"),
            _job("Stale Atlanta Data Scientist", "Atlanta, GA", 80, posted_date="2026-04-01"),
        ],
        report_path,
        config,
    )
    report = report_path.read_text(encoding="utf-8")
    assert "Fresh Atlanta Data Scientist" in report
    assert "Stale Atlanta Data Scientist" not in report
    assert "Jobs hidden by freshness gate: 1" in report


def test_report_keeps_unknown_recently_seen_jobs(tmp_path: Path) -> None:
    report_path = tmp_path / "ranked_jobs.md"
    config = {
        **REPORTING_CONFIG,
        "hide_stale_jobs": True,
        "freshness": {"first_seen_recent_days": 9999},
    }
    generate_report(
        [
            _job(
                "Unknown Date Atlanta Data Scientist",
                "Atlanta, GA",
                80,
                posted_date="",
                first_seen_at="2026-07-01T12:00:00+00:00",
            ),
        ],
        report_path,
        config,
    )
    report = report_path.read_text(encoding="utf-8")
    assert "Unknown Date Atlanta Data Scientist" in report
    assert "Unknown, first seen" in report
    assert "source: local first_seen fallback" in report


def _job(
    title: str,
    location: str,
    score: int,
    posted_date: str = "",
    first_seen_at: str = "2026-07-02T12:00:00+00:00",
) -> dict[str, object]:
    return {
        "source": "test",
        "title": title,
        "company": "Example Co",
        "location": location,
        "score": score,
        "posted_date": posted_date,
        "first_seen_at": first_seen_at,
        "matched_skills": [],
        "missing_skills": [],
        "positive_reasons": [],
        "negative_reasons": [],
        "job_url": "https://example.com/job",
    }
