"""Immutable snapshots with transactional, idempotent publication."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

SCHOOLS = {"north_gwinnett": "North Gwinnett High School", "johns_creek": "Johns Creek High School",
           "chattahoochee": "Chattahoochee High School", "northview": "Northview High School"}
SCOPE = "houses_3bed_2bath_all_prices_v1"
SOURCE_SCOPE = "zillow_school_search_houses_3bed_2bath_all_prices_v1"
BAND_SCOPE = "zillow_school_search_houses_3bed_2bath_400k_700k_v2"
EXTRAS = {'year_status': 'TEXT', 'year_observed_at': 'TEXT', 'price_observed_at': 'TEXT',
          'status_observed_at': 'TEXT',
          'price_cut': 'REAL', 'price_cut_date': 'TEXT', 'cut_source': 'TEXT', 'facts_hash': 'TEXT'}
DATASETS = {"observed"}
STATUSES = {"active", "under_contract", "pending", "sold", "withdrawn", "off_market_unknown"}


def default_db() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return Path(os.environ.get("HOUSING_DB_PATH", str(root / "SchoolHousingTracker" / "prototype.sqlite3")))


@contextmanager
def connection(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()


def initialize(path):
    with connection(path) as db, db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY, dataset TEXT NOT NULL, school TEXT NOT NULL,
          observed_at TEXT NOT NULL, market_date TEXT NOT NULL, scope TEXT NOT NULL,
          quality TEXT NOT NULL, reported_count INTEGER, row_count INTEGER NOT NULL,
          boundary_version TEXT NOT NULL, note TEXT NOT NULL, source TEXT NOT NULL,
          imported_at TEXT NOT NULL, raw_gzip BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
          run_id TEXT NOT NULL REFERENCES runs(run_id), property_id TEXT NOT NULL,
          episode_id TEXT NOT NULL, address TEXT NOT NULL, price REAL,
          bedrooms REAL, bathrooms REAL, square_feet REAL, year_built INTEGER,
          property_type TEXT NOT NULL, status TEXT NOT NULL, raw_status TEXT NOT NULL,
          latitude REAL, longitude REAL, url TEXT, year_source TEXT,
          sold_price REAL, sold_date TEXT, evidence TEXT,
          PRIMARY KEY (run_id, property_id)
        );
        CREATE INDEX IF NOT EXISTS run_lookup ON runs(dataset, school, market_date, observed_at);
        CREATE INDEX IF NOT EXISTS property_lookup ON observations(property_id, episode_id);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(observations)")}
        if "in_inventory" not in columns:
            db.execute("ALTER TABLE observations ADD COLUMN in_inventory INTEGER NOT NULL DEFAULT 1")
        for column, kind in EXTRAS.items():
            if column not in columns:
                db.execute(f'ALTER TABLE observations ADD COLUMN {column} {kind}')


def normalize_status(value):
    text = str(value or "").strip().lower().replace("_", " ")
    return {
        "active": "active", "for sale": "active", "house for sale": "active", "forsale": "active",
        "for sale by owner": "active",
        "active under contract": "under_contract", "under contract": "under_contract",
        "pending": "pending", "sold": "sold", "recently sold": "sold", "closed": "sold",
        "withdrawn": "withdrawn", "off market": "off_market_unknown",
        "off market unknown": "off_market_unknown",
    }.get(text, "off_market_unknown")


def number(value, field, minimum=0, maximum=None, integer=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected a number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field}: invalid number") from exc
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"{field}: out of range")
    if integer and result != int(result):
        raise ValueError(f"{field}: expected integer")
    return int(result) if integer else result


def validate(snapshot):
    if snapshot.get("schema_version") != 1:
        raise ValueError("Expected snapshot schema_version=1")
    if snapshot.get("dataset") not in DATASETS or snapshot.get("school") not in SCHOOLS:
        raise ValueError("Unknown dataset or school")
    observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("observed_at must contain an explicit timezone")
    stamp = observed.astimezone(timezone.utc).isoformat()
    day = observed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if snapshot.get('search_observed_at'):
        search_time = datetime.fromisoformat(snapshot['search_observed_at'])
        if search_time.tzinfo is None or search_time > observed:
            raise ValueError('Invalid search observation time')
        day = search_time.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    quality = snapshot.get("quality")
    if quality not in {"complete", "source_complete", "partial", "failed"}:
        raise ValueError("Unknown quality")
    rows = snapshot.get("listings")
    if not isinstance(rows, list):
        raise ValueError("listings must be an array")
    if quality == "failed" and rows:
        raise ValueError("Failed runs cannot contain observations; use partial")
    if quality == "source_complete":
        coverage = snapshot.get("coverage", {})
        band = str(snapshot.get('scope', '')).startswith(BAND_SCOPE + ':')
        scope_ok = band or str(snapshot.get('scope', '')).startswith(SOURCE_SCOPE + ':')
        price_ok = coverage.get('price_range') == [400000, 700000] if band else coverage.get('all_prices') is True
        if not scope_ok or not price_ok or not all(coverage.get(k) is True for k in ('all_pages', 'query_validated')):
            raise ValueError('Source publication requires validated query and pagination')
        if number(snapshot.get("expected_unique_count"), "expected_unique_count", integer=True) != len(rows):
            raise ValueError("Source publication must reconcile rows")
    if quality == "complete":
        coverage = snapshot.get("coverage", {})
        if snapshot.get("scope") != SCOPE or not all(coverage.get(k) is True for k in
                ("all_pages", "all_prices", "official_zone_verified", "query_validated")):
            raise ValueError("Complete publication requires all-price, all-page, zone and query verification")
        if not snapshot.get("boundary_version"):
            raise ValueError("Complete publication requires boundary_version")
        if number(snapshot.get("expected_unique_count"), "expected_unique_count", integer=True) != len(rows):
            raise ValueError("Complete publication must reconcile expected_unique_count with rows")
    parsed = []
    seen = set()
    for row in rows:
        pid = str(row.get("property_id", "")).strip()
        if not pid or pid in seen:
            raise ValueError("Missing or duplicate property_id")
        seen.add(pid)
        episode = str(row.get("episode_id") or f"{pid}:unknown")
        status = normalize_status(row.get("status"))
        price = number(row.get("price"), "price")
        beds = number(row.get("bedrooms"), "bedrooms")
        baths = number(row.get("bathrooms"), "bathrooms")
        kind = row.get("property_type", "UNKNOWN")
        # Sold / off-market observations may follow a formerly eligible property.
        if quality == "complete" and status in {"active", "pending", "under_contract"}:
            if beds is None or beds < 3 or baths is None or baths < 2 or kind != "SINGLE_FAMILY":
                raise ValueError("In-scope inventory must meet house/bed/bath criteria")
        sold_price = number(row.get("sold_price"), "sold_price")
        sold_date = row.get("sold_date")
        if sold_price is not None and (status != "sold" or not sold_date or not row.get("evidence")):
            raise ValueError("sold_price requires explicit sold status, sold_date and episode evidence")
        if sold_date:
            sale_day = datetime.strptime(sold_date, "%Y-%m-%d").date()
            if sale_day > observed.date():
                raise ValueError("sold_date cannot follow the observation")
        url = str(row.get("url") or "")
        if url and not url.startswith("https://"):
            raise ValueError("Property links must use HTTPS")
        year = number(row.get("year_built"), "year_built", 1600, observed.year + 5, True)
        parsed.append((pid, episode, str(row.get("address") or pid), price, beds, baths,
                       number(row.get("square_feet"), "square_feet"), year, kind, status,
                       str(row.get("raw_status") or row.get("status") or ""),
                       number(row.get("latitude"), "latitude", -90, 90),
                       number(row.get("longitude"), "longitude", -180, 180), url,
                       str(row.get("year_source") or ""), sold_price, sold_date,
                       str(row.get("evidence") or ""), int(bool(row.get("in_inventory", True)))))
    return stamp, day, parsed


def import_snapshot(path, snapshot):
    validate(snapshot)
    initialize(path)
    with connection(path) as db, db:
        return insert_snapshot(db, snapshot)


def insert_snapshot(db, snapshot):
    """Insert inside the caller's transaction; also used by atomic scope migration."""
    stamp, day, rows = validate(snapshot)
    raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    run_id = hashlib.sha256(raw).hexdigest()
    if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
        return run_id, False
    # Equal-time conflicting versions require a deliberate new observed_at.
    if db.execute("SELECT 1 FROM runs WHERE dataset=? AND school=? AND observed_at=?",
                  (snapshot["dataset"], snapshot["school"], stamp)).fetchone():
        raise ValueError("Conflicting snapshot for the same school/dataset/observation time")
    db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        run_id, snapshot["dataset"], snapshot["school"], stamp, day,
        snapshot.get("scope", "unknown"), snapshot["quality"],
        number(snapshot.get("reported_count"), "reported_count", integer=True), len(rows),
        snapshot.get("boundary_version", "unverified"), snapshot.get("note", ""),
        snapshot.get("source", "manual import"), datetime.now(timezone.utc).isoformat(),
        gzip.compress(raw, mtime=0)))
    columns = 'run_id,property_id,episode_id,address,price,bedrooms,bathrooms,square_feet,year_built,property_type,status,raw_status,latitude,longitude,url,year_source,sold_price,sold_date,evidence,in_inventory'
    db.executemany("INSERT INTO observations (" + columns + ") VALUES (" + ",".join(["?"] * 20) + ")",
                   [(run_id, *row) for row in rows])
    for row in snapshot['listings']:
        values = [row.get(k) for k in EXTRAS]
        if row.get('price_cut') is not None:
            number(row['price_cut'], 'price_cut')
        db.execute('UPDATE observations SET ' + ','.join(k + '=?' for k in EXTRAS) +
                   ' WHERE run_id=? AND property_id=?', [*values, run_id, row['property_id']])
    return run_id, True


