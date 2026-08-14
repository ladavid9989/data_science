from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.freshness import classify_freshness, format_freshness, source_date_quality
from src.utils import ensure_parent_dir


def generate_report(
    ranked_jobs: list[dict[str, Any]],
    report_path: str | Path,
    reporting_config: dict[str, Any] | None = None,
) -> str:
    reporting_config = reporting_config or {}
    min_score = int(reporting_config.get("min_score_to_show", 0))
    max_jobs = int(reporting_config.get("max_jobs_to_show", len(ranked_jobs) or 0))
    strict_location_gate = bool(reporting_config.get("strict_location_gate", False))
    hide_stale_jobs = bool(reporting_config.get("hide_stale_jobs", False))
    eligible_jobs = [
        job
        for job in ranked_jobs
        if int(job.get("score") or 0) >= min_score
        and (not strict_location_gate or _passes_location_gate(job, reporting_config))
        and (not hide_stale_jobs or _passes_freshness_gate(job, reporting_config))
    ]
    visible_jobs = eligible_jobs[:max_jobs]
    hidden_by_location_gate = sum(
        1
        for job in ranked_jobs
        if int(job.get("score") or 0) >= min_score
        and strict_location_gate
        and not _passes_location_gate(job, reporting_config)
    )
    hidden_by_freshness_gate = sum(
        1
        for job in ranked_jobs
        if int(job.get("score") or 0) >= min_score
        and (not strict_location_gate or _passes_location_gate(job, reporting_config))
        and hide_stale_jobs
        and not _passes_freshness_gate(job, reporting_config)
    )
    ensure_parent_dir(report_path)
    lines = [
        "# Ranked Job Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Total jobs processed: {len(ranked_jobs)}",
        f"Jobs shown: {len(visible_jobs)}",
        f"Minimum score shown: {min_score}",
        f"Strict location gate: {'enabled' if strict_location_gate else 'disabled'}",
        f"Jobs hidden by location gate: {hidden_by_location_gate}",
        f"Stale freshness gate: {'enabled' if hide_stale_jobs else 'disabled'}",
        f"Jobs hidden by freshness gate: {hidden_by_freshness_gate}",
        "",
    ]
    if not visible_jobs:
        lines.extend(["No scored jobs found.", ""])
    for index, job in enumerate(visible_jobs, start=1):
        lines.extend(
            [
                f"## {index}. {job.get('title', 'Untitled job')}",
                "",
                f"- Company: {job.get('company') or 'Unknown'}",
                f"- Location: {job.get('location') or 'Unknown'}",
                f"- Posted: {_freshness_line(job, reporting_config)}",
                f"- Score: {job.get('score')}",
                f"- Matched skills: {_join(job.get('matched_skills', []))}",
                f"- Missing skills: {_join(job.get('missing_skills', []))}",
                f"- Positive reasons: {_join(job.get('positive_reasons', []))}",
                f"- Negative reasons: {_join(job.get('negative_reasons', []))}",
                f"- Job URL: {job.get('job_url') or 'Unavailable'}",
                "",
            ]
        )
    lines.extend(
        _source_summary_lines(
            ranked_jobs,
            min_score,
            reporting_config,
            strict_location_gate,
            hide_stale_jobs,
        )
    )
    content = "\n".join(lines)
    Path(report_path).write_text(content, encoding="utf-8")
    return str(report_path)


def _join(values: list[str]) -> str:
    return ", ".join(values) if values else "None"


def _passes_location_gate(job: dict[str, Any], reporting_config: dict[str, Any]) -> bool:
    location = _normalize_location(str(job.get("location") or ""))
    reasons = _normalize_location(" ".join(_coerce_list(job.get("positive_reasons", []))))
    score = int(job.get("score") or 0)

    if _is_georgia_location(location) or "georgia preferred location" in reasons:
        return True
    if _is_explicit_remote_us(location) or "remote us location" in reasons:
        return True
    if _is_non_us_or_remote_north_america(location):
        return False
    if _is_broad_us_only(location):
        return score >= int(reporting_config.get("broad_us_min_score_to_show", 95))
    return False


