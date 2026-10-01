"""Portable immutable observations; SQLite is a rebuildable local query store."""
import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path

from tracker.collect import read_json
from tracker.storage import connection, import_snapshot, initialize

REMOTE = "https://raw.githubusercontent.com/ladavid9989/data_science/data/school-housing-tracker/"


def rebuild(db, archive):
    count = 0
    for path in sorted(Path(archive).glob("snapshots/*/*.json.gz")):
        count += import_snapshot(db, read_json(path))[1]
    return count


def index_archive(archive):
    root = Path(archive)
    entries = []
    for path in sorted(root.glob("snapshots/*/*.json.gz")):
        snapshot = read_json(path)
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        entries.append({"path": path.relative_to(root).as_posix(), "run_id": digest,
                        "school": snapshot["school"], "observed_at": snapshot["observed_at"],
                        "quality": snapshot["quality"], "rows": len(snapshot["listings"])})
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(json.dumps({"version": 1, "snapshots": entries}, indent=2), encoding="utf-8")
    return entries


def sync(db):
    import gzip
    initialize(db)
    with urllib.request.urlopen(REMOTE + f"index.json?t={time.time_ns()}", timeout=20) as reply:
        index = json.load(reply)
    with connection(db) as conn:
        existing = {row[0] for row in conn.execute("SELECT run_id FROM runs")}
    count = 0
    for entry in index["snapshots"]:
        if entry["run_id"] in existing:
            continue
        if not re.fullmatch(r"snapshots/\d{4}-\d{2}-\d{2}/(?:north_gwinnett|johns_creek)-[a-f0-9]{64}\.json\.gz", entry["path"]):
            raise ValueError("Invalid archive path")
        with urllib.request.urlopen(REMOTE + entry["path"], timeout=20) as reply:
            payload = json.loads(gzip.decompress(reply.read()))
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if digest != entry["run_id"] or payload.get("dataset") != "observed":
            raise ValueError("Archive checksum or dataset mismatch")
        count += import_snapshot(db, payload)[1]
    return count
