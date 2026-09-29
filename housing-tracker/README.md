# Schoolside: school-zone housing tracker prototype

A runnable Streamlit prototype with persistent SQLite observations, historical filters, market charts, a listing explorer and per-property timelines. Development branch: `feature/school-housing-tracker`.

## What works

- Two independently selectable school zones: North Gwinnett High School and Johns Creek High School.
- Default USD 400k-700k display filter, optional all prices, construction year including unknowns, beds and baths.
- Daily active inventory and asking-price median from complete snapshots only, with gaps preserved.
- Property observations across price changes, contracts, disappearance, sale-price reporting delays and relistings.
- Append-only, atomic, idempotent snapshot imports; content checksums; timestamp-aware market dates in America/New_York.
- Backup/restore through SQLite's online backup API and exact normalized payload export for replay.
- Separate **fictional demonstration** and **actual imported observations**. They never share aggregates.

This is a local prototype. It does not yet implement unattended all-price collection, verified school membership, Supabase deployment, user authentication or cloud scheduling. A working ingestion contract and saved-sample importer are provided; a complete two-school Zillow collector is still an acquisition gate, not a completed feature.

## Run

Use Python 3.12 or newer. From this directory:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m tracker.cli seed-demo
.venv/Scripts/python.exe -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8502
```

Then open **http://127.0.0.1:8502**. On Windows, `./scripts/start-local.ps1` starts the installed environment and prints the URL. It also recognizes the project-local runtime prepared in this workspace; no global Python installation is required there. Press Ctrl+C in that terminal to stop the app.

On macOS/Linux, use `.venv/bin/python` in place of `.venv/Scripts/python.exe`.

By default, Windows data lives at `%LOCALAPPDATA%/SchoolHousingTracker/prototype.sqlite3`, outside this OneDrive/Git checkout. Other systems use `~/.local/share/SchoolHousingTracker/prototype.sqlite3`. Override with `HOUSING_DB_PATH` or CLI `--db PATH`. The dashboard and CLI must point to the same database. Do not put the active database in a synchronized OneDrive folder. This SQLite deployment is for a single local app; use PostgreSQL for independently hosted collectors and dashboards.

The app seeds deterministic fictional data on first launch if none exists. Reloading does not perform any website requests. The local server binds to loopback and has no authentication; do not expose it publicly without adding access control.

## Data modes

**Simulation:** 60 fictional snapshots spanning 2026-08-31 through 2026-09-29 across both schools. All addresses, coordinates, prices, assignments and status events are invented. Includes a price crossing from USD 710k to 690k, a missing property that never becomes sold by inference, delayed sale-price disclosure, a relisting, a failed run and a partial run. Complete/verified flags in this dataset are scenario inputs, not real geographic verification.

**Actual observations:** starts empty on a fresh clone. In the original workspace, import the previously saved bounded probe:

```powershell
python -m tracker.cli import-probe ../../probe-output
```

That import contains 41 North Gwinnett proximity-search observations from 2026-09-29, with construction years extracted from three matching saved detail pages. It is always marked partial: first page only, USD 400k-700k only, and unverified official school assignments. The source reported 71 results; that is not a verified school-zone inventory count. No actual Johns Creek observations or daily real-world histories have been acquired for this prototype. Real samples are private local data, not included in Git.

The importer validates the saved summary/CSV counts, source identity and timestamps, supports both tested year-built paths, and archives original files by SHA256 under the database's sibling `raw/` directory. Source history amounts are not converted into current-sale prices. New construction labels use the saved structured home status when available; otherwise status remains unknown.

## Add daily observations

```powershell
python -m tracker.cli import-json C:/private/snapshots/day-1.json C:/private/snapshots/day-2.json
```

The source adapter should emit one JSON snapshot per school and observation time. Importing the same bytes/JSON content again is a no-op. Different content at the same normalized school/dataset/observation timestamp is rejected so revisions cannot silently overwrite evidence. A failed attempt is a separate timestamp with `quality: failed` and empty `listings`; partial data uses `quality: partial`.

Example contract (illustrative placeholders; do not mark actual data complete until coverage is verified):

```json
{
  "schema_version": 1,
  "dataset": "observed",
  "school": "north_gwinnett",
  "scope": "houses_3bed_2bath_all_prices_v1",
  "observed_at": "2026-09-29T10:17:00Z",
  "quality": "partial",
  "reported_count": 1,
  "expected_unique_count": 1,
  "boundary_version": "unverified",
  "coverage": {
    "all_pages": false,
    "all_prices": true,
    "official_zone_verified": false,
    "query_validated": true
  },
  "source": "YOUR_SOURCE",
  "note": "Example only; acquisition and boundary verification still required",
  "listings": [{
    "property_id": "provider:EXAMPLE",
    "episode_id": "provider:EXAMPLE:unknown",
    "address": "EXAMPLE ONLY",
    "price": 650000,
    "bedrooms": 4,
    "bathrooms": 3,
    "square_feet": 2800,
    "year_built": 2000,
    "year_source": "detail page with matching property ID",
    "property_type": "SINGLE_FAMILY",
    "status": "active"
  }]
}
```

For complete publication the importer requires the agreed scope, all four coverage flags, a boundary version, unique property IDs and an expected unique count equal to the number of records. These are **source adapter attestations**, not independent boundary/pagination verification by this prototype. A future production adapter must supply evidence for them. `reported_count` can differ when documented spatial exclusions or lifecycle follow-ups exist; `expected_unique_count` is the reconciled total.

Use a confirmed provider listing ID in `episode_id` where available; otherwise use `:unknown`. The same-episode price-change table excludes unknown episodes. A sold amount requires explicit sold status, a nonfuture sold date, and episode evidence. Known past transactions are not equivalent to current listing closure.

The prototype stores the year present in each supplied observation; the future collector should carry forward previously verified stable attributes with their original provenance. It does not silently enrich old observations with values learned later. There is no automatic GIS membership computation yet.

## Metric semantics

- The latest common complete day anchors the two-school headline comparison. Chart lines can show each school's individual valid dates. Gaps are null, never zero.
- The newest complete run per school/day is canonical; later failed/partial attempts do not erase a completed inventory observation. All attempts remain in the collection ledger.
- Each historical date is filtered using its own price/year/bed/bath facts. A house entering the price band is not relabeled as newly listed.
- Active inventory excludes pending and under-contract listings; those are shown separately. Unknown statuses are not assumed active.
- The median is an asking-price composition measure, not an appreciation index. Invalid/missing asking prices do not contribute to it.
- Individual timelines ignore price/year/date filters so previously observed homes remain inspectable. Missing observations and last known states are distinguished.
- In the actual first-page sample, market totals and trend metrics are withheld. List counts describe the observed sample only.

## Backup and replay

```powershell
python -m tracker.cli backup C:/private/backups/housing-2026-09-29.sqlite3
python -m tracker.cli export-run RUN_ID C:/private/exported-run.json
python -m tracker.cli --db C:/private/restored.sqlite3 import-json C:/private/exported-run.json
```

Backup uses SQLite's consistent backup API, checks integrity and returns a SHA256 digest. It refuses to overwrite an existing destination. Copy the sibling `raw/` directory separately for full source evidence; it is content-addressed and immutable. The database backup includes normalized compressed source payloads but not the full HTML archive. Keep a copy on independent storage; a second file on the same disk is not protection against disk failure. Set `HOUSING_DB_PATH` to the restored database to inspect it.

This prototype does not delete raw evidence or enable paid services. Cloud raw retention and independent backup automation remain in the [implementation plan](docs/IMPLEMENTATION_PLAN.md).

## Verification

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests cover snapshot validation/atomicity, duplicate import, Eastern dates, failed/partial exclusion, missing-day gaps, historical price filtering, disappearance without sale inference, sale-price evidence, both year-built paths, backup/replay/checksums, and Streamlit filter interactions including empty results and absent school data. Streamlit AppTest exercises application rendering and widget behavior without a browser; it is not a pixel-level visual review.

Verified in the original Windows workspace on 2026-09-29: all 18 tests passed; the three UI tests also passed after the final layout API update. A separate AppTest check against the actual saved probe confirmed 41 observations, three construction years and exception-free rendering in both modes. The running local server returned HTTP 200 and an `ok` health check on port 8502. Browser visual inspection was unavailable in this environment.

## Next integration gates

Validate both official school boundaries and complete all-price discovery; verify access from a cloud runner and operating conditions for the chosen data source; then connect the collector to persistent hosted storage and run a multi-day pilot. The existing `probe_zillow.ps1` remains a manual first-page diagnostic and overwrites its output files. Use a new private output directory for each observation and import it promptly. Do not schedule that probe as if it were a complete market collector.

See [research](docs/FEASIBILITY.md), [actual probe findings](docs/ZILLOW_PROBE_2026-09-29.md), and [implementation plan](docs/IMPLEMENTATION_PLAN.md).
