from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.normalizer import Job
from src.utils import text_contains


@dataclass(frozen=True)
class ScoreResult:
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    positive_reasons: list[str]
    negative_reasons: list[str]


def score_job(job: Job, profile: dict[str, Any]) -> ScoreResult:
    text = _combined_text(job)
    score = 0
    positive: list[str] = []
    negative: list[str] = []

    if _matches_any(job.title, profile.get("target_titles", [])):
        score += 22
        positive.append("Title matches target roles")
    elif _matches_any(text, profile.get("target_titles", [])):
        score += 10
        positive.append("Description mentions target role keywords")

    role_score = _score_role_type(job, profile)
    score += role_score.score_delta
    positive.extend(role_score.positive_reasons)
    negative.extend(role_score.negative_reasons)

    required = profile.get("required_skills", [])
    preferred = profile.get("preferred_skills", [])
    matched_required = _matched_terms(text, required)
    missing_required = [skill for skill in required if skill not in matched_required]
    matched_preferred = _matched_terms(text, preferred)

    if required:
        required_points = round(30 * len(matched_required) / len(required))
        score += required_points
        if matched_required:
            positive.append(f"Matched required skills: {', '.join(matched_required)}")
        if missing_required:
            negative.append(f"Missing required skills: {', '.join(missing_required)}")

    score += min(18, len(matched_preferred) * 3)
    if matched_preferred:
        positive.append(f"Matched preferred skills: {', '.join(matched_preferred)}")

    industries = _matched_terms(text, profile.get("industries", []))
    if industries:
        score += 10
        positive.append(f"Industry fit: {', '.join(industries)}")

    location_score = _score_location(job, profile)
    score += location_score.score_delta
    positive.extend(location_score.positive_reasons)
    negative.extend(location_score.negative_reasons)

    if _seniority_fit(job.title, text):
        score += 6
        positive.append("Seniority appears aligned")

    salary = _max_salary(job.compensation_text or text)
    minimum_salary = int(profile.get("minimum_salary") or 0)
    if salary and minimum_salary:
        if salary >= minimum_salary:
            score += 4
            positive.append(f"Compensation appears to meet minimum salary: ${salary:,}")
        else:
            score -= 12
            negative.append(f"Compensation appears below minimum salary: ${salary:,}")

    negative_matches = _matched_terms(text, profile.get("negative_keywords", []))
    if negative_matches:
        penalty = min(40, 15 * len(negative_matches))
        score -= penalty
        negative.append(f"Negative keywords found: {', '.join(negative_matches)}")

    has_georgia_preference = any("Georgia preferred location" in reason for reason in positive)
    has_remote_us_preference = any("Remote US location" in reason for reason in positive)
    has_management_penalty = any(
        "Management-track" in reason or "Product/program/project manager" in reason
        for reason in negative
    )
    if has_management_penalty:
        score = min(score, 55)
    if has_remote_us_preference and not has_georgia_preference:
        score = min(score, 95)

    score = max(0, min(100, score))
    return ScoreResult(
        score=score,
        matched_skills=matched_required + matched_preferred,
        missing_skills=missing_required,
        positive_reasons=positive,
        negative_reasons=negative,
    )


def _combined_text(job: Job) -> str:
    return " ".join(
        [job.title, job.company, job.location, job.remote_type, job.description_text, job.compensation_text]
    )


def _matches_any(text: str, terms: list[str]) -> bool:
    return any(text_contains(text, term) for term in terms)


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if text_contains(text, term)]


@dataclass(frozen=True)
class LocationScore:
    score_delta: int
    positive_reasons: list[str]
    negative_reasons: list[str]


@dataclass(frozen=True)
class RoleScore:
    score_delta: int
    positive_reasons: list[str]
    negative_reasons: list[str]


