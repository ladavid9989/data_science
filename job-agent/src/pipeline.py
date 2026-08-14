from __future__ import annotations

import logging

from src.collectors import collect_all
from src.emailer import send_report_if_configured
from src.memory import get_active_resume, get_jobs, get_ranked_jobs, init_db, mark_report_sent, save_score, upsert_job
from src.normalizer import Job, normalize_job
from src.reporter import generate_report
from src.resume import adjust_score_for_resume, load_resume_text
from src.scorer import score_job
from src.utils import load_yaml

LOGGER = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        config_path: str = "config/config.yaml",
        profile_path: str = "config/user_profile.yaml",
        sources_path: str = "config/sources.yaml",
    ) -> None:
        self.config = load_yaml(config_path)
        self.profile = load_yaml(profile_path)
        self.sources = load_yaml(sources_path).get("sources", [])
        self.db_path = self.config.get("database", {}).get("path", "data/job_agent.sqlite3")
        self.report_path = self.config.get("output", {}).get("report_path", "output/ranked_jobs.md")

    def collect(self) -> list[int]:
        init_db(self.db_path)
        raw_jobs = collect_all(self.sources, self.config.get("crawler", {}))
        job_ids: list[int] = []
        for raw in raw_jobs:
            try:
                job = normalize_job(raw)
                job_ids.append(upsert_job(self.db_path, job))
            except Exception:
                LOGGER.exception("Failed to normalize/store raw job from %s", raw.get("source"))
        LOGGER.info("Collected and stored %s jobs", len(job_ids))
        return job_ids

    def score(self) -> int:
        init_db(self.db_path)
        resume_text = load_resume_text(get_active_resume(self.db_path))
        resume_config = self.config.get("resume_scoring", {})
        count = 0
        for row in get_jobs(self.db_path):
            job = _job_from_row(row)
            result = score_job(job, self.profile)
            result = adjust_score_for_resume(result, dict(row), resume_text, resume_config)
            save_score(self.db_path, int(row["id"]), result)
            count += 1
        LOGGER.info("Scored %s jobs", count)
        return count

    def report(self) -> str:
        init_db(self.db_path)
        report_path = generate_report(
            get_ranked_jobs(self.db_path),
            self.report_path,
            self.config.get("reporting", {}),
        )
        LOGGER.info("Report written to %s", report_path)
        return report_path

    def email_report(self) -> bool:
        init_db(self.db_path)
        sent = send_report_if_configured(self.report_path)
        mark_report_sent(self.db_path, self.report_path, "sent" if sent else "skipped_or_failed")
        return sent

    def run_all(self) -> str:
        self.collect()
        self.score()
        report_path = self.report()
        self.email_report()
        return report_path


def _job_from_row(row: dict[str, object]) -> Job:
    return Job(
        source=str(row.get("source") or ""),
        source_job_id=str(row.get("source_job_id") or ""),
        job_url=str(row.get("job_url") or ""),
        title=str(row.get("title") or ""),
        company=str(row.get("company") or ""),
        location=str(row.get("location") or ""),
        remote_type=str(row.get("remote_type") or ""),
        description_text=str(row.get("description_text") or ""),
        compensation_text=str(row.get("compensation_text") or ""),
        posted_date=str(row.get("posted_date") or ""),
        posted_date_source=str(row.get("posted_date_source") or ""),
    )
