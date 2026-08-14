from src.memory import get_latest_feedback_by_job, init_db, save_feedback, upsert_job
from src.normalizer import Job


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