def _score_role_type(job: Job, profile: dict[str, Any]) -> RoleScore:
    preferences = profile.get("role_preferences") or _legacy_role_preferences(profile)
    title_text = _normalize_role_text(job.title)
    positive: list[str] = []
    negative: list[str] = []
    score_delta = 0

    ic_matches = _matched_role_terms(title_text, preferences.get("individual_contributor_positive", []))
    management_matches = _matched_role_terms(title_text, preferences.get("management_negative", []))
    product_manager_matches = _matched_role_terms(
        title_text,
        ["Product Manager", "Program Manager", "Project Manager", "Product Owner"],
    )

    is_management = bool(management_matches)
    is_product_manager = bool(product_manager_matches)

    if ic_matches and not is_management and not is_product_manager:
        bonus = int(preferences.get("ic_role_bonus", 25))
        score_delta += bonus
        positive.append(f"Individual contributor data role match: {', '.join(ic_matches)} (+{bonus})")
    elif ic_matches and is_management:
        positive.append(f"Data domain detected in management title: {', '.join(ic_matches)}")

    if is_product_manager:
        penalty = int(preferences.get("product_manager_penalty", 35))
        score_delta -= penalty
        negative.append(f"Product/program/project manager title match: {', '.join(product_manager_matches)} (-{penalty})")

    non_product_management = [
        match for match in management_matches if match not in product_manager_matches
    ]
    if non_product_management:
        penalty = int(preferences.get("management_penalty", 45))
        score_delta -= penalty
        negative.append(f"Management-track title match: {', '.join(non_product_management)} (-{penalty})")

    if not ic_matches:
        if _is_generic_engineering_title(title_text) or not _has_data_role_signal(title_text):
            penalty = int(preferences.get("non_data_role_penalty", 25))
            score_delta -= penalty
            negative.append(f"Non-IC data role title penalty (-{penalty})")

    if "lead" in title_text and ic_matches and not is_management:
        negative.append("Lead title treated cautiously as IC only because data role is explicit")

    return RoleScore(score_delta, positive, negative)


def _score_location(job: Job, profile: dict[str, Any]) -> LocationScore:
    preferences = profile.get("location_preferences") or _legacy_location_preferences(profile)
    primary_location_text = _normalize_location_text(job.location)
    if not primary_location_text:
        primary_location_text = _normalize_location_text(job.remote_type)
    positive: list[str] = []
    negative: list[str] = []
    score_delta = 0

    if not primary_location_text or primary_location_text in {"unknown", "n/a", "na"}:
        penalty = int(preferences.get("unknown_location_penalty", 10))
        negative.append(f"Unknown location penalty: -{penalty}")
        score_delta -= penalty

    non_us_matches = _matched_location_terms(primary_location_text, preferences.get("negative", []))
    if non_us_matches:
        penalty = int(preferences.get("non_us_penalty", 60))
        score_delta -= penalty
        negative.append(f"Non-US or unwanted location match: {', '.join(non_us_matches)} (-{penalty})")

    preferred_matches = _matched_location_terms(primary_location_text, preferences.get("strong_positive", []))
    if preferred_matches:
        bonus = int(preferences.get("preferred_location_bonus", 30))
        score_delta += bonus
        positive.append(f"Georgia preferred location match: {', '.join(preferred_matches)} (+{bonus})")

    remote_us_matches = _matched_location_terms(primary_location_text, preferences.get("remote_positive", []))
    if remote_us_matches and not non_us_matches:
        bonus = int(preferences.get("remote_us_bonus", 25))
        score_delta += bonus
        positive.append(f"Remote US location match: {', '.join(remote_us_matches)} (+{bonus})")

    mild_matches = _matched_location_terms(primary_location_text, preferences.get("mild_positive", []))
    if non_us_matches or preferred_matches or remote_us_matches:
        mild_matches = []
    if mild_matches:
        bonus = int(preferences.get("mild_location_bonus", 10))
        score_delta += bonus
        positive.append(f"Mild location match: {', '.join(mild_matches)} (+{bonus})")

    broad_us_matches = _broad_us_matches(primary_location_text)
    broad_us_bonus = int(preferences.get("broad_us_bonus", 0))
    if broad_us_matches and not preferred_matches and not remote_us_matches and not non_us_matches:
        if broad_us_bonus:
            score_delta += broad_us_bonus
            positive.append(f"Broad US location match: {', '.join(broad_us_matches)} (+{broad_us_bonus})")
        else:
            positive.append(f"Broad US location is neutral: {', '.join(broad_us_matches)}")

    onsite_matches = _matched_location_terms(
        primary_location_text,
        preferences.get("unwanted_onsite", preferences.get("onsite_only_negative", [])),
    )
    if onsite_matches and not remote_us_matches and _appears_onsite_only(primary_location_text):
        penalty = int(preferences.get("unwanted_onsite_penalty", 40))
        score_delta -= penalty
        negative.append(f"Unwanted onsite-only location: {', '.join(onsite_matches)} (-{penalty})")

    if (
        not preferred_matches
        and not remote_us_matches
        and not mild_matches
        and not non_us_matches
        and not onsite_matches
        and not broad_us_matches
    ):
        negative.append("No preferred location signal found")

    return LocationScore(score_delta, positive, negative)


