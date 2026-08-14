from pathlib import Path

from src.memory import init_db, list_tailoring_runs_for_job, save_resume_version
from src.tailoring import tailor_resume_for_job


class FakeGenerator:
    model = "fake-local-model"

    def generate(self, prompt: str, system: str = "") -> str:
        assert "Job description:" in prompt
        assert "Source resume:" in prompt
        assert "Hermes" in system
        return """
## Fit Analysis
- Strong match on experimentation and analytics.
- Do not invent Statsig platform experience.

## Tailored Resume
### Candidate Name
- Built analytics workflows with Python and SQL.
- Communicated findings to stakeholders.
""".strip()


class FencedFakeGenerator:
    model = "fake-fenced-model"

    def generate(self, prompt: str, system: str = "") -> str:
        return """
```markdown
## Fit Analysis
### Fit Verdict
Strong adjacent fit.

### Evidence Map
| JD requirement | Resume evidence | How to position it | Confidence |
|---|---|---|---|
| Experimentation | Experimental design | Emphasize statistics | Medium |

## Tailored Resume
---
# Candidate Name
- **Python** and SQL analytics.
---
```
""".strip()


def test_tailor_resume_for_job_saves_markdown_docx_and_db_row(tmp_path: Path) -> None:
    db_path = tmp_path / "job_agent.sqlite3"
    init_db(db_path)
    resume_id = save_resume_version(
        db_path,
        "resume.docx",
        "data/profile/resumes/original/resume.docx",
        "data/profile/resumes/extracted/resume.txt",
        "abc",
    )
    job = {
        "id": 42,
        "title": "Customer Data Scientist",
        "company": "Amplitude",
        "location": "Remote - USA",
        "description_text": "Experimentation, product analytics, statistics, customer-facing consulting.",
    }
    active_resume = {"id": resume_id, "original_filename": "resume.docx"}

    result = tailor_resume_for_job(
        db_path,
        job,
        active_resume,
        "Python SQL analytics stakeholder communication",
        "Emphasize experimentation. Do not overstate Statsig.",
        FakeGenerator(),
        {"output_dir": str(tmp_path / "tailored")},
    )

    assert Path(result.markdown_path).exists()
    assert Path(result.docx_path).exists()
    assert "Tailored Resume" in Path(result.markdown_path).read_text(encoding="utf-8")
    runs = list_tailoring_runs_for_job(db_path, 42)
    assert len(runs) == 1
    assert runs[0]["model"] == "fake-local-model"


def test_tailoring_removes_code_fences_and_horizontal_rules(tmp_path: Path) -> None:
    db_path = tmp_path / "job_agent.sqlite3"
    init_db(db_path)
    resume_id = save_resume_version(db_path, "resume.docx", "resume.docx", "resume.txt", "abc")
    result = tailor_resume_for_job(
        db_path,
        {"id": 7, "title": "Data Scientist", "company": "Example", "description_text": "Experimentation"},
        {"id": resume_id, "original_filename": "resume.docx"},
        "Python SQL experimental design",
        "",
        FencedFakeGenerator(),
        {"output_dir": str(tmp_path / "tailored")},
    )

    markdown = Path(result.markdown_path).read_text(encoding="utf-8")
    assert "```" not in markdown
    assert "---" not in markdown
    assert "# Candidate Name" in markdown
