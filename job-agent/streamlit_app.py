from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from src.feedback import apply_feedback_adjustments
from src.freshness import classify_freshness, format_freshness
from src.llm import OllamaError, ollama_client_from_config
from src.memory import get_feedback_events, get_feedback_version, get_latest_feedback_by_job
from src.memory import get_active_resume, get_job_by_id, get_ranked_jobs_light, init_db, list_resume_versions, save_feedback
from src.pipeline import Pipeline
from src.reporter import _passes_location_gate
from src.resume import load_resume_text, save_uploaded_resume, score_resume_fit
from src.tailoring import tailor_resume_for_job
from src.utils import clean_html_to_text, configure_logging


st.set_page_config(page_title="job-agent", layout="wide")


def main() -> None:
    configure_logging()
    pipeline = Pipeline()
    init_db(pipeline.db_path)

    st.title("job-agent")
    st.caption("Local-first ranked job review for Georgia and Remote US IC data roles.")

    with st.sidebar:
        st.header("Controls")
        if st.button("Refresh pipeline", type="primary"):
            with st.spinner("Collecting, scoring, and regenerating report..."):
                pipeline.run_all()
            st.cache_data.clear()
            st.success("Pipeline refreshed.")
            st.rerun()

        min_score = st.slider("Minimum score", 0, 100, int(pipeline.config.get("reporting", {}).get("min_score_to_show", 60)))
        max_display = st.slider("Jobs to show", 5, 50, 10, step=5)
        show_hidden = st.checkbox("Show hidden jobs", value=False)
        source_filter = st.text_input("Source contains", value="")
        location_filter = st.text_input("Location contains", value="")

    jobs_tab, resume_tab = st.tabs(["Jobs", "Resume"])

    with resume_tab:
        _render_resume_panel(pipeline.db_path)

    with jobs_tab:
        active_resume = get_active_resume(pipeline.db_path)
        resume_text = load_resume_text(active_resume)
        if active_resume:
            st.caption(f"Active resume: {active_resume['original_filename']} ({active_resume['uploaded_at']})")
        else:
            st.caption("No active resume uploaded yet. Resume fit is not available.")

        jobs = _visible_jobs(pipeline, min_score, max_display, show_hidden, source_filter, location_filter)
        st.subheader(f"Ranked jobs ({len(jobs)})")

        if not jobs:
            st.info("No jobs match the current filters.")
            return

        for job in jobs:
            _render_job_card(pipeline.db_path, job, active_resume, resume_text, pipeline.config)


def _visible_jobs(
    pipeline: Pipeline,
    min_score: int,
    max_display: int,
    show_hidden: bool,
    source_filter: str,
    location_filter: str,
) -> list[dict[str, Any]]:
    reporting_config = pipeline.config.get("reporting", {})
    ranked_jobs = _load_ranked_jobs(pipeline.db_path)
    feedback_events, feedback_by_job = _load_feedback_data(pipeline.db_path, get_feedback_version(pipeline.db_path))

    candidate_limit = max(250, max_display * 12)
    candidates: list[dict[str, Any]] = []
    for job in ranked_jobs:
        if int(job.get("score") or 0) < max(0, min_score - 20):
            continue
        if reporting_config.get("strict_location_gate", False) and not _passes_location_gate(job, reporting_config):
            continue
        if reporting_config.get("hide_stale_jobs", False):
            freshness = classify_freshness(
                job.get("posted_date"),
                job.get("first_seen_at"),
                posted_date_source=str(job.get("posted_date_source") or ""),
                config=reporting_config.get("freshness", {}),
            )
            if freshness.is_stale:
                continue
        candidates.append(job)
        if len(candidates) >= candidate_limit:
            break

    adjusted_candidates = apply_feedback_adjustments(candidates, feedback_events)

    visible: list[dict[str, Any]] = []
    for job in adjusted_candidates:
        job_id = int(job["id"])
        latest_feedback = feedback_by_job.get(job_id)
        job["latest_feedback"] = latest_feedback
        if int(job.get("score") or 0) < min_score:
            continue
        if latest_feedback and latest_feedback.get("action") == "hide" and not show_hidden:
            continue
        if source_filter and source_filter.casefold() not in str(job.get("source") or "").casefold():
            continue
        if location_filter and location_filter.casefold() not in str(job.get("location") or "").casefold():
            continue
        visible.append(job)
        if len(visible) >= max_display:
            break
    return visible


@st.cache_data(show_spinner=False)
def _load_ranked_jobs(db_path: str) -> list[dict[str, Any]]:
    return get_ranked_jobs_light(db_path)