def read_frames(path, dataset):
    initialize(path)
    with connection(path) as db:
        runs = pd.read_sql_query("SELECT run_id,dataset,school,observed_at,market_date,scope,quality,"
            "reported_count,row_count,boundary_version,note,source FROM runs WHERE dataset=? "
            "ORDER BY observed_at,run_id", db, params=(dataset,))
        observations = pd.read_sql_query("SELECT o.* FROM observations o JOIN runs r USING(run_id) "
            "WHERE r.dataset=?", db, params=(dataset,))
    for column in ("price", "bedrooms", "bathrooms", "square_feet", "year_built", "sold_price",
                   "latitude", "longitude", "price_cut"):
        observations[column] = pd.to_numeric(observations[column], errors="coerce")
    return runs, observations


def export_snapshot(path, run_id):
    with connection(path) as db:
        row = db.execute("SELECT raw_gzip FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown run_id")
    raw = gzip.decompress(row[0])
    if hashlib.sha256(raw).hexdigest() != run_id:
        raise ValueError("Stored payload checksum mismatch")
    return json.loads(raw)


def backup(path, destination):
    target = Path(destination)
    if Path(path).resolve() == target.resolve() or target.exists():
        raise ValueError("Choose a new backup filename")
    target.parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as src, sqlite3.connect(target) as dest:
        src.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
    return hashlib.sha256(target.read_bytes()).hexdigest()
