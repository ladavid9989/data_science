"""Portable immutable observations; SQLite is a rebuildable local query store."""
import hashlib
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tracker.collect import read_json
from tracker.band import restrict_snapshot, prune_database
from tracker.storage import SCHOOLS, connection, import_snapshot, initialize, insert_snapshot
from tracker.health import read_status, write_status, local_status_path

REMOTE = "https://raw.githubusercontent.com/ladavid9989/data_science/data/school-housing-tracker/"


def rebuild(db, archive):
    prune_database(db)
    count = 0
    for path in sorted(Path(archive).glob("snapshots/*/*.json.gz")):
        count += import_snapshot(db, restrict_snapshot(read_json(path)))[1]
    return count


def index_archive(archive):
    root = Path(archive)
    entries = []
    last_success = {}
    for path in sorted(root.glob("snapshots/*/*.json.gz")):
        snapshot = read_json(path)
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        entries.append({"path": path.relative_to(root).as_posix(), "run_id": digest,
                        "school": snapshot["school"], "observed_at": snapshot["observed_at"],
                        "quality": snapshot["quality"], "rows": len(snapshot["listings"])})
        if snapshot['quality'] == 'source_complete':
            stamp = snapshot.get('collection_finished_at') or snapshot.get('search_observed_at') or snapshot['observed_at']
            school = snapshot['school']
            last_success[school] = max(last_success.get(school, ''), stamp)
    root.mkdir(parents=True, exist_ok=True)
    status = read_status(root / 'state/collection-status.json')
    status['last_success_by_school'] = last_success
    (root / "index.json").write_text(json.dumps({"version": 1, "snapshots": entries, 'collection_status': status}, indent=2), encoding="utf-8")
    return entries


def sync(db):
    import gzip
    initialize(db)
    prune_database(db)
    with urllib.request.urlopen(REMOTE + f"index.json?t={time.time_ns()}", timeout=20) as reply:
        index = json.load(reply)
    write_status(local_status_path(db), index.get('collection_status') or {})
    with connection(db) as conn:
        existing = {row[0] for row in conn.execute("SELECT run_id FROM runs")}
    pending = [entry for entry in index['snapshots'] if entry['run_id'] not in existing]
    schools = '|'.join(re.escape(school) for school in SCHOOLS)
    for entry in pending:
        if not re.fullmatch(r"snapshots/\d{4}-\d{2}-\d{2}/(?:" + schools + r")-[a-f0-9]{64}\.json\.gz", entry["path"]):
            raise ValueError("Invalid archive path")

    def download(entry):
        with urllib.request.urlopen(REMOTE + entry["path"], timeout=20) as reply:
            payload = json.loads(gzip.decompress(reply.read()))
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if digest != entry["run_id"] or payload.get("dataset") != "observed":
            raise ValueError("Archive checksum or dataset mismatch")
        return restrict_snapshot(payload)

    count = 0
    # Only immutable files from our GitHub archive are fetched concurrently.
    # Zillow collection limits remain unchanged. Keep memory and writes bounded.
    with ThreadPoolExecutor(max_workers=8) as downloads:
        for offset in range(0, len(pending), 32):
            payloads = list(downloads.map(download, pending[offset:offset + 32]))
            with connection(db) as conn, conn:
                for payload in payloads:
                    count += insert_snapshot(conn, payload)[1]
    return count