def _legacy_location_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "strong_positive": profile.get("locations", []),
        "remote_positive": [],
        "mild_positive": [],
        "negative": [],
        "unwanted_onsite": [],
        "unknown_location_penalty": 10,
        "non_us_penalty": 60,
        "unwanted_onsite_penalty": 40,
        "preferred_location_bonus": 30,
        "mild_location_bonus": 10,
    }


def _legacy_role_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "individual_contributor_positive": profile.get("target_titles", []),
        "acceptable_senior_ic_prefixes": ["Senior", "Sr.", "Staff", "Principal", "Lead"],
        "management_negative": ["Manager", "Director", "VP", "Vice President", "Head of"],
        "management_penalty": 45,
        "product_manager_penalty": 35,
        "non_data_role_penalty": 25,
        "ic_role_bonus": 25,
    }


def _normalize_role_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s+-]", " ", text.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _matched_role_terms(title_text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _role_term_matches(title_text, term)]


def _role_term_matches(title_text: str, term: str) -> bool:
    normalized_term = _normalize_role_text(term)
    if not normalized_term:
        return False
    return bool(re.search(rf"\b{re.escape(normalized_term)}\b", title_text))


def _has_data_role_signal(title_text: str) -> bool:
    signals = [
        "data",
        "analytics",
        "analyst",
        "machine learning",
        "ml engineer",
        "bi",
        "business intelligence",
        "applied scientist",
        "decision scientist",
        "risk",
        "quantitative",
    ]
    return any(_role_term_matches(title_text, signal) for signal in signals)


def _is_generic_engineering_title(title_text: str) -> bool:
    generic_terms = [
        "software engineer",
        "security engineer",
        "observability engineer",
        "forward deployed engineer",
    ]
    data_qualifiers = ["data", "analytics", "machine learning", "ml", "bi", "risk"]
    return any(_role_term_matches(title_text, term) for term in generic_terms) and not any(
        _role_term_matches(title_text, qualifier) for qualifier in data_qualifiers
    )


def _normalize_location_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s+-]", " ", text.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _matched_location_terms(location_text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _location_term_matches(location_text, term)]


def _location_term_matches(location_text: str, term: str) -> bool:
    normalized_term = _normalize_location_text(term)
    if not normalized_term:
        return False
    if normalized_term == "uk":
        return bool(re.search(r"\buk\b", location_text))
    if normalized_term == "ga":
        return bool(re.search(r"\bga\b", location_text))
    if normalized_term == "est":
        return bool(re.search(r"\best\b", location_text))
    if normalized_term == "cst":
        return bool(re.search(r"\bcst\b", location_text))
    return normalized_term in location_text


def _broad_us_matches(location_text: str) -> list[str]:
    matches: list[str] = []
    if re.search(r"\bunited states\b", location_text):
        matches.append("United States")
    if re.search(r"\busa\b", location_text):
        matches.append("USA")
    if re.search(r"\bus\b", location_text):
        matches.append("US")
    return matches


def _appears_onsite_only(location_text: str) -> bool:
    has_remote_or_hybrid = "remote" in location_text or "hybrid" in location_text
    has_onsite_signal = (
        "onsite" in location_text
        or "on-site" in location_text
        or "in office" in location_text
        or "office" in location_text
    )
    return has_onsite_signal or not has_remote_or_hybrid


def _seniority_fit(title: str, text: str) -> bool:
    combined = f"{title} {text}"
    senior_terms = ["senior", "sr.", "lead", "principal", "staff"]
    junior_terms = ["junior", "entry level", "internship", "intern"]
    return _matches_any(combined, senior_terms) and not _matches_any(combined, junior_terms)


def _max_salary(text: str) -> int | None:
    values: list[int] = []
    for raw in re.findall(r"\$?\s?(\d{2,3}(?:,\d{3})?|\d{3})\s?k?", text, flags=re.IGNORECASE):
        cleaned = int(raw.replace(",", ""))
        if cleaned < 1000:
            cleaned *= 1000
        if 20_000 <= cleaned <= 500_000:
            values.append(cleaned)
    return max(values) if values else None
