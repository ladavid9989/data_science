# User Guide

This guide explains how to clone, configure, run, and use `job-agent`.

## 1. Clone The Repository

Clone the repository:

```powershell
git clone https://github.com/ladavid9989/data_science.git
cd data_science
git checkout jobAgent
```

If the app is inside a subfolder, move into it:

```powershell
cd job-agent
```

Forking means creating your own copy on GitHub. Cloning means downloading a repository to your computer. Most users can start by cloning.

## 2. Create Python Environment

Conda example:

```powershell
conda create -n job-agent python=3.11 -y
conda activate job-agent
python -m pip install -r requirements.txt
```

Existing environment example:

```powershell
conda activate your-env-name
python -m pip install -r requirements.txt
```

## 3. Install Ollama For Local LLM

Install Ollama:

```powershell
winget install --id Ollama.Ollama --source winget
```

Download the default model:

```powershell
ollama pull qwen2.5:7b
```

Verify:

```powershell
ollama list
```

If you do not want LLM resume tailoring, set this in [config/config.yaml](../config/config.yaml):

```yaml
llm:
  enabled: false

tailoring:
  enabled: false
```

## 4. Configure Your Profile

Edit [config/user_profile.yaml](../config/user_profile.yaml).

Important sections:

```yaml
target_titles:
  - Data Scientist
  - Data Analyst

required_skills:
  - Python
  - SQL

preferred_skills:
  - AWS
  - Snowflake

location_preferences:
  strong_positive:
    - Atlanta
    - Georgia
  remote_positive:
    - Remote US
    - Remote, United States
  negative:
    - Europe
    - India
```

For a different user, change:

- target titles
- required skills
- preferred skills
- industries
- location preferences
- salary threshold
- negative keywords

### How To Customize Your Job Search Target

The current dashboard does not yet provide a form for editing the target profile. For now, customize your search target by editing YAML files directly.

Use this file for the user's preferences:

```text
config/user_profile.yaml
```

Use this file for general app thresholds:

```text
config/config.yaml
```

Use this file for job boards and sources:

```text
config/sources.yaml
```

After changing YAML, rerun the pipeline:

```powershell
python run.py run-all
```

Then refresh the dashboard:

```powershell
streamlit run streamlit_app.py
```

If the dashboard is already open, click `Refresh pipeline`.

#### Example: Emphasize Data Engineering More

Add or move engineering roles higher in `target_titles` and `role_preferences.individual_contributor_positive`:

```yaml
target_titles:
  - Senior Data Engineer
  - Data Engineer
  - Analytics Engineer
  - Machine Learning Engineer
  - Data Scientist
  - Data Analyst

role_preferences:
  individual_contributor_positive:
    - Data Engineer
    - Senior Data Engineer
    - Analytics Engineer
    - Machine Learning Engineer
    - Data Scientist
```

Then add engineering tools to `required_skills` or `preferred_skills`:

```yaml
required_skills:
  - Python
  - SQL
  - Data Engineering

preferred_skills:
  - Airflow
  - Spark
  - dbt
  - Snowflake
```

Use `required_skills` for skills that should strongly affect the score. Use `preferred_skills` for nice-to-have skills.

#### Example: Remove AWS From Preference

Remove `AWS` from `preferred_skills`:

```yaml
preferred_skills:
  - Snowflake
  - Tableau
  - Power BI
  - Spark
  - Airflow
```

If you want cloud skills to matter less overall, keep cloud tools in `preferred_skills`, not `required_skills`.

#### Example: Add Git As A Preferred Skill

Add `Git` or `GitHub` to `preferred_skills`:

```yaml
preferred_skills:
  - Snowflake
  - Tableau
  - Git
  - GitHub
```

If too many jobs mention Git generically, keep it as preferred rather than required.

#### Example: Remove Remote Preference

If you do not want remote jobs to receive a boost, remove remote terms from `remote_positive` and `mild_positive`:

```yaml
location_preferences:
  strong_positive:
    - Atlanta
    - Alpharetta
    - Georgia
    - GA

  remote_positive: []

  mild_positive:
    - Hybrid
    - Southeast
    - Eastern Time
```

You can also lower or zero out `remote_us_bonus`:

```yaml
location_preferences:
  remote_us_bonus: 0
```

#### Example: Change Target Location From Georgia To New York

Replace Georgia terms with New York terms:

```yaml
location_preferences:
  strong_positive:
    - New York
    - New York City
    - NYC
    - NY

  remote_positive:
    - Remote US
    - Remote USA
    - Remote, United States

  unwanted_onsite:
    - San Francisco
    - Los Angeles
    - Seattle
    - Boston

  preferred_location_bonus: 35
  remote_us_bonus: 25
  mild_location_bonus: 5
```

Then remove New York from `unwanted_onsite` if it is currently listed there.

Important: the current report location gate is still Georgia / Remote US oriented in code. If you fully switch geographies, update the location gate logic in `src/reporter.py` or temporarily disable it in `config/config.yaml`:

```yaml
reporting:
  strict_location_gate: false
```

This is a known limitation. A future dashboard settings page should generate these preferences without manual YAML edits.

#### Example: Add More Negative Locations

Add locations you do not want to `negative` or `unwanted_onsite`:

