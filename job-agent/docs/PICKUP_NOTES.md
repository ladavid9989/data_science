# Pickup Notes

All project Markdown should be written in English for compactness, searchability, and token efficiency.

This file is a chronological development log. Older entries may describe earlier constraints or missing features that were later implemented. When entries conflict, use the newest dated section and the current README / architecture docs as the source of truth.

## 2026-06-30

### Work Completed

- Built the Phase 1 local-first job matching MVP.
- Added collectors for local files, Greenhouse, Lever, and Ashby.
- Added normalization into a shared `Job` dataclass.
- Added SQLite persistence for jobs, scores, and email report status.
- Added ranked Markdown reporting.
- Added optional SMTP email report delivery.
- Configured execution in the `newenv_01` Conda environment.
- Added deterministic scoring for skills, industry, salary, seniority, negative keywords, location, and role type.
- Tightened location scoring toward Georgia and Remote US:
  - Strong preference: Atlanta, Alpharetta, Georgia, GA.
  - Secondary preference: Remote USA / Remote U.S. / Remote, United States.
  - Neutral: broad United States-only locations.
  - Penalty: non-target international locations and unwanted onsite-only US cities.
- Tightened role scoring toward individual contributor data roles:
  - Positive: Data Scientist, Data Analyst, Data Engineer, Analytics Engineer, BI Analyst, Machine Learning Engineer, Applied Scientist, Decision Scientist, Risk Analyst, Quantitative Analyst.
  - Penalty: Manager, Director, Associate Director, Assistant Director, VP, Head of, Product Manager, Program Manager, Project Manager, Product Owner, Engineering Manager.
- Added tests for normalizer, scoring, Georgia / Remote US location logic, non-US penalties, unwanted onsite penalties, and IC-vs-management role logic.

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
34 passed
```

Run the pipeline:

```powershell
python run.py run-all
```

Check the report:

```text
output/ranked_jobs.md
```

### Observed Report Quality

The latest report is much better than the initial report:

- Top jobs are mostly IC data roles.
- Management-track jobs dropped sharply.
- Georgia and Remote US jobs are prioritized.
- The source summary is useful for identifying noisy sources.

Remaining noise still exists:

- Broad `United States` roles can rank high when role and skill fit are strong.
- `Remote, North America` can still appear via mild remote scoring.
- Mixed locations such as `San Francisco, CA or Remote (U.S.)` are currently treated as acceptable because Remote US is present.
- Some non-target locations may still leak if the source location text is ambiguous or if the unwanted location term is not yet in the negative list.
- Some source boards are broad and produce many irrelevant roles.

### Lessons Learned

- Location must be scored primarily from `job.location`, not full job descriptions.
- `United States` alone should not mean preferred.
- Remote US should be positive, but lower than Georgia.
- Georgia should outrank Remote US when role and skill fit are similar.
- Role type must be title-first; descriptions mention many skills and can make non-IC roles look relevant.
- Management and PM roles need final score caps, not just penalties, because location and skill bonuses can otherwise lift them above the report threshold.
- Source quality matters. Some sources should eventually be pruned or weighted down.
- Job descriptions are essential long-term data, even if early scoring remains deterministic. Similar titles such as Data Scientist or Data Engineer can represent very different roles, and future feedback learning, resume tailoring, and cover letter drafting all need the full posting context.

### Next Work

Recommended next steps:

1. Add a strict location gate before report display:
   - Keep Georgia.
   - Keep explicit Remote US.
   - Optionally keep broad United States only if score is extremely high and source is trusted.
   - Hide `Remote North America` unless explicitly allowed.
2. Add source quality controls:
   - Per-source allowlist / blocklist.
   - Per-source score adjustment.
   - Hide sources with low average score or low above-threshold rate.
3. Improve location parsing:
   - Parse mixed locations into tags such as `georgia`, `remote_us`, `broad_us`, `non_us`, `unwanted_onsite`.
   - Store these tags in SQLite or score metadata.
4. Improve report diagnostics:
   - Add location category to each report item.
   - Add role category to each report item.
   - Add a short reason why each job passed the report threshold.
5. Improve description handling:
   - Keep full descriptions in SQLite as first-class data.
   - Clean HTML more consistently before scoring, reporting, and future LLM use.
   - Add a short description preview or responsibilities summary to the report.
   - Track whether each source provides full descriptions or only listing-level metadata.
6. Add feedback fields:
   - liked
   - disliked
   - applied
   - hidden
   - notes
7. Add email feedback workflow later:
   - Send report email.
   - Include like / dislike / applied links or reply commands.
   - Store feedback in SQLite.
   - Use feedback to adjust future ranking.
8. Add local LLM support later, likely through Ollama:
   - Summarize full descriptions.
   - Extract responsibilities, requirements, tools, seniority, and domain signals.
   - Compare job descriptions against the user's resume.
   - Use explicit user reactions to improve future fit explanations and ranking.
   - Draft resume and cover letter tailoring suggestions for user approval.

### Version 2.0 Candidate: Job Alert Email Ingestion

Future V2 architecture:

```text
LinkedIn / Indeed / Google Jobs job alert
        v
