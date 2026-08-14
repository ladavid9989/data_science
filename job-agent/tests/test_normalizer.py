from src.normalizer import normalize_job


def test_local_raw_job_can_be_normalized() -> None:
    raw = {
        "source_type": "local_files",
        "source": "Sample Local Jobs",
        "id": "senior_data_scientist",
        "absolute_url": "data/sample_jobs/senior_data_scientist.txt",
        "content": """
        Title: Senior Data Scientist
        Company: First Horizon Analytics
        Location: Remote - Atlanta, Georgia
        Compensation: $145,000 - $175,000 per year

        Python, SQL, Machine Learning, Statistics, Data Analysis.
        """,
    }
    job = normalize_job(raw)
    assert job.title == "Senior Data Scientist"
    assert job.company == "First Horizon Analytics"
    assert job.location == "Remote - Atlanta, Georgia"
    assert job.remote_type == "Remote"
    assert "Python" in job.description_text


def test_lever_epoch_millis_posted_date_is_normalized() -> None:
    job = normalize_job(
        {
            "source_type": "lever",
            "source": "Example Lever",
            "id": "abc",
            "hostedUrl": "https://example.com/job",
            "text": "Data Scientist",
            "categories": {"location": "Remote - USA"},
            "createdAt": 1751328000000,
            "description": "Python and SQL",
        }
    )
    assert job.posted_date == "2025-07-01"
    assert job.posted_date_source == "Lever createdAt"


def test_serpapi_google_jobs_payload_can_be_normalized() -> None:
    job = normalize_job(
        {
            "source_type": "serpapi_google_jobs",
            "source": "SerpApi Google Jobs",
            "job_id": "123",
            "title": "Data Analyst",
            "company_name": "Example Co",
            "location": "Atlanta, GA",
            "description": "<p>SQL dashboards</p>",
            "detected_extensions": {"posted_at": "2026-07-01"},
            "apply_options": [{"link": "https://example.com/apply"}],
        }
    )
    assert job.company == "Example Co"
    assert job.location == "Atlanta, GA"
    assert job.job_url == "https://example.com/apply"
    assert job.posted_date == "2026-07-01"
    assert job.posted_date_source == "SerpApi Google Jobs posted_at"