def _passes_freshness_gate(job: dict[str, Any], reporting_config: dict[str, Any]) -> bool:
    freshness = classify_freshness(
        job.get("posted_date"),
        job.get("first_seen_at"),
        posted_date_source=str(job.get("posted_date_source") or ""),
        config=reporting_config.get("freshness", {}),
    )
    return not freshness.is_stale


def _freshness_line(job: dict[str, Any], reporting_config: dict[str, Any]) -> str:
    freshness = classify_freshness(
        job.get("posted_date"),
        job.get("first_seen_at"),
        posted_date_source=str(job.get("posted_date_source") or ""),
        config=reporting_config.get("freshness", {}),
    )
    return format_freshness(freshness)


def _normalize_location(value: str) -> str:
    import re

    normalized = re.sub(r"[^a-z0-9\s+-]", " ", value.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _is_georgia_location(location: str) -> bool:
    import re

    return (
        "atlanta" in location
        or "alpharetta" in location
        or "georgia" in location
        or bool(re.search(r"\bga\b", location))
    )


def _is_explicit_remote_us(location: str) -> bool:
    import re

    remote = "remote" in location
    explicit_us = (
        bool(re.search(r"\bus\b", location))
        or "usa" in location
        or "u s" in location
        or "united states" in location
    )
    return remote and explicit_us


def _is_broad_us_only(location: str) -> bool:
    import re

    has_broad_us = (
        "united states" in location
        or "usa" in location
        or bool(re.search(r"\bus\b", location))
    )
    return has_broad_us and not _is_explicit_remote_us(location) and not _is_georgia_location(location)


def _is_non_us_or_remote_north_america(location: str) -> bool:
    negative_terms = [
        "remote north america",
        "north america",
        "toronto",
        "canada",
        "europe",
        "united kingdom",
        "uk",
        "london",
        "amsterdam",
        "germany",
        "france",
        "netherlands",
        "ireland",
        "india",
        "argentina",
        "colombia",
        "brazil",
        "singapore",
        "australia",
        "mexico",
    ]
    return any(term in location for term in negative_terms)


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


def _source_summary_lines(
    ranked_jobs: list[dict[str, Any]],
    min_score: int,
    reporting_config: dict[str, Any],
    strict_location_gate: bool,
    hide_stale_jobs: bool,
) -> list[str]:
    lines = ["## Source Summary", ""]
    if not ranked_jobs:
        return lines + ["No source data available.", ""]

    date_quality = source_date_quality(ranked_jobs)
    summaries: dict[str, dict[str, float]] = {}
    for job in ranked_jobs:
        source = str(job.get("source") or "Unknown")
        score = int(job.get("score") or 0)
        summary = summaries.setdefault(
            source,
            {
                "count": 0,
                "score_total": 0,
                "above_threshold": 0,
                "shown_after_gate": 0,
                "stale": 0,
                "unknown_date": 0,
            },
        )
        summary["count"] += 1
        summary["score_total"] += score
        freshness = classify_freshness(
            job.get("posted_date"),
            job.get("first_seen_at"),
            posted_date_source=str(job.get("posted_date_source") or ""),
            config=reporting_config.get("freshness", {}),
        )
        if freshness.is_stale:
            summary["stale"] += 1
        if freshness.is_unknown:
            summary["unknown_date"] += 1
        if score >= min_score:
            summary["above_threshold"] += 1
            if (
                (not strict_location_gate or _passes_location_gate(job, reporting_config))
                and (not hide_stale_jobs or _passes_freshness_gate(job, reporting_config))
            ):
                summary["shown_after_gate"] += 1

    lines.extend(
        [
            "| Source | Jobs collected | Average score | Posted date coverage | Stale | Unknown date | Above threshold | Shown after gate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for source, summary in sorted(summaries.items()):
        count = int(summary["count"])
        average = summary["score_total"] / count if count else 0
        posted_date_rate = float(date_quality.get(source, {}).get("posted_date_rate", 0)) * 100
        lines.append(
            f"| {source} | {count} | {average:.1f} | {posted_date_rate:.0f}% | "
            f"{int(summary['stale'])} | {int(summary['unknown_date'])} | {int(summary['above_threshold'])} | "
            f"{int(summary['shown_after_gate'])} |"
        )
    lines.append("")
    return lines
