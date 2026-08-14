from src.feedback import apply_feedback_adjustments


def test_direct_feedback_adjusts_exact_job_score() -> None:
    jobs = [_job(1, "Data Scientist", "Atlanta, GA", 80)]
    feedback = [_feedback(1, "like", "good fit", "Data Scientist", "Atlanta, GA")]

    adjusted = apply_feedback_adjustments(jobs, feedback)

    assert adjusted[0]["base_score"] == 80
    assert adjusted[0]["score"] == 86
    assert adjusted[0]["feedback_adjustment"] == 6


def test_dislike_feedback_penalizes_similar_future_jobs() -> None:
    jobs = [_job(2, "Data Analyst", "Atlanta, GA", 80, description="cybersecurity reporting")]
    feedback = [_feedback(1, "dislike", "too much cybersecurity", "Data Analyst II", "Atlanta, GA")]

    adjusted = apply_feedback_adjustments(jobs, feedback)

    assert adjusted[0]["score"] < 80
    assert adjusted[0]["feedback_adjustment"] < 0


def test_applied_feedback_boosts_similar_future_jobs() -> None:
    jobs = [_job(2, "Senior Data Scientist", "Remote USA", 80)]
    feedback = [_feedback(1, "applied", "strong ML fit", "Data Scientist", "Remote USA")]

    adjusted = apply_feedback_adjustments(jobs, feedback)

    assert adjusted[0]["score"] > 80


def test_hide_feedback_removes_exact_job_from_effective_ranking() -> None:
    jobs = [_job(1, "Data Scientist", "Atlanta, GA", 80)]
    feedback = [_feedback(1, "hide", "not interested", "Data Scientist", "Atlanta, GA")]

    adjusted = apply_feedback_adjustments(jobs, feedback)

    assert adjusted[0]["score"] == 0
    assert adjusted[0]["feedback_adjustment"] == -100


def _job(job_id: int, title: str, location: str, score: int, description: str = "") -> dict[str, object]:
    return {
        "id": job_id,
        "source": "Example",
        "title": title,
        "company": "Example Co",
        "location": location,
        "description_text": description,
        "score": score,
    }


def _feedback(
    job_id: int,
    action: str,
    notes: str,
    title: str,
    location: str,
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "action": action,
        "notes": notes,
        "source": "Example",
        "title": title,
        "company": "Example Co",
        "location": location,
        "description_text": notes,
    }