Gmail alert arrives
        v
job-agent reads email subject/body/link
        v
SQLite storage
        v
location / role / skill scoring
        v
ranked report generation
```

Proposed V2 flow:

1. Receive LinkedIn, Indeed, and Google Jobs job alert emails.
2. Let `job-agent` read email subject, body, and links.
3. Use Greenhouse, Lever, and Ashby only as supplemental seed-list sources for companies of interest.
4. Store all postings in SQLite.
5. Score by location, role type, and skills.
6. Send the ranked report by email.
7. Improve ranking from user feedback: like, dislike, and applied.

Description quality is a prerequisite for this flow. Email-ingested alerts may contain only summary metadata and links, so a later enrichment step may need to follow approved links or otherwise recover full posting text before scoring, learning, resume tuning, or cover letter generation.

### Do Not Do Yet

- Do not add LLM scoring yet, but preserve the design assumption that local Ollama-style LLM support will likely become important for description summarization, fit reasoning, and resume / cover letter tailoring.
- Do not add feedback learning yet.
- Do not scrape LinkedIn, Indeed, Google Jobs, Workday, or login/CAPTCHA-protected sites directly.
- Do not add automatic application submission.
- Do not build a dashboard until the ranking and feedback loop are stable.

## 2026-07-02

### Work Completed

- Implemented a strict report-level location gate.
- Kept all jobs in SQLite; the gate only controls what appears in `output/ranked_jobs.md`.
- Added `reporting.strict_location_gate: true`.
- Added `reporting.broad_us_min_score_to_show: 95`.
- Added reporter tests for:
  - Georgia jobs passing the gate.
  - explicit Remote US jobs passing the gate.
  - broad `United States` jobs below the exceptional threshold being hidden.
  - exceptional broad `United States` jobs being allowed.
  - `Remote, North America` and `Toronto` jobs being hidden.
- Updated the report header with:
  - `Strict location gate`
  - `Jobs hidden by location gate`
- Updated source summary with:
  - `Above threshold`
  - `Shown after gate`

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
38 passed
```

Latest pipeline run:

```powershell
python run.py run-all
```

Latest report result:

```text
Total jobs processed: 3448
Jobs shown: 18
Minimum score shown: 60
Strict location gate: enabled
Jobs hidden by location gate: 20
```

### Lessons Learned

- Report filtering is safer than deleting or suppressing jobs at collection time.
- Broad `United States` jobs can still score high, but most should not appear in the daily report.
- `Remote, North America` is too broad for the current target and should stay hidden unless explicitly allowed later.
- Source summary needs both score-threshold counts and final shown counts; otherwise source quality looks better than the final report experience.

### Next Work

Recommended next steps:

1. Add a location category field to report rows:
   - `georgia`
   - `remote_us`
   - `broad_us_exception`
   - `hidden_non_target`
