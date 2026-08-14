from __future__ import annotations

import re
from typing import Any

POSITIVE_ACTIONS = {"like", "save", "applied"}
NEGATIVE_ACTIONS = {"dislike", "hide"}
DIRECT_ACTION_WEIGHTS = {
    "like": 6,
    "save": 8,
    "applied": 12,
    "dislike": -12,
    "hide": -100,
}
SIMILAR_ACTION_WEIGHTS = {
    "like": 4,
    "save": 5,
    "applied": 7,
    "dislike": -6,
    "hide": -4,
}


def apply_feedback_adjustments(
    jobs: list[dict[str, Any]],
    feedback_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for job in jobs:
        copied = dict(job)
        base_score = int(copied.get("score") or 0)
        adjustment, reasons = _feedback_adjustment_for_job(copied, feedback_events)
        copied["base_score"] = base_score
        copied["feedback_adjustment"] = adjustment
        copied["feedback_reasons"] = reasons
        copied["score"] = max(0, min(100, base_score + adjustment))
        adjusted.append(copied)
    return sorted(adjusted, key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or "")))


def _feedback_adjustment_for_job(
    job: dict[str, Any],
    feedback_events: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    raw_adjustment = 0
    reasons: list[str] = []
    job_id = int(job.get("id") or 0)

    for event in feedback_events:
        action = str(event.get("action") or "")
        if action not in DIRECT_ACTION_WEIGHTS:
            continue

        if int(event.get("job_id") or 0) == job_id:
            if action == "hide":
                return -100, ["Direct feedback hide: -100"]
            direct = DIRECT_ACTION_WEIGHTS[action]
            raw_adjustment += direct
            reasons.append(f"Direct feedback {action}: {direct:+d}")
            continue

        similarity = _similarity_score(job, event)
        if similarity <= 0:
            continue
        weight = SIMILAR_ACTION_WEIGHTS[action]
        similar_adjustment = round(weight * min(1.0, similarity / 10))
        if similar_adjustment:
            raw_adjustment += similar_adjustment
            reasons.append(f"Similar to {action} feedback: {similar_adjustment:+d}")

        note_adjustment = _notes_adjustment(job, event)
        if note_adjustment:
            raw_adjustment += note_adjustment
            reasons.append(f"Matched feedback note pattern: {note_adjustment:+d}")

    capped = max(-35, min(20, raw_adjustment))
    if capped != raw_adjustment:
        reasons.append(f"Feedback adjustment capped at {capped:+d}")
    return capped, reasons[:6]


def _similarity_score(job: dict[str, Any], event: dict[str, Any]) -> int:
    score = 0
    if _norm(job.get("source")) and _norm(job.get("source")) == _norm(event.get("source")):
        score += 3
    if _location_category(job.get("location")) == _location_category(event.get("location")):
        score += 2
    overlap = _title_terms(job.get("title")) & _title_terms(event.get("title"))
    score += min(5, len(overlap) * 2)
    return score


def _notes_adjustment(job: dict[str, Any], event: dict[str, Any]) -> int:
    action = str(event.get("action") or "")
    notes = _note_terms(event.get("notes"))
    if not notes:
        return 0
    searchable = _norm(
        " ".join(
            str(job.get(key) or "")
            for key in ("title", "company", "location", "description_text")
        )
    )
    matches = [term for term in notes if term in searchable]
    if not matches:
        return 0
    if action in NEGATIVE_ACTIONS:
        return -min(8, len(matches) * 2)
    if action in POSITIVE_ACTIONS:
        return min(5, len(matches))
    return 0


def _title_terms(value: Any) -> set[str]:
    terms = {
        "analyst",
        "analytics",
        "bi",
        "business",
        "data",
        "engineer",
        "intelligence",
        "learning",
        "machine",
        "risk",
        "scientist",
        "senior",
        "staff",
    }
    tokens = set(_norm(value).split())
    return tokens & terms


def _note_terms(value: Any) -> list[str]:
    text = _norm(value)
    if not text:
        return []
    stop_words = {
        "and",
        "are",
        "because",
        "but",
        "for",
        "from",
        "job",
        "not",
        "role",
        "that",
        "the",
        "this",
        "too",
        "with",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]{4,}", text)
        if token not in stop_words
    ][:12]


def _location_category(value: Any) -> str:
    text = _norm(value)
    if "atlanta" in text or "alpharetta" in text or "georgia" in text or re.search(r"\bga\b", text):
        return "georgia"
    if "remote" in text and ("usa" in text or "united states" in text or re.search(r"\bus\b", text)):
        return "remote_us"
    if "remote" in text:
        return "remote_other"
    if "united states" in text or "usa" in text or re.search(r"\bus\b", text):
        return "broad_us"
    return text[:40]


def _norm(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9\s+-]", " ", str(value or "").casefold())
    return re.sub(r"\s+", " ", normalized).strip()
