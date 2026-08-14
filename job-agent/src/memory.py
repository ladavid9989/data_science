from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.normalizer import Job
from src.scorer import ScoreResult


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_job_id TEXT,
                job_url TEXT UNIQUE,
                title TEXT NOT NULL,
                company TEXT,
                location TEXT,
                remote_type TEXT,
                description_text TEXT,
                compensation_text TEXT,
                posted_date TEXT,
                posted_date_source TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                matched_skills_json TEXT NOT NULL,
                missing_skills_json TEXT NOT NULL,
                positive_reasons_json TEXT NOT NULL,
                negative_reasons_json TEXT NOT NULL,
                scored_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS email_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_path TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS resume_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                extracted_text_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS resume_tailoring_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                resume_version_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                user_notes TEXT,
                analysis_text TEXT NOT NULL,
                tailored_resume_md_path TEXT NOT NULL,
                tailored_resume_docx_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id),
                FOREIGN KEY(resume_version_id) REFERENCES resume_versions(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_job
            ON jobs(source, source_job_id);

            CREATE INDEX IF NOT EXISTS idx_job_feedback_job_id
            ON job_feedback(job_id);

            CREATE INDEX IF NOT EXISTS idx_resume_versions_active
            ON resume_versions(is_active);

            CREATE INDEX IF NOT EXISTS idx_tailoring_runs_job_id
            ON resume_tailoring_runs(job_id);
            """
        )
        _ensure_column(conn, "jobs", "posted_date_source", "TEXT")


def upsert_job(db_path: str | Path, job: Job) -> int:
    now = _now()
    job_url = job.job_url or f"{job.source}:{job.source_job_id}"
    with _connect(db_path) as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (job_url,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE jobs
                SET source = ?, source_job_id = ?, title = ?, company = ?, location = ?,
                    remote_type = ?, description_text = ?, compensation_text = ?,
                    posted_date = ?, posted_date_source = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    job.source,
                    job.source_job_id,
                    job.title,
                    job.company,
                    job.location,
                    job.remote_type,
                    job.description_text,
                    job.compensation_text,
                    job.posted_date,
                    job.posted_date_source,
                    now,
                    existing["id"],
                ),
            )
            return int(existing["id"])

        cursor = conn.execute(
            """
            INSERT INTO jobs (
                source, source_job_id, job_url, title, company, location, remote_type,
                description_text, compensation_text, posted_date, posted_date_source, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.source,
                job.source_job_id,
                job_url,
                job.title,
                job.company,
                job.location,
                job.remote_type,
                job.description_text,
                job.compensation_text,
                job.posted_date,
                job.posted_date_source,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)


def save_score(db_path: str | Path, job_id: int, result: ScoreResult) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_scores (
                job_id, score, matched_skills_json, missing_skills_json,
                positive_reasons_json, negative_reasons_json, scored_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                result.score,
                json.dumps(result.matched_skills),
                json.dumps(result.missing_skills),
                json.dumps(result.positive_reasons),
                json.dumps(result.negative_reasons),
                _now(),
            ),
        )


def get_jobs(db_path: str | Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY last_seen_at DESC").fetchall()
        return [dict(row) for row in rows]


def get_ranked_jobs(db_path: str | Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                j.*,
                s.score,
                s.matched_skills_json,
                s.missing_skills_json,
                s.positive_reasons_json,
                s.negative_reasons_json,
                s.scored_at
            FROM jobs j
            JOIN job_scores s ON s.id = (
                SELECT id FROM job_scores
                WHERE job_id = j.id
                ORDER BY scored_at DESC, id DESC
                LIMIT 1
            )
            ORDER BY s.score DESC, j.title ASC
            """
        ).fetchall()
    ranked = [dict(row) for row in rows]
    for row in ranked:
        for key in (
            "matched_skills_json",
            "missing_skills_json",
            "positive_reasons_json",
            "negative_reasons_json",
        ):
            row[key.replace("_json", "")] = json.loads(row.get(key) or "[]")
    return ranked


def save_feedback(db_path: str | Path, job_id: int, action: str, notes: str = "") -> None:
    allowed_actions = {"like", "dislike", "hide", "save", "applied"}
    if action not in allowed_actions:
        raise ValueError(f"Unsupported feedback action: {action}")
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_feedback (job_id, action, notes, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, action, notes, _now()),
        )


def get_latest_feedback_by_job(db_path: str | Path) -> dict[int, dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT jf.*
            FROM job_feedback jf
            JOIN (
                SELECT job_id, MAX(id) AS latest_id
                FROM job_feedback
                GROUP BY job_id
            ) latest ON latest.latest_id = jf.id
            """
        ).fetchall()
    return {int(row["job_id"]): dict(row) for row in rows}


def get_feedback_version(db_path: str | Path) -> tuple[int, int]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(MAX(id), 0) AS max_id FROM job_feedback"
        ).fetchone()
    return int(row["count"]), int(row["max_id"])


def get_feedback_events(db_path: str | Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                jf.id,
                jf.job_id,
                jf.action,
                jf.notes,
                jf.created_at,
                j.source,
                j.title,
                j.company,
                j.location,
                j.remote_type,
                j.description_text
            FROM job_feedback jf
            JOIN jobs j ON j.id = jf.job_id
            ORDER BY jf.id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def save_resume_version(
    db_path: str | Path,
    original_filename: str,
    stored_path: str,
    extracted_text_path: str,
    file_hash: str,
) -> int:
    with _connect(db_path) as conn:
        conn.execute("UPDATE resume_versions SET is_active = 0 WHERE is_active = 1")
        cursor = conn.execute(
            """
            INSERT INTO resume_versions (
                original_filename, stored_path, extracted_text_path,
                file_hash, uploaded_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (original_filename, stored_path, extracted_text_path, file_hash, _now()),
        )
        return int(cursor.lastrowid)


def get_active_resume(db_path: str | Path) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM resume_versions
            WHERE is_active = 1
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def list_resume_versions(db_path: str | Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM resume_versions
            ORDER BY uploaded_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def save_tailoring_run(
    db_path: str | Path,
    job_id: int,
    resume_version_id: int,
    model: str,
    user_notes: str,
    analysis_text: str,
    tailored_resume_md_path: str,
    tailored_resume_docx_path: str,
) -> int:
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO resume_tailoring_runs (
                job_id, resume_version_id, model, user_notes, analysis_text,
                tailored_resume_md_path, tailored_resume_docx_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                resume_version_id,
                model,
                user_notes,
                analysis_text,
                tailored_resume_md_path,
                tailored_resume_docx_path,
                _now(),
            ),
        )
        return int(cursor.lastrowid)


def list_tailoring_runs_for_job(db_path: str | Path, job_id: int) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM resume_tailoring_runs
            WHERE job_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_report_sent(db_path: str | Path, report_path: str, status: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO email_reports (report_path, sent_at, status) VALUES (?, ?, ?)",
            (report_path, _now(), status),
        )


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
