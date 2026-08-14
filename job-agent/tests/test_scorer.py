from src.normalizer import Job
from src.scorer import score_job


PROFILE = {
    "target_titles": [
        "Senior Data Scientist",
        "Data Scientist",
        "Data Analyst",
        "Senior Data Analyst",
        "Machine Learning Engineer",
        "Data Engineer",
        "Senior Data Engineer",
        "Analytics Engineer",
        "BI Analyst",
        "Business Intelligence Analyst",
        "Applied Scientist",
        "Decision Scientist",
        "Risk Analyst",
        "Risk Analytics",
        "Banking Analytics",
        "Quantitative Analyst",
    ],
    "required_skills": ["Python", "SQL", "Machine Learning", "Statistics", "Data Analysis"],
    "preferred_skills": ["AWS", "Snowflake", "Tableau", "Banking", "Risk Modeling"],
    "industries": ["Banking", "Financial Services"],
    "role_preferences": {
        "individual_contributor_positive": [
            "Data Scientist",
            "Senior Data Scientist",
            "Data Analyst",
            "Senior Data Analyst",
            "Data Engineer",
            "Senior Data Engineer",
            "Analytics Engineer",
            "BI Analyst",
            "Business Intelligence Analyst",
            "Machine Learning Engineer",
            "Applied Scientist",
            "Decision Scientist",
            "Risk Analyst",
            "Risk Analytics",
            "Quantitative Analyst",
            "Customer Analytics",
            "Marketing Analytics",
            "Product Analytics",
        ],
        "acceptable_senior_ic_prefixes": ["Senior", "Sr.", "Staff", "Principal", "Lead"],
        "management_negative": [
            "Manager",
            "Director",
            "Associate Director",
            "Assistant Director",
            "Head of",
            "VP",
            "Vice President",
            "People Manager",
            "Engineering Manager",
            "Security Engineering Manager",
            "Product Manager",
            "Program Manager",
            "Project Manager",
            "Product Owner",
            "Team Lead",
        ],
        "management_penalty": 45,
        "product_manager_penalty": 35,
        "non_data_role_penalty": 25,
        "ic_role_bonus": 25,
    },
    "locations": ["Remote", "Atlanta", "Alpharetta", "Georgia", "GA"],
    "location_preferences": {
        "strong_positive": ["Atlanta", "Alpharetta", "Georgia", "GA"],
        "remote_positive": [
            "Remote US",
            "Remote USA",
            "Remote, USA",
            "Remote, United States",
            "United States Remote",
            "Remote U.S.",
            "Remote - USA",
            "Remote, USA",
        ],
        "mild_positive": ["Remote", "Hybrid", "Southeast", "Eastern Time", "EST"],
        "negative": [
            "Europe",
            "United Kingdom",
            "UK",
            "London",
            "Amsterdam",
            "Germany",
            "France",
            "Netherlands",
            "Ireland",
            "India",
            "Argentina",
            "Colombia",
            "Brazil",
            "Singapore",
            "Australia",
            "Canada",
            "Mexico",
        ],
        "unwanted_onsite": [
            "San Francisco",
            "New York",
            "Los Angeles",
            "Seattle",
            "Boston",
            "Redwood City",
            "Jersey City",
            "Tempe",
            "Dallas",
            "Tysons",
            "Philadelphia",
            "Washington D.C.",
            "Washington DC",
        ],
        "preferred_location_bonus": 35,
        "remote_us_bonus": 25,
        "mild_location_bonus": 5,
        "broad_us_bonus": 0,
        "unknown_location_penalty": 10,
        "unwanted_onsite_penalty": 45,
        "non_us_penalty": 70,
    },
    "negative_keywords": ["unpaid", "internship", "junior", "entry level", "commission only"],
    "minimum_salary": 120000,
}


def test_strong_data_scientist_job_scores_high() -> None:
    job = Job(
        source="test",
        source_job_id="1",
        job_url="https://example.com/1",
        title="Senior Data Scientist",
        company="Bank",
        location="Remote - Atlanta, Georgia",
        remote_type="Remote",
        description_text=(
            "Python SQL Machine Learning Statistics Data Analysis AWS Snowflake Tableau "
            "Banking Risk Modeling Financial Services"
        ),
        compensation_text="$145,000 - $175,000 per year",
        posted_date="",
    )
    assert score_job(job, PROFILE).score >= 85


def test_irrelevant_commission_sales_job_scores_low() -> None:
    job = Job(
        source="test",
        source_job_id="2",
        job_url="https://example.com/2",
        title="Entry Level Sales Representative",
        company="Sales Co",
        location="Tampa, Florida",
        remote_type="Onsite",
        description_text="Junior outbound sales. Unpaid training. Commission only.",
        compensation_text="commission only",
        posted_date="",
    )
    assert score_job(job, PROFILE).score <= 20


