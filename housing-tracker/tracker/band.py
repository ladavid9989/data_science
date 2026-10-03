"""The product's fixed, inclusive asking-price scope and reversible archive migration."""
import copy
import gzip
import hashlib
import json
from pathlib import Path

from tracker.storage import BAND_SCOPE, connection, initialize, insert_snapshot

PRICE_RANGE = (400000, 700000)


def in_band(price):
    try:
        return PRICE_RANGE[0] <= float(price) <= PRICE_RANGE[1]
    except (ValueError, TypeError):
        return False


def restrict_snapshot(snapshot):
    rows = [r for r in snapshot['listings'] if in_band(r.get('price'))]
    if len(rows) == len(snapshot['listings']):
        return snapshot
    result = copy.deepcopy(snapshot)
    result['listings'] = rows
    result['expected_unique_count'] = len(rows)
    removed = len(snapshot['listings']) - len(rows)
    if not str(snapshot.get('scope', '')).startswith(BAND_SCOPE + ':'):
        # A filtered legacy sample is not a newly validated price-band search.
        result.update(quality='partial', scope=BAND_SCOPE + ':' + snapshot.get('boundary_version', 'unverified') + ':legacy_projection',
                      reported_count=None, coverage=dict(price_range=list(PRICE_RANGE), all_prices=False, all_pages=False))
    result['note'] = snapshot.get('note', '') + f' Stored asking-price scope restricted to $400k-$700k; removed {removed} out-of-scope observations.'
    return result


def prune_database(path):
    initialize(path)
    removed = 0
    with connection(path) as db, db:
        records = db.execute('SELECT run_id,raw_gzip FROM runs WHERE dataset=?', ('observed',)).fetchall()
        for run_id, payload in records:
            original = json.loads(gzip.decompress(payload))
            clean = restrict_snapshot(original)
            if clean is original:
                continue
            removed += len(original['listings']) - len(clean['listings'])
            db.execute('DELETE FROM observations WHERE run_id=?', (run_id,))
            db.execute('DELETE FROM runs WHERE run_id=?', (run_id,))
            insert_snapshot(db, clean)
    return removed


def prune_archive(root):
    from tracker.collect import read_json, write_json
    root = Path(root).resolve()
    removed, retained = 0, set()
    for path in sorted(root.glob('snapshots/*/*.json.gz')):
        original = read_json(path)
        clean = restrict_snapshot(original)
        retained.update(r['property_id'] for r in clean['listings'])
        if clean is original:
            continue
        removed += len(original['listings']) - len(clean['listings'])
        digest = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        destination = path.with_name(f"{clean['school']}-{digest}.json.gz")
        write_json(destination, clean)
        if not path.resolve().is_relative_to(root):
            raise ValueError('Archive path escaped root')
        path.unlink()
    state_file = root / 'state/batch-v2.json.gz'
    if state_file.exists():
        state = read_json(state_file)
        for job in state.get('jobs', {}).values():
            for key in ('rows', 'watch', 'previous', 'followed'):
                if key in job:
                    job[key] = {pid: row for pid, row in job[key].items() if in_band(row.get('price'))}
        if state.get('outbox'):
            state['outbox'] = restrict_snapshot(state['outbox'])
        state['details'] = {pid: facts for pid, facts in state.get('details', {}).items() if pid in retained}
        write_json(state_file, state)
    for path in (root / 'state').glob('*-details.json.gz'):
        write_json(path, {pid: facts for pid, facts in read_json(path).items() if pid in retained})
    return removed