2. Add a role category field to report rows:
   - `ic_data`
   - `management`
   - `pm`
   - `generic_engineering`
3. Consider lowering or removing the broad US exception after reviewing whether any broad-US-only jobs are actually useful.
4. Add source-level controls:
   - source allowlist
   - source blocklist
   - source score adjustment
5. Add feedback fields and a first manual feedback command before implementing email feedback.

### Product Direction Update

The project direction changed from email-first to local dashboard-first.

Preferred near-term architecture:

```text
Local Streamlit dashboard
        v
Run / refresh job pipeline on demand
        v
Show ranked jobs
        v
User clicks like / dislike / hide / save / applied
        v
Feedback saved locally
        v
Ranking improves over time
        v
Later: Ollama reads JD + resume
        v
Resume tailoring / fit explanation / cover letter draft
```

Local-first remains the right path for now because it preserves privacy, works naturally with SQLite and Ollama, and avoids hosted multi-user complexity too early.

## 2026-07-02 Dashboard MVP

### Work Completed

- Added `job_feedback` table to SQLite.
- Added feedback persistence helpers:
  - `save_feedback`
  - `get_latest_feedback_by_job`
- Added `streamlit_app.py` as the first local dashboard.
- Added dashboard actions:
  - like
  - dislike
  - hide
  - save
  - applied
- Added dashboard controls:
  - refresh pipeline
  - minimum score slider
  - show hidden jobs
  - source text filter
  - location text filter
