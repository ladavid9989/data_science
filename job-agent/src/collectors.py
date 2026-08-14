from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


def collect_all(sources: list[dict[str, Any]], crawler_config: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    delay = float(crawler_config.get("delay_seconds", 1))
    for source in sources:
        source_type = source.get("type")
        try:
            if source_type == "local_files":
                collected = collect_local_files(source)
            elif source_type == "greenhouse":
                collected = collect_greenhouse(source, crawler_config)
            elif source_type == "lever":
                collected = collect_lever(source, crawler_config)
            elif source_type == "ashby":
                collected = collect_ashby(source, crawler_config)
            elif source_type == "serpapi_google_jobs":
                collected = collect_serpapi_google_jobs(source, crawler_config)
            else:
                LOGGER.warning("Skipping unknown source type: %s", source_type)
                collected = []
            jobs.extend(collected)
        except Exception:
            LOGGER.exception("Source failed and was skipped: %s", source.get("name", source_type))
        if delay > 0 and source_type != "local_files":
            time.sleep(delay)
    return jobs


def collect_local_files(source: dict[str, Any]) -> list[dict[str, Any]]:
    folder = Path(source.get("path", "data/sample_jobs"))
    if not folder.exists():
        LOGGER.warning("Local jobs folder does not exist: %s", folder)
        return []

    jobs: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".txt", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        jobs.append(
            {
                "source_type": "local_files",
                "source": source.get("name", "Local Files"),
                "id": path.stem,
                "absolute_url": path.as_posix(),
                "title": path.stem.replace("_", " ").title(),
                "company": "Sample Company",
                "location": "",
                "content": text,
            }
        )
    return jobs


def collect_greenhouse(source: dict[str, Any], crawler_config: dict[str, Any]) -> list[dict[str, Any]]:
    board_token = source.get("board_token")
    if not board_token or board_token == "example":
        LOGGER.info("Skipping placeholder Greenhouse source: %s", source.get("name"))
        return []
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    payload = _get_json(url, crawler_config)
    return [
        {**job, "source_type": "greenhouse", "source": source.get("name", board_token)}
        for job in payload.get("jobs", [])
    ]


def collect_lever(source: dict[str, Any], crawler_config: dict[str, Any]) -> list[dict[str, Any]]:
    company = source.get("company")
    if not company or company == "example":
        LOGGER.info("Skipping placeholder Lever source: %s", source.get("name"))
        return []
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    payload = _get_json(url, crawler_config)
    if not isinstance(payload, list):
        LOGGER.warning("Unexpected Lever response for %s", company)
        return []
    return [{**job, "source_type": "lever", "source": source.get("name", company)} for job in payload]


def collect_ashby(source: dict[str, Any], crawler_config: dict[str, Any]) -> list[dict[str, Any]]:
    board_name = source.get("board_name")
    if not board_name or board_name == "example":
        LOGGER.info("Skipping placeholder Ashby source: %s", source.get("name"))
        return []
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}"
    payload = _get_json(url, crawler_config)
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    return [{**job, "source_type": "ashby", "source": source.get("name", board_name)} for job in jobs]


def collect_serpapi_google_jobs(source: dict[str, Any], crawler_config: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = source.get("api_key") or os.getenv("SERPAPI_API_KEY")
    if not api_key:
        LOGGER.info("Skipping SerpApi Google Jobs source without SERPAPI_API_KEY: %s", source.get("name"))
        return []
    params = {
        "engine": "google_jobs",
        "q": source.get("query") or "data scientist jobs Atlanta GA",
        "api_key": api_key,
        "hl": source.get("hl", "en"),
    }
    if source.get("location"):
        params["location"] = source["location"]
    payload = _get_json("https://serpapi.com/search.json", crawler_config, params=params)
    jobs = payload.get("jobs_results", []) if isinstance(payload, dict) else []
    return [
        {
            **job,
            "source_type": "serpapi_google_jobs",
            "source": source.get("name", "SerpApi Google Jobs"),
        }
        for job in jobs
    ]


def _get_json(url: str, crawler_config: dict[str, Any], params: dict[str, Any] | None = None) -> Any:
    headers = {"User-Agent": crawler_config.get("user_agent", "LocalJobAgent/0.1")}
    timeout = int(crawler_config.get("timeout_seconds", 20))
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        LOGGER.warning("Request failed for %s: %s", url, exc)
    except ValueError as exc:
        LOGGER.warning("Invalid JSON from %s: %s", url, exc)
    return {}
