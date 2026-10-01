# Schoolside

Real observations only. Daily GitHub Actions collection at **06:17 America/New_York**; the PC is not required.

- Code: `feature/school-housing-tracker`.
- History: `data/school-housing-tracker`, immutable compressed JSON snapshots plus an index and reusable detail metadata. This public repository makes these observations public. No HTML or photos are committed.
- SQLite: a rebuildable local query store at `%LOCALAPPDATA%/SchoolHousingTracker/prototype.sqlite3`; override `HOUSING_DB_PATH`.
- UI: `./scripts/start-local.ps1`, then http://127.0.0.1:8502. The app synchronizes new cloud observations on opening and every five minutes on rerun. Hosting the UI is separate from collection.

```powershell
python -m pip install -r requirements.txt
python -m tracker.cli sync
python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8502
```

Collection covers Houses, 3+ bedrooms, 2+ bathrooms, all asking prices, including source contract statuses. UI defaults to $400k-700k. Construction years are progressively enriched and cached. Known properties can be checked after disappearing; disappearance alone never means sold.

`source_complete` means the school search's filters, pages and unique result count reconcile. Coordinate checks use public school polygons, but exhaustive school-zone coverage and effective boundary school years are not independently established. Unmapped properties are excluded from mapped inventory. `partial` and `failed` records are retained and excluded from trends; different query/boundary versions are not combined. Missing days cannot be reconstructed from today's results.

The workflow saves observations even when collection fails. Access challenges stop requests without bypass. Actions schedules can be delayed/dropped or disabled after 60 days of repository inactivity; check the Actions page and collection ledger. Source access success does not establish permission for recurring use under Zillow's terms.

```powershell
python -m tracker.cli collect --archive C:/private/history --detail-limit 5
python -m tracker.cli rebuild C:/private/history
python -m tracker.cli backup C:/private/backups/housing.sqlite3
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Archive snapshots can rebuild SQLite; local raw responses live beside the database in `raw/`. GitHub runner raw HTML is temporary. Keep an independent clone/backup of the data branch for account-loss recovery. Test fixtures are confined to `tests/` and never seeded into the app. Existing research documents describe earlier stages, not current deployment status.