- Added a feedback test in `tests/test_memory.py`.

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
39 passed
```

Run dashboard:

```powershell
streamlit run streamlit_app.py
```

If needed:

```powershell
conda run -n newenv_01 streamlit run streamlit_app.py
```

### Next Work

1. Make feedback affect ranking:
   - hide removes jobs from dashboard already.
   - dislike should eventually penalize similar roles/sources/locations.
   - like/save/applied should eventually boost similar jobs.
2. Add feedback summary to dashboard.
3. Add role and location category chips.
4. Add source quality controls.
5. Add resume input after feedback loop is stable.

### Dashboard Display Fix

- Cleaned HTML job descriptions before showing them in the dashboard.
- Changed dashboard reasons from comma-separated text into bullet lists.
- Added `clean_html_to_text` as a shared utility.
- Added a test to verify HTML descriptions become human-readable text.

Latest known test result after this fix:

```text
40 passed
```

### Feedback-Aware Ranking

- Added `src/feedback.py`.
- Added cumulative deterministic feedback adjustment for dashboard ranking.
- Preserved original model score as `base_score`.
- Added adjusted display score as `score`.
- Added `feedback_adjustment` and `feedback_reasons`.
- Added `get_feedback_events` to load all historical feedback from SQLite.
- Added a dislike reason dialog in the dashboard.
- `hide` drops the exact job's effective score to zero and hides it by default.
- `like`, `save`, and `applied` add positive direct and similarity signals.
- `dislike` and `hide` add negative direct and similarity signals.
- Dislike notes are tokenized and can penalize future jobs whose title, company, location, or description matches those note patterns.

Latest known test result after this fix:

```text
44 passed
```

Important caveat:

- This is still deterministic feedback weighting, not machine learning.
- The next useful step is tuning the feedback weights after several real like/dislike/hide/save/applied actions.

### Dashboard Performance Pass

- Added cached dashboard data loading with `st.cache_data`.
- Added `get_feedback_version` so the dashboard cache invalidates when new feedback is saved.
- Added a `Jobs to show` slider, defaulting to 10 jobs.
- Changed reasons and description from an always-rendered expander to an explicit `Show reasons and description` toggle.
- Description HTML cleanup now runs only when the user opens details for a specific job.
- Feedback adjustment now runs only on prefiltered display candidates instead of all collected jobs.

Why this matters:

- Streamlit reruns the script after most interactions.
- Rendering and cleaning every job description on every click made the dashboard feel heavy.
- The dashboard should now feel lighter during like/dislike/hide/save/applied interactions.

### Resume Upload MVP

- Added DOCX/PDF resume support with `python-docx` and `pypdf`.
- Added `src/resume.py`.
- Added `resume_versions` SQLite table.
- Added active resume metadata:
  - original filename
  - stored original path
  - extracted text path
  - file hash
  - uploaded timestamp
  - active flag
- Added dashboard Resume tab.
- Added resume upload for `.docx`, `.pdf`, `.txt`, and `.md`.
- Added original uploaded resume download from the dashboard.
- Added extracted text preview.
- Added resume version table in the dashboard.
- Added lightweight keyword-based `Resume fit` per visible job.
- Added tests for DOCX extraction, active resume version storage, and resume fit scoring.

Latest known test result after this feature:

```text
47 passed
```

Important caveat:

- Resume fit is currently keyword overlap only.
- It does not yet use LLM reasoning, semantic matching, or resume bullet tailoring.
- Resume fit now affects ranking when `resume_scoring.enabled` is true.
- The next useful step is tuning broad terms such as `excel` and deciding whether some resume terms should be weighted lower than core skills such as Python, SQL, ML, statistics, cloud, and domain terms.

## 2026-07-02 Freshness Layer

### Work Completed

- Added `src/freshness.py`.
- Added source posted-date normalization for ISO timestamps, date strings, and epoch milliseconds.
- Normalized Lever `createdAt` values into ISO dates.
- Added freshness categories:
  - `fresh`
  - `recent`
  - `aging`
  - `stale`
  - `unknown_recently_seen`
  - `unknown`
- Added `reporting.hide_stale_jobs: true`.
- Added report-level stale filtering.
- Added per-job `Posted` lines to `output/ranked_jobs.md`.
- Added explicit freshness provenance to report and dashboard display:
  - `source: Greenhouse updated_at`
  - `source: Lever createdAt`
  - `source: Ashby publishedDate`
  - `source: local first_seen fallback`
- Added `posted_date_source` to SQLite jobs and automatic migration for existing databases.
- Added source summary fields:
  - posted date coverage
  - stale count
  - unknown-date count
- Added dashboard freshness captions on job cards.
- Added optional `serpapi_google_jobs` collector support. It requires `SERPAPI_API_KEY` and is not enabled by default.
- Added tests for freshness classification, source date quality, Lever epoch milliseconds, SerpApi normalization, and stale report filtering.

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
55 passed
```

Latest report regeneration:

```powershell
python run.py report
```

Latest report result:

```text
Total jobs processed: 3450
Jobs shown: 15
Strict location gate: enabled
Jobs hidden by location gate: 21
Stale freshness gate: enabled
Jobs hidden by freshness gate: 3
```

Current active resume:

```text
uploaded_resume.docx
uploaded_at: example timestamp
```

## 2026-07-02 Resume-Aware Scoring

### Work Completed

- Added active resume fit into pipeline scoring.
- Added `resume_scoring` settings in `config/config.yaml`.
- Strong resume keyword overlap can add a small bonus.
- Moderate resume keyword overlap can add a smaller bonus.
- Weak resume keyword overlap can add a small penalty.
- Resume reasons are written into report positive/negative reasons.
- Dashboard still shows `Resume fit` per visible job.

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
59 passed
```

Latest pipeline run:

```text
Collected and stored 3357 jobs
Scored 3450 jobs
Report written to output/ranked_jobs.md
```

### Lessons Learned

- Resume fit is now useful enough to affect ranking, but it is still keyword overlap.
- Broad terms like `excel` and `analytics` can inflate fit for some jobs.
- The next ranking improvement should separate core skills, domain terms, tools, and generic terms into different weights.

## 2026-07-02 Hermes Tailor Resume MVP

### Work Completed

- Installed Ollama on Windows through `winget`.
- Pulled local model:
  - `qwen2.5:7b`
- Verified local Ollama API:
  - `http://127.0.0.1:11434`