```yaml
location_preferences:
  negative:
    - Europe
    - India
    - Canada

  unwanted_onsite:
    - San Francisco
    - Los Angeles
    - Seattle
```

Use `negative` for non-target countries or regions. Use `unwanted_onsite` for US cities that are acceptable only when Remote US is also present.

#### Example: Change Salary Threshold

Edit:

```yaml
minimum_salary: 140000
```

Salary parsing is simple and can be noisy, so treat salary scoring as a weak signal.

#### Example: Adjust Report Strictness

Edit [config/config.yaml](../config/config.yaml):

```yaml
reporting:
  min_score_to_show: 60
  max_jobs_to_show: 50
```

Raise `min_score_to_show` to make the report stricter. Lower it to inspect more jobs.

#### Recommended Customization Workflow

1. Edit `config/user_profile.yaml`.
2. Run `python run.py run-all`.
3. Open the dashboard.
4. Review top jobs.
5. Use `Like`, `Dislike`, `Hide`, `Save`, and `Applied`.
6. Add dislike reasons when possible.
7. Repeat after tuning role, skill, and location settings.

Manual YAML tuning is the current MVP approach. The long-term product direction is to move this into a dashboard settings UI.

## 5. Configure Job Sources

Edit [config/sources.yaml](../config/sources.yaml).

Supported source types:

```yaml
- name: "Example Greenhouse"
  type: "greenhouse"
  board_token: "example"

- name: "Example Lever"
  type: "lever"
  company: "example"

- name: "Example Ashby"
  type: "ashby"
  board_name: "example"

- name: "Local Sample Jobs"
  type: "local_files"
  path: "data/sample_jobs"
```

Optional SerpApi Google Jobs:

```yaml
- name: "SerpApi Google Jobs"
  type: "serpapi_google_jobs"
  query: "data scientist Atlanta GA"
  location: "Atlanta, Georgia, United States"
```

Set `SERPAPI_API_KEY` before using SerpApi.

Protected platforms such as LinkedIn, Indeed, Workday, login-gated sites, and CAPTCHA-protected sites are not scraped directly.

## 6. Run Tests

Always run tests from the project folder:

```powershell
python -m pytest
```

Do not run `python -m pytest` from your home folder. Pytest will search your whole user directory and may fail on system folders.

## 7. Run The Pipeline

Run all steps:

```powershell
python run.py run-all
```

Or run steps separately:

```powershell
python run.py collect
python run.py score
python run.py report
```

The Markdown report is written to:

```text
output/ranked_jobs.md
```

## 8. Open The Dashboard

```powershell
streamlit run streamlit_app.py
```

Open the URL shown by Streamlit.

Use the dashboard to:

1. Click `Refresh pipeline`.
2. Review ranked jobs.
3. Open job postings.
4. Like, dislike, hide, save, or mark jobs as applied.
5. Upload your resume in the Resume tab.
6. Review `Resume fit`.
7. Click `Tailor Resume` for a job you want to apply to.
8. Add guidance for Hermes.
9. Generate and download a tailored resume.

## 9. Upload Resume

Supported file types:

- `.docx`
- `.pdf`
- `.txt`
- `.md`

The original file and extracted text are stored locally under:

```text
data/profile/resumes/
```

This folder is ignored by git.

## 10. Tailor Resume With Hermes

The `Tailor Resume` button sends this data to local Ollama:

- job title
- company
- location
- job description
- active resume text
- your guidance notes

Hermes returns:

- Fit Verdict
- Evidence Map
- Gaps / Do Not Overclaim
- Recommended Emphasis
- tailored resume draft

Generated files are stored under:

```text
data/profile/tailored_resumes/
```

This folder is ignored by git.

## 11. Feedback Learning

Feedback is stored locally in SQLite.

Actions:

- `Like`
- `Dislike`
- `Hide`
- `Save`
- `Applied`

Dislike can include a reason. These reasons become future ranking signals.

Feedback clicks should be fast. The dashboard loads a lightweight job list and fetches full job descriptions only when the user opens details or clicks `Tailor Resume`.

## 12. Optional Email Report

Copy `.env.example` to `.env`:

```powershell
copy .env.example .env
```

Fill in SMTP variables:

```text
EMAIL_SMTP_HOST
EMAIL_SMTP_PORT
EMAIL_USERNAME
EMAIL_APP_PASSWORD
EMAIL_FROM
EMAIL_TO
```

Then run:

```powershell
python run.py email-report
```

If email is not configured, the pipeline still runs and writes the local report.

## 13. Common Problems

### Pytest Collects The Whole User Folder

Cause: running tests from the wrong folder.

Fix:

```powershell
cd path\to\job-agent
python -m pytest
```

### Ollama Is Not Responding

Check:

```powershell
ollama list
```

If needed, restart Ollama from the Windows Start Menu.

### Tailor Resume Button Is Disabled

Check:

- an active resume is uploaded
- `tailoring.enabled` is true
- Ollama is installed and running

### Generated Resume Dialog Closes After Download

This is a known Streamlit UX issue in the current MVP. The next improvement should keep the Evidence Map and download buttons visible after download.

## 14. What Not To Commit

Do not commit:

- `.env`
- SQLite databases
- uploaded resumes
- extracted resume text
- generated tailored resumes
- generated reports

These are local/private artifacts.