def test_negative_keywords_reduce_score() -> None:
    good_job = Job(
        source="test",
        source_job_id="3",
        job_url="https://example.com/3",
        title="Senior Data Scientist",
        company="Bank",
        location="Remote",
        remote_type="Remote",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking",
        compensation_text="$140,000",
        posted_date="",
    )
    bad_job = Job(
        source="test",
        source_job_id="4",
        job_url="https://example.com/4",
        title="Senior Data Scientist Internship",
        company="Bank",
        location="Remote",
        remote_type="Remote",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking unpaid internship",
        compensation_text="$140,000",
        posted_date="",
    )
    assert score_job(bad_job, PROFILE).score < score_job(good_job, PROFILE).score


def test_remote_us_data_scientist_job_scores_high() -> None:
    job = _job(
        title="Senior Data Scientist",
        location="Remote US",
        remote_type="Remote",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS Snowflake",
        compensation_text="$150,000",
    )
    result = score_job(job, PROFILE)
    assert result.score >= 85
    assert any("Remote US location" in reason for reason in result.positive_reasons)


def test_atlanta_data_engineer_job_scores_high() -> None:
    job = _job(
        title="Data Engineer",
        location="Atlanta, GA",
        remote_type="Hybrid",
        description_text="Python SQL Machine Learning Statistics Data Analysis Financial Services Airflow",
        compensation_text="$140,000",
    )
    result = score_job(job, PROFILE)
    assert result.score >= 80
    assert any("Georgia preferred location" in reason for reason in result.positive_reasons)


def test_europe_only_data_scientist_job_is_strongly_penalized() -> None:
    job = _job(
        title="Senior Data Scientist",
        location="Remote - Europe only",
        remote_type="Remote",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
        compensation_text="$150,000",
    )
    result = score_job(job, PROFILE)
    assert result.score < 50
    assert any("Non-US" in reason for reason in result.negative_reasons)


def test_india_only_data_analyst_job_is_strongly_penalized() -> None:
    job = _job(
        title="Data Scientist",
        location="India only",
        remote_type="Onsite",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking Tableau",
        compensation_text="$150,000",
    )
    result = score_job(job, PROFILE)
    assert result.score < 50
    assert any("Non-US" in reason for reason in result.negative_reasons)


def test_san_francisco_onsite_only_job_is_penalized() -> None:
    job = _job(
        title="Senior Data Scientist",
        location="San Francisco, CA",
        remote_type="Onsite",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
        compensation_text="$150,000",
    )
    result = score_job(job, PROFILE)
    assert result.score < 70
    assert any("Unwanted onsite-only" in reason for reason in result.negative_reasons)


def test_unknown_location_gets_small_penalty_but_not_excluded() -> None:
    job = _job(
        title="Senior Data Scientist",
        location="",
        remote_type="",
        description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
        compensation_text="$150,000",
    )
    result = score_job(job, PROFILE)
    assert result.score >= 60
    assert any("Unknown location penalty" in reason for reason in result.negative_reasons)


def test_atlanta_data_scientist_scores_very_high() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Atlanta, Georgia",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS Snowflake",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score >= 90
    assert any("Georgia preferred location" in reason for reason in result.positive_reasons)


def test_alpharetta_data_analyst_scores_very_high() -> None:
    result = score_job(
        _job(
            title="Data Scientist",
            location="Alpharetta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Financial Services Tableau",
            compensation_text="$135,000",
        ),
        PROFILE,
    )
    assert result.score >= 90
    assert any("Georgia preferred location" in reason for reason in result.positive_reasons)


def test_georgia_data_engineer_scores_very_high() -> None:
    result = score_job(
        _job(
            title="Data Engineer",
            location="Georgia",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking Airflow",
            compensation_text="$140,000",
        ),
        PROFILE,
    )
    assert result.score >= 90
    assert any("Georgia preferred location" in reason for reason in result.positive_reasons)


def test_remote_usa_data_scientist_scores_high() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Remote USA",
            remote_type="Remote",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score >= 85
    assert any("Remote US location" in reason for reason in result.positive_reasons)


def test_united_states_only_location_gets_no_preferred_bonus() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="United States",
            remote_type="",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert not any("Georgia preferred location" in reason for reason in result.positive_reasons)
    assert not any("Remote US location" in reason for reason in result.positive_reasons)


def test_new_york_onsite_data_scientist_is_penalized() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="New York, New York, United States",
            remote_type="Onsite",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 65
    assert any("Unwanted onsite-only" in reason for reason in result.negative_reasons)


def test_los_angeles_onsite_data_scientist_is_penalized() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Los Angeles, California, United States",
            remote_type="Onsite",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 65
    assert any("Unwanted onsite-only" in reason for reason in result.negative_reasons)


def test_amsterdam_data_scientist_is_strongly_penalized() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Amsterdam",
            remote_type="Onsite",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 45
    assert any("Non-US" in reason for reason in result.negative_reasons)


def test_argentina_data_scientist_is_strongly_penalized() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Argentina",
            remote_type="Remote",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 45
    assert any("Non-US" in reason for reason in result.negative_reasons)