- Verified test generation:
  - `local llm ready`
- Added `src/llm.py`:
  - local Ollama client
  - timeout handling
  - clear `OllamaError`
- Added `src/tailoring.py`:
  - Hermes prompt
  - JD + active resume + user notes input
  - truthfulness constraints
  - Fit Analysis section
  - Tailored Resume section
  - Markdown output
  - DOCX output
- Added `resume_tailoring_runs` table.
- Added dashboard `Tailor Resume` button on each job card.
- Added a guidance dialog for user instructions before generation.
- Added DOCX and Markdown download buttons after generation.
- Added tests for tailoring output files and DB persistence.

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
60 passed
```

### Design Decision

Hermes is not a separate autonomous agent yet. It is currently a local LLM-assisted capability inside the dashboard, triggered only by user action. This keeps the system local-first, auditable, and easier to control before adding more agentic behavior.

### Next Work

1. Add generated resume history to the Resume tab.
2. Add a second-pass refinement UI:
   - user correction notes
   - regenerate version 2
   - compare version 1 vs version 2
3. Add stronger guardrails:
   - detect claims not present in the source resume
   - show "do not overclaim" warnings
4. Improve DOCX formatting and preserve more structure from the original resume.
5. Add semantic fit scoring as a separate visible score, not only resume tailoring.

### Tailoring Quality Fix

- Tightened Hermes output requirements so `Fit Analysis` includes:
  - `Fit Verdict`
  - `Evidence Map`
  - `Gaps / Do Not Overclaim`
  - `Recommended Emphasis`
- Changed dashboard rendering so Fit Analysis is shown as Markdown, including tables.
- Added cleanup for model output:
  - remove ```markdown fences
  - remove closing code fences
  - remove horizontal rules such as `---`
- Added tests to prevent code fences and horizontal rules from leaking into generated resume files.

Latest known test result after this fix:

```text
61 passed
```

### UX Issue To Pick Up Next

- Downloading a generated tailored resume from the Streamlit dialog can make the dialog disappear or reset.
- This is a poor review workflow because the user wants to download the DOCX while keeping the Evidence Map visible for careful comparison.
- Next fix should persist the latest tailoring result in `st.session_state` and/or render the result outside the dialog after generation.
- Desired behavior:
  - click `Tailor Resume`
  - generate Fit Analysis and tailored resume
  - download DOCX/Markdown
  - keep Fit Analysis, Evidence Map, and download buttons visible
  - allow a second-pass instruction without losing the first result

## 2026-07-02 End-of-Day Product Notes

### Work Completed Today

- Tightened Georgia / Remote US ranking and report display.
- Added freshness layer:
  - source posted date parsing
  - `first_seen_at` fallback
  - explicit date provenance
  - stale report gate
  - source date coverage summary
- Added cumulative feedback-aware dashboard ranking:
  - like
  - dislike
  - hide
  - save
  - applied
  - dislike reason text
- Improved dashboard performance by limiting visible jobs and deferring description rendering.
- Added resume upload and version tracking:
  - DOCX/PDF/TXT/MD input
  - extracted text preview
  - original file download
  - active resume tracking
- Uploaded first real active resume:
  - first real DOCX resume
- Added resume-aware scoring:
  - active resume keyword overlap affects ranking
  - resume fit reasons are written into report reasons
- Installed local Ollama and pulled:
  - `qwen2.5:7b`
- Added Hermes `Tailor Resume` MVP:
  - user-triggered local LLM workflow
  - JD + active resume + user guidance
  - Fit Analysis
  - tailored Markdown and DOCX output
  - local run persistence
- Improved Hermes output quality:
  - Evidence Map
  - Gaps / Do Not Overclaim
  - Recommended Emphasis
  - cleanup for code fences and horizontal rules

### Current Verification

Run:

```powershell
conda activate newenv_01
cd path\to\job-agent
python -m pytest
```

Latest known result:

```text
61 passed
```

