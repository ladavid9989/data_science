from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class FreshnessInfo:
    category: str
    label: str
    posted_date: str
    posted_date_source: str
    age_days: int | None
    first_seen_age_days: int | None
    is_stale: bool
    is_unknown: bool


def normalize_posted_date(value: Any) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return ""
    return parsed.date().isoformat()


def classify_freshness(
    posted_date: Any,
    first_seen_at: Any = "",
    *,
    posted_date_source: str = "",
    now: datetime | None = None,
    config: dict[str, Any] | None = None,
) -> FreshnessInfo:
    config = config or {}
    now_dt = _as_utc(now or datetime.now(timezone.utc))
    fresh_days = int(config.get("fresh_days", 7))
    recent_days = int(config.get("recent_days", 21))
    aging_days = int(config.get("aging_days", 45))
    first_seen_recent_days = int(config.get("first_seen_recent_days", 14))

    posted_dt = parse_datetime(posted_date)
    first_seen_dt = parse_datetime(first_seen_at)
    posted_age = _age_days(posted_dt, now_dt)
    first_seen_age = _age_days(first_seen_dt, now_dt)

    if posted_age is not None:
        if posted_age <= fresh_days:
            category = "fresh"
        elif posted_age <= recent_days:
            category = "recent"
        elif posted_age <= aging_days:
            category = "aging"
        else:
            category = "stale"
        return FreshnessInfo(
            category=category,
            label=_label(category, posted_age),
            posted_date=normalize_posted_date(posted_date),
            posted_date_source=posted_date_source or "source_posted_date",
            age_days=posted_age,
            first_seen_age_days=first_seen_age,
            is_stale=category == "stale",
            is_unknown=False,
        )

    if first_seen_age is not None and first_seen_age <= first_seen_recent_days:
        return FreshnessInfo(
            category="unknown_recently_seen",
            label=f"Unknown posted date; first seen {first_seen_age}d ago",
            posted_date="",
            posted_date_source="local first_seen fallback",
            age_days=None,
            first_seen_age_days=first_seen_age,
            is_stale=False,
            is_unknown=True,
        )

    return FreshnessInfo(
        category="unknown",
        label="Unknown posted date",
        posted_date="",
        posted_date_source="missing source posted date",
        age_days=None,
        first_seen_age_days=first_seen_age,
        is_stale=False,
        is_unknown=True,
    )


def format_freshness(info: FreshnessInfo) -> str:
    if info.posted_date:
        return f"{info.posted_date}, {info.label}, source: {info.posted_date_source}"
    if info.first_seen_age_days is not None:
        return f"Unknown, first seen {info.first_seen_age_days}d ago, source: {info.posted_date_source}"
    return f"Unknown, source: {info.posted_date_source}"


def source_date_quality(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for row in rows:
        source = str(row.get("source") or "Unknown")
        item = summary.setdefault(source, {"count": 0, "posted_date_count": 0})
        item["count"] += 1
        if parse_datetime(row.get("posted_date")):
            item["posted_date_count"] += 1
    for item in summary.values():
        count = item["count"] or 1
        item["posted_date_rate"] = item["posted_date_count"] / count
        item["missing_posted_date_rate"] = 1 - item["posted_date_rate"]
    return summary


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_epoch_number(int(text))
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return _as_utc(datetime.strptime(text, pattern).replace(tzinfo=timezone.utc))
        except ValueError:
            continue
    return None


def _parse_epoch_number(value: int) -> datetime | None:
    try:
        if value > 10_000_000_000:
            value = value // 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _age_days(value: datetime | None, now: datetime) -> int | None:
    if not value:
        return None
    return max(0, (now.date() - value.date()).days)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _label(category: str, age_days: int) -> str:
    if category == "fresh":
        return f"Fresh ({age_days}d old)"
    if category == "recent":
        return f"Recent ({age_days}d old)"
    if category == "aging":
        return f"Aging ({age_days}d old)"
    return f"Stale ({age_days}d old)"