@st.cache_data(show_spinner=False)
def _load_feedback_data(
    db_path: str,
    feedback_version: tuple[int, int],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    del feedback_version
    feedback_events = get_feedback_events(db_path)
    feedback_by_job = get_latest_feedback_by_job(db_path)
    return feedback_events, feedback_by_job


def _render_resume_panel(db_path: str) -> None:
    st.subheader("Resume")
    uploaded = st.file_uploader(
        "Upload resume",
        type=["docx", "pdf", "txt", "md"],
        help="The original file is stored locally and can be downloaded later.",
    )
    if uploaded is not None and st.button("Save as active resume", type="primary"):
        try:
            save_uploaded_resume(db_path, uploaded.name, uploaded.getvalue())
            st.cache_data.clear()
            st.success("Resume uploaded and set as active.")
            st.rerun()
        except Exception as exc:
            st.error(f"Resume upload failed: {exc}")

    active_resume = get_active_resume(db_path)
    if not active_resume:
        st.info("No resume uploaded yet.")
        return

    st.markdown("### Active resume")
    st.write(f"Filename: {active_resume['original_filename']}")
    st.write(f"Uploaded: {active_resume['uploaded_at']}")
    st.write(f"Version hash: `{str(active_resume['file_hash'])[:12]}`")

    stored_path = str(active_resume.get("stored_path") or "")
    try:
        with open(stored_path, "rb") as file:
            st.download_button(
                "Download original resume",
                data=file.read(),
                file_name=str(active_resume["original_filename"]),
            )
    except OSError:
        st.warning("Original resume file is missing from local storage.")

    resume_text = load_resume_text(active_resume)
    with st.expander("Extracted text preview"):
        st.write(resume_text[:4000] if resume_text else "No text extracted.")

    versions = list_resume_versions(db_path)
    if versions:
        st.markdown("### Resume versions")
        st.dataframe(
            [
                {
                    "id": version["id"],
                    "filename": version["original_filename"],
                    "uploaded_at": version["uploaded_at"],
                    "active": bool(version["is_active"]),
                    "hash": str(version["file_hash"])[:12],
                }
                for version in versions
            ],
            hide_index=True,
        )


def _render_job_card(
    db_path: str,
    job: dict[str, Any],
    active_resume: dict[str, Any] | None,
    resume_text: str,
    app_config: dict[str, Any],
) -> None:
    job_id = int(job["id"])
    title = str(job.get("title") or "Untitled job")
    company = str(job.get("company") or "Unknown company")
    score = int(job.get("score") or 0)
    base_score = int(job.get("base_score", score) or 0)
    feedback_adjustment = int(job.get("feedback_adjustment", 0) or 0)
    location = str(job.get("location") or "Unknown location")
    source = str(job.get("source") or "Unknown source")
    latest_feedback = job.get("latest_feedback") or {}
    freshness = classify_freshness(
        job.get("posted_date"),
        job.get("first_seen_at"),
        posted_date_source=str(job.get("posted_date_source") or ""),
    )

    with st.container(border=True):
        left, right = st.columns([4, 1])
        with left:
            st.markdown(f"### {title}")
            st.markdown(f"**{company}** · {location} · `{source}`")
            st.caption(f"Posted: {format_freshness(freshness)}")
        with right:
            st.metric("Score", score, delta=feedback_adjustment if feedback_adjustment else None)
            resume_fit = score_resume_fit(job, resume_text)
            if resume_fit is not None:
                st.metric("Resume fit", resume_fit.score)
            if feedback_adjustment:
                st.caption(f"Base score: {base_score}")
            if latest_feedback:
                st.caption(f"Last feedback: {latest_feedback.get('action')}")

        st.markdown(f"[Open job posting]({job.get('job_url') or '#'})")
        st.write("Matched skills:", _join(job.get("matched_skills", [])))
        st.write("Missing skills:", _join(job.get("missing_skills", [])))

        show_details = st.toggle("Show reasons and description", key=f"details-{job_id}")
        if show_details:
            st.markdown("**Positive reasons**")
            for reason in _coerce_list(job.get("positive_reasons", [])):
                st.markdown(f"- {reason}")
            st.markdown("**Negative reasons**")
            negative_reasons = _coerce_list(job.get("negative_reasons", []))
            if negative_reasons:
                for reason in negative_reasons:
                    st.markdown(f"- {reason}")
            else:
                st.markdown("- None")
            full_job = _load_job_detail(db_path, job_id)
            description = clean_html_to_text(str(job.get("description_text") or ""))
            if full_job:
                description = clean_html_to_text(str(full_job.get("description_text") or description))
            st.markdown("**Description preview**")
            st.write(description[:4000] if description else "No description available.")
            feedback_reasons = _coerce_list(job.get("feedback_reasons", []))
            if feedback_reasons:
                st.markdown("**Feedback adjustment reasons**")
                for reason in feedback_reasons:
                    st.markdown(f"- {reason}")
            resume_fit = score_resume_fit(full_job or job, resume_text)
            if resume_fit is not None:
                st.markdown("**Resume fit terms**")
                st.write("Matched:", _join(resume_fit.matched_terms))
                st.write("Job terms missing from resume:", _join(resume_fit.missing_terms))

        notes = st.text_input("Notes", key=f"notes-{job_id}")
        action_columns = st.columns(6)
        actions = [("like", "Like"), ("dislike", "Dislike"), ("hide", "Hide"), ("save", "Save"), ("applied", "Applied")]
        for column, (action, label) in zip(action_columns, actions):
            with column:
                if st.button(label, key=f"{action}-{job_id}"):
                    if action == "dislike":
                        _dislike_dialog(db_path, job_id, title)
                        continue
                    save_feedback(db_path, job_id, action, notes)
                    st.session_state[f"feedback_saved_{job_id}"] = action
                    st.toast(f"Saved feedback: {action}")
        saved_action = st.session_state.pop(f"feedback_saved_{job_id}", None)
        if saved_action:
            st.success(f"Saved feedback: {saved_action}. Refresh or change a filter to update the ranking.")
        with action_columns[-1]:
            tailor_disabled = not active_resume or not resume_text.strip() or not app_config.get("tailoring", {}).get("enabled", True)
            if st.button("Tailor Resume", key=f"tailor-{job_id}", type="primary", disabled=tailor_disabled):
                full_job = _load_job_detail(db_path, job_id) or job
                _tailor_resume_dialog(db_path, full_job, active_resume or {}, resume_text, app_config)


@st.dialog("Why do you dislike this job?")
def _dislike_dialog(db_path: str, job_id: int, title: str) -> None:
    st.write(title)
    reason = st.text_area(
        "Reason",
        placeholder="Examples: too much cybersecurity, not enough ML, too senior, consulting-heavy, weak SQL fit...",
    )
    if st.button("Save dislike"):
        save_feedback(db_path, job_id, "dislike", reason)
        st.session_state[f"feedback_saved_{job_id}"] = "dislike"
        st.toast("Saved dislike feedback.")
        st.success("Dislike feedback saved. Close this dialog when you are ready.")


@st.cache_data(show_spinner=False)
def _load_job_detail(db_path: str, job_id: int) -> dict[str, Any] | None:
    return get_job_by_id(db_path, job_id)


@st.dialog("Tailor Resume")
def _tailor_resume_dialog(
    db_path: str,
    job: dict[str, Any],
    active_resume: dict[str, Any],
    resume_text: str,
    app_config: dict[str, Any],
) -> None:
    result_key = f"tailoring_result_{int(job.get('id') or 0)}_{int(active_resume.get('id') or 0)}"
    st.write(f"{job.get('title') or 'Untitled job'} at {job.get('company') or 'Unknown company'}")
    st.caption(f"Active resume: {active_resume.get('original_filename')}")
    user_notes = st.text_area(
        "Guidance for Hermes",
        placeholder=(
            "Examples: emphasize experimentation and statistics; do not overstate Statsig experience; "
            "keep banking analytics experience; make it customer-facing but truthful."
        ),
    )
    if st.button("Generate tailored resume", type="primary"):
        try:
            llm_config = app_config.get("llm", {})
            client = ollama_client_from_config(llm_config)
            with st.spinner("Hermes is tailoring your resume locally with Ollama..."):
                result = tailor_resume_for_job(
                    db_path,
                    job,
                    active_resume,
                    resume_text,
                    user_notes,
                    client,
                    app_config.get("tailoring", {}),
                )
            st.session_state[result_key] = {
                "analysis_text": result.analysis_text,
                "tailored_resume_markdown": result.tailored_resume_markdown,
                "markdown_path": result.markdown_path,
                "docx_path": result.docx_path,
                "model": result.model,
            }
        except OllamaError as exc:
            st.error(f"Ollama failed: {exc}")
            return
        except Exception as exc:
            st.error(f"Resume tailoring failed: {exc}")
            return

        st.success(f"Tailored resume generated with {result.model}.")

    saved_result = st.session_state.get(result_key)
    if saved_result:
        _render_tailoring_result(saved_result)


def _render_tailoring_result(result: dict[str, Any]) -> None:
    st.markdown("### Fit Analysis")
    st.markdown(str(result.get("analysis_text") or "No fit analysis returned."))
    st.markdown("### Tailored Resume Preview")
    st.markdown(str(result.get("tailored_resume_markdown") or "No tailored resume returned."))

    docx_path = Path(str(result.get("docx_path") or ""))
    markdown_path = Path(str(result.get("markdown_path") or ""))
    try:
        with open(docx_path, "rb") as file:
            st.download_button(
                "Download DOCX",
                data=file.read(),
                file_name=docx_path.name or "tailored_resume.docx",
                on_click="ignore",
            )
        with open(markdown_path, "rb") as file:
            st.download_button(
                "Download Markdown",
                data=file.read(),
                file_name=markdown_path.name or "tailored_resume.md",
                on_click="ignore",
            )
    except OSError:
        st.warning("Generated files were saved, but could not be opened for download.")


def _join(values: Any) -> str:
    if isinstance(values, list):
        return ", ".join(str(value) for value in values) if values else "None"
    return str(values) if values else "None"


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


if __name__ == "__main__":
    main()
