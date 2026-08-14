from src.memory import (
    get_job_by_id,
    get_latest_feedback_by_job,
    get_ranked_jobs_light,
    init_db,
    save_feedback,
    save_score,
    upsert_job,
)
from src.normalizer import Job
from src.scorer import ScoreResult


def test_feedback_can_be_saved_and_latest_feedback_is_returned(tmp_path) -> None:
    db_path = tmp_path / "job_agent.sqlite3"
    init_db(db_path)
    job_id = upsert_job(
        db_path,
        Job(
            source="test",
            source_job_id="1",
            job_url="https://example.com/job",
            title="Senior Data Scientist",
            company="Example Co",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning",
            compensation_text="$150,000",
            posted_date="",
        ),
    )

    save_feedback(db_path, job_id, "like", "Strong fit")
    save_feedback(db_path, job_id, "save", "Review later")

    feedback = get_latest_feedback_by_job(db_path)
    assert feedback[job_id]["action"] == "save"
    assert feedback[job_id]["notes"] == "Review later"


def test_light_ranked_jobs_truncates_description_and_full_job_can_be_loaded(tmp_path) -> None:
    db_path = tmp_path / "job_agent.sqlite3"
    init_db(db_path)
    long_description = "Python SQL " * 300
    job_id = upsert_job(
        db_path,
        Job(
            source="test",
            source_job_id="2",
            job_url="https://example.com/job-2",
            title="Data Scientist",
            company="Example Co",
            location="Remote - USA",
            remote_type="Remote",
            description_text=long_description,
            compensation_text="$150,000",
            posted_date="",
        ),
    )
    save_score(
        db_path,
        job_id,
        ScoreResult(
            score=80,
            matched_skills=["Python", "SQL"],
            missing_skills=[],
            positive_reasons=[],
            negative_reasons=[],
        ),
    )

    light_job = get_ranked_jobs_light(db_path)[0]
    full_job = get_job_by_id(db_path, job_id)

    assert len(light_job["description_text"]) == 1200
    assert full_job is not None
    assert full_job["description_text"] == long_description
