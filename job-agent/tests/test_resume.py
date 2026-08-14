from io import BytesIO

from docx import Document

from src.memory import get_active_resume, init_db
from src.resume import adjust_score_for_resume, extract_resume_text, save_uploaded_resume, score_resume_fit
from src.scorer import ScoreResult


def test_docx_resume_text_can_be_extracted() -> None:
    content = _docx_bytes(["Senior data scientist", "Python SQL Machine Learning"])

    text = extract_resume_text("resume.docx", content)

    assert "Senior data scientist" in text
    assert "Python SQL Machine Learning" in text


def test_uploaded_resume_is_saved_as_active_version(tmp_path) -> None:
    db_path = tmp_path / "job_agent.sqlite3"
    profile_dir = tmp_path / "profile"
    init_db(db_path)
    content = _docx_bytes(["Banking analytics", "Python SQL Snowflake"])

    saved = save_uploaded_resume(db_path, "resume.docx", content, profile_dir)
    active = get_active_resume(db_path)

    assert active is not None
    assert active["original_filename"] == "resume.docx"
    assert active["file_hash"] == saved["file_hash"]
    assert profile_dir.joinpath("resumes", "original").exists()
    assert profile_dir.joinpath("resumes", "extracted").exists()


def test_resume_fit_scores_overlap_between_resume_and_job() -> None:
    resume_text = "Python SQL Machine Learning Banking Risk Modeling Snowflake"
    job = {
        "title": "Senior Data Scientist",
        "description_text": "Python SQL Machine Learning Risk Modeling Tableau",
        "matched_skills": ["Python", "SQL", "Machine Learning"],
        "positive_reasons": [],
    }

    fit = score_resume_fit(job, resume_text)

    assert fit is not None
    assert fit.score > 50
    assert "python" in fit.matched_terms
    assert "tableau" in fit.missing_terms


def test_resume_adjustment_boosts_strong_resume_fit() -> None:
    result = ScoreResult(
        score=70,
        matched_skills=[],
        missing_skills=[],
        positive_reasons=[],
        negative_reasons=[],
    )
    job = {
        "title": "Senior Data Scientist",
        "description_text": "Python SQL Machine Learning Risk Modeling Snowflake",
    }

    adjusted = adjust_score_for_resume(
        result,
        job,
        "Python SQL Machine Learning Risk Modeling Snowflake",
        {"enabled": True, "high_fit_threshold": 70, "high_fit_bonus": 8},
    )

    assert adjusted.score == 78
    assert any("Resume fit is strong" in reason for reason in adjusted.positive_reasons)


def test_resume_adjustment_penalizes_weak_resume_fit() -> None:
    result = ScoreResult(
        score=70,
        matched_skills=[],
        missing_skills=[],
        positive_reasons=[],
        negative_reasons=[],
    )
    job = {
        "title": "Senior Data Scientist",
        "description_text": "Python SQL Machine Learning Risk Modeling Snowflake",
    }

    adjusted = adjust_score_for_resume(
        result,
        job,
        "Excel Power BI",
        {"enabled": True, "low_fit_threshold": 35, "low_fit_penalty": 6},
    )

    assert adjusted.score == 64
    assert any("Resume fit is weak" in reason for reason in adjusted.negative_reasons)


def test_resume_adjustment_does_nothing_without_resume_text() -> None:
    result = ScoreResult(
        score=70,
        matched_skills=[],
        missing_skills=[],
        positive_reasons=[],
        negative_reasons=[],
    )

    adjusted = adjust_score_for_resume(result, {"description_text": "Python SQL"}, "", {"enabled": True})

    assert adjusted == result


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