Run dashboard:

```powershell
streamlit run streamlit_app.py
```

### Product Reflection

- The initial local-first concept is now mostly represented in working form:
  - collect jobs
  - rank jobs
  - review in dashboard
  - capture feedback
  - upload resume
  - compare resume to JD
  - use local LLM to tailor resume drafts
- The biggest remaining issue appears to be data, not UI alone.
- Current sources were assembled pragmatically from accessible ATS boards, not from a complete market-wide job dataset.
- It is unclear whether current data coverage is enough for daily job search usefulness.
- Freshness matters because old postings can be low-value even when the role fit looks strong.
- Source expansion should become a major next theme.

### Data Strategy Questions

- How can each user get enough relevant postings for their own role and geography?
- Can job alerts from LinkedIn, Indeed, and Google Jobs become the main user-specific data feed?
- Should Gmail alert ingestion become the practical workaround for protected platforms?
- Should SerpApi Google Jobs be used optionally despite API cost and quota limits?
- Should each source have quality metrics:
  - freshness coverage
  - description completeness
  - above-threshold rate
  - shown-after-gate rate
  - user feedback rate
- Should source configuration become user-facing instead of manually edited YAML?

### Hosted / Shareable Link Questions

- A shareable hosted dashboard may be valuable for a broader audience, but it changes the architecture.
- Local dashboard advantages:
  - private resume storage
  - local SQLite
  - local Ollama
  - no LLM API cost
  - no multi-user security burden
- Hosted dashboard challenges:
  - authentication
  - per-user resumes
  - per-user job source configuration
  - per-user geography and role tuning
  - remote LLM/API cost
  - abuse/overuse controls
  - data retention and privacy
- Given the high tuning needed even for Atlanta data roles, a hosted version should probably start as a configurable personal assistant, not a general-purpose job board.

### Next Pickup Priorities

1. Fix Tailor Resume review UX:
   - keep generated result visible after download
   - keep Evidence Map visible
   - support second-pass refinement without losing version 1
2. Add generated resume history to the Resume tab:
   - job title
   - company
   - model
   - created time
   - download DOCX
   - open Fit Analysis
3. Improve Hermes evidence quality:
   - stricter evidence map
   - direct vs adjacent evidence labels
   - stronger "do not overclaim" warnings
4. Improve data coverage:
   - evaluate Gmail job alert ingestion
   - evaluate SerpApi cost/quality
   - evaluate JSON-LD `JobPosting` enrichment
   - add source quality dashboard
5. Improve resume scoring:
   - separate core skills, domain terms, tools, and generic terms
   - reduce overweighting of broad terms like `excel` and `analytics`
6. Think through hosted architecture:
   - what remains local
   - what can be shared
   - where LLM calls run
   - how to control API cost and user-specific data setup

### Lessons Learned

- Original posted date is often missing from ATS data.
- `first_seen_at` is useful provenance, but it is not the same as public posting date.
- Unknown-date jobs should not be deleted automatically; they should be labeled and source quality should be tracked.
- Stale jobs can be hidden safely at report display time while keeping raw jobs in SQLite.
- JobSpy-style `hours_old`, Google JobPosting `datePosted` / `validThrough`, and SerpApi Google Jobs date filters all point to the same practical pattern: keep freshness provenance, prefer source posted dates, use first-seen only as a fallback, and surface date coverage by source.

### Next Work

1. Add optional source-level freshness weighting:
   - Penalize sources with low posted-date coverage.
   - Prefer sources with reliable `posted_date`.
2. Add a dashboard filter for freshness category:
   - fresh
   - recent
   - aging
   - unknown
3. Add JSON-LD `JobPosting` enrichment for selected job URLs:
   - parse `datePosted`
   - parse `validThrough`
   - keep provenance for extracted dates
4. Decide whether to enable SerpApi Google Jobs after confirming cost, quota, and API key setup.
5. Consider a hard stale threshold for dashboard display after reviewing whether any older jobs are still valuable.
