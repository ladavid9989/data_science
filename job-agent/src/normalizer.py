from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.freshness import normalize_posted_date
from src.utils import clean_html_to_text


@dataclass(frozen=True)
class Job:
    source: str
    source_job_id: str
    job_url: str
    title: str
    company: str
    location: str
    remote_type: str
    description_text: str
    compensation_text: str
    posted_date: str
    posted_date_source: str = ""


def normalize_job(raw: dict[str, Any]) -> Job:
    source_type = raw.get("source_type", "")
    if source_type == "greenhouse":
        return _normalize_greenhouse(raw)
    if source_type == "lever":
        return _normalize_lever(raw)
    if source_type == "ashby":
        return _normalize_ashby(raw)
    if source_type == "serpapi_google_jobs":
        return _normalize_serpapi_google_jobs(raw)
    return _normalize_local_or_generic(raw)


def _normalize_greenhouse(raw: dict[str, Any]) -> Job:
    location = _pick_nested(raw, ["location", "name"]) or ""
    description = _html_to_text(str(raw.get("content") or ""))
    return Job(
        source=str(raw.get("source") or "Greenhouse"),
        source_job_id=str(raw.get("id") or raw.get("internal_job_id") or raw.get("absolute_url") or ""),
        job_url=str(raw.get("absolute_url") or ""),
        title=str(raw.get("title") or "Untitled job"),
        company=str(raw.get("company") or raw.get("source") or "Unknown company"),
        location=location,
        remote_type=_remote_type(location, description),
        description_text=description,
        compensation_text=_extract_compensation(description),
        posted_date=normalize_posted_date(raw.get("updated_at")),
        posted_date_source="Greenhouse updated_at" if raw.get("updated_at") else "",
    )


def _normalize_lever(raw: dict[str, Any]) -> Job:
    categories = raw.get("categories") or {}
    location = str(categories.get("location") or raw.get("workplaceType") or "")
    description = _html_to_text(" ".join(_lever_description_parts(raw)))
    return Job(
        source=str(raw.get("source") or "Lever"),
        source_job_id=str(raw.get("id") or raw.get("hostedUrl") or ""),
        job_url=str(raw.get("hostedUrl") or raw.get("applyUrl") or ""),
        title=str(raw.get("text") or "Untitled job"),
        company=str(raw.get("company") or raw.get("source") or "Unknown company"),
        location=location,
        remote_type=_remote_type(location, description),
        description_text=description,
        compensation_text=_extract_compensation(description),
        posted_date=normalize_posted_date(raw.get("createdAt")),
        posted_date_source="Lever createdAt" if raw.get("createdAt") else "",
    )


def _normalize_ashby(raw: dict[str, Any]) -> Job:
    location = str(raw.get("location") or "")
    description = _html_to_text(str(raw.get("descriptionHtml") or raw.get("description") or ""))
    return Job(
        source=str(raw.get("source") or "Ashby"),
        source_job_id=str(raw.get("id") or raw.get("jobUrl") or ""),
        job_url=str(raw.get("jobUrl") or raw.get("applyUrl") or ""),
        title=str(raw.get("title") or "Untitled job"),
        company=str(raw.get("company") or raw.get("source") or "Unknown company"),
        location=location,
        remote_type=_remote_type(location, description),
        description_text=description,
        compensation_text=_extract_compensation(description),
        posted_date=normalize_posted_date(raw.get("publishedDate") or raw.get("updatedAt")),
        posted_date_source=_ashby_posted_date_source(raw),
    )


def _normalize_serpapi_google_jobs(raw: dict[str, Any]) -> Job:
    extensions = raw.get("detected_extensions") or raw.get("extensions") or {}
    if isinstance(extensions, list):
        extensions = {}
    posted_date = extensions.get("posted_at") or extensions.get("date_posted") or raw.get("posted_at")
    location = str(raw.get("location") or "")
    description = _html_to_text(str(raw.get("description") or ""))
    return Job(
        source=str(raw.get("source") or "SerpApi Google Jobs"),
        source_job_id=str(raw.get("job_id") or raw.get("share_link") or raw.get("title") or ""),
        job_url=str(_first_apply_link(raw) or raw.get("share_link") or ""),
        title=str(raw.get("title") or "Untitled job"),
        company=str(raw.get("company_name") or raw.get("company") or "Unknown company"),
        location=location,
        remote_type=_remote_type(location, description),
        description_text=description,
        compensation_text=_extract_compensation(description),
        posted_date=normalize_posted_date(posted_date),
        posted_date_source="SerpApi Google Jobs posted_at" if posted_date else "",
    )


def _normalize_local_or_generic(raw: dict[str, Any]) -> Job:
    content = str(raw.get("content") or raw.get("description") or "")
    text = _html_to_text(content)
    title = _field_from_text(content, "Title") or str(raw.get("title") or "Untitled job")
    company = _field_from_text(content, "Company") or str(raw.get("company") or "Unknown company")
    location = _field_from_text(content, "Location") or str(raw.get("location") or "")
    compensation = _field_from_text(content, "Compensation") or _extract_compensation(text)
    return Job(
        source=str(raw.get("source") or "Local Files"),
        source_job_id=str(raw.get("id") or raw.get("source_job_id") or raw.get("absolute_url") or title),
        job_url=str(raw.get("absolute_url") or raw.get("job_url") or ""),
        title=title,
        company=company,
        location=location,
        remote_type=_remote_type(location, text),
        description_text=text,
        compensation_text=compensation,
        posted_date=normalize_posted_date(raw.get("posted_date")),
        posted_date_source=str(raw.get("posted_date_source") or "Local posted_date") if raw.get("posted_date") else "",
    )


def _html_to_text(value: str) -> str:
    return re.sub(r"\s+", " ", clean_html_to_text(value)).strip()


def _lever_description_parts(raw: dict[str, Any]) -> list[str]:
    parts = [str(raw.get("description") or ""), str(raw.get("descriptionPlain") or "")]
    for item in raw.get("lists") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
            parts.append(str(item.get("content") or ""))
    parts.append(str(raw.get("additional") or ""))
    return parts


def _field_from_text(text: str, field_name: str) -> str:
    pattern = rf"^\s*{re.escape(field_name)}:\s*(.+)$"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _pick_nested(raw: dict[str, Any], keys: list[str]) -> str | None:
    value: Any = raw
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return str(value) if value is not None else None


def _first_apply_link(raw: dict[str, Any]) -> str:
    apply_options = raw.get("apply_options") or []
    if isinstance(apply_options, list) and apply_options:
        first = apply_options[0]
        if isinstance(first, dict):
            return str(first.get("link") or "")
    return ""


def _ashby_posted_date_source(raw: dict[str, Any]) -> str:
    if raw.get("publishedDate"):
        return "Ashby publishedDate"
    if raw.get("updatedAt"):
        return "Ashby updatedAt"
    return ""


def _remote_type(location: str, description: str) -> str:
    combined = f"{location} {description}".casefold()
    if "hybrid" in combined:
        return "Hybrid"
    if "remote" in combined:
        return "Remote"
    if "onsite" in combined or "on-site" in combined:
        return "Onsite"
    return "Unknown"


def _extract_compensation(text: str) -> str:
    salary_pattern = r"(\$\s?\d{2,3}(?:,\d{3})?(?:\s?-\s?\$?\s?\d{2,3}(?:,\d{3})?)?\s?(?:per year|annually|/year|year)?)"
    matches = re.findall(salary_pattern, text, flags=re.IGNORECASE)
    return "; ".join(matches[:3])