def test_columbus_and_ohio_are_not_preferred_anymore() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Columbus, Ohio",
            remote_type="Onsite",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert not any("Georgia preferred location" in reason for reason in result.positive_reasons)
    assert not any("Remote US location" in reason for reason in result.positive_reasons)


def test_san_francisco_or_remote_us_is_acceptable_but_lower_than_atlanta() -> None:
    remote_sf = score_job(
        _job(
            title="Senior Data Scientist",
            location="San Francisco or Remote U.S.",
            remote_type="Remote",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    atlanta = score_job(
        _job(
            title="Senior Data Scientist",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert remote_sf.score >= 80
    assert remote_sf.score < atlanta.score
    assert not any("Unwanted onsite-only" in reason for reason in remote_sf.negative_reasons)


def test_senior_data_scientist_role_scores_high() -> None:
    result = score_job(
        _job(
            title="Senior Data Scientist",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score >= 90
    assert any("Individual contributor data role" in reason for reason in result.positive_reasons)


def test_data_engineer_role_scores_high() -> None:
    result = score_job(
        _job(
            title="Data Engineer",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Financial Services Airflow",
            compensation_text="$140,000",
        ),
        PROFILE,
    )
    assert result.score >= 90
    assert any("Individual contributor data role" in reason for reason in result.positive_reasons)


def test_data_analyst_role_scores_high() -> None:
    result = score_job(
        _job(
            title="Data Analyst",
            location="Alpharetta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Statistics Data Analysis Banking Tableau",
            compensation_text="$125,000",
        ),
        PROFILE,
    )
    assert result.score >= 85
    assert any("Individual contributor data role" in reason for reason in result.positive_reasons)


def test_machine_learning_engineer_role_scores_high() -> None:
    result = score_job(
        _job(
            title="Machine Learning Engineer",
            location="Remote USA",
            remote_type="Remote",
            description_text="Python SQL Machine Learning Statistics Data Analysis Financial Services AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score >= 85
    assert any("Individual contributor data role" in reason for reason in result.positive_reasons)


def test_manager_data_analytics_is_penalized() -> None:
    result = score_job(
        _job(
            title="Manager, Data Analytics",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 60
    assert any("Management-track" in reason for reason in result.negative_reasons)


def test_data_engineering_manager_is_penalized() -> None:
    result = score_job(
        _job(
            title="Data Engineering Manager",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 60
    assert any("Management-track" in reason for reason in result.negative_reasons)


def test_director_role_is_penalized() -> None:
    result = score_job(
        _job(
            title="Director, Provider Operations",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Insurance AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 50
    assert any("Management-track" in reason for reason in result.negative_reasons)


def test_associate_director_role_is_penalized() -> None:
    result = score_job(
        _job(
            title="Associate Director, Analytics",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Insurance AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 60
    assert any("Management-track" in reason for reason in result.negative_reasons)


def test_product_manager_role_is_penalized() -> None:
    result = score_job(
        _job(
            title="Product Manager",
            location="Remote USA",
            remote_type="Remote",
            description_text="Python SQL Machine Learning Statistics Data Analysis Financial Services AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 60
    assert any("Product/program/project manager" in reason for reason in result.negative_reasons)


def test_senior_data_product_manager_is_penalized() -> None:
    result = score_job(
        _job(
            title="Senior Data Product Manager",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 60
    assert any("Product/program/project manager" in reason for reason in result.negative_reasons)


def test_staff_machine_learning_engineer_is_acceptable() -> None:
    result = score_job(
        _job(
            title="Staff Machine Learning Engineer",
            location="Remote USA",
            remote_type="Remote",
            description_text="Python SQL Machine Learning Statistics Data Analysis Financial Services AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score >= 85
    assert any("Individual contributor data role" in reason for reason in result.positive_reasons)


def test_generic_software_engineer_is_penalized() -> None:
    result = score_job(
        _job(
            title="Software Engineer",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL AWS Spark Airflow",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 60
    assert any("Non-IC data role" in reason for reason in result.negative_reasons)


def test_security_engineering_manager_is_penalized() -> None:
    result = score_job(
        _job(
            title="Security Engineering Manager",
            location="Atlanta, GA",
            remote_type="Hybrid",
            description_text="Python SQL Machine Learning Statistics Data Analysis Banking AWS",
            compensation_text="$150,000",
        ),
        PROFILE,
    )
    assert result.score < 50
    assert any("Management-track" in reason for reason in result.negative_reasons)


def _job(
    title: str,
    location: str,
    remote_type: str,
    description_text: str,
    compensation_text: str,
) -> Job:
    return Job(
        source="test",
        source_job_id=title,
        job_url=f"https://example.com/{title.replace(' ', '-').lower()}",
        title=title,
        company="Example Co",
        location=location,
        remote_type=remote_type,
        description_text=description_text,
        compensation_text=compensation_text,
        posted_date="",
    )
