import copy

import pytest

from tests.scenarios import snapshots
from tracker.archive import index_archive, rebuild
from tracker.collect import AccessBlocked, collect_school, contains, filters, validate_page, write_json
from tracker.metrics import canonical_runs
from tracker.storage import SOURCE_SCOPE, import_snapshot, read_frames


def test_polygon_holes_and_multipart():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]
    geo = {"features": [{"geometry": {"type": "MultiPolygon", "coordinates": [[outer, hole]]}}]}
    assert contains(geo, 1, 1)
    assert not contains(geo, 3, 3)
    assert not contains(geo, 11, 1)
    assert contains(geo, None, 1) is None


def test_pagination_and_filters_must_match():
    state = {"queryState": {"schoolId": 102507, "filterState": filters(), "pagination": {"currentPage": 2}}}
    validate_page(state, 102507, filters(), {}, 2)
    with pytest.raises(ValueError, match="Pagination"):
        validate_page(state, 102507, filters(), {}, 3)
    state["queryState"]["filterState"]["price"]["max"] = 700000
    with pytest.raises(ValueError, match="filter mismatch"):
        validate_page(state, 102507, filters(), {}, 2)


def test_block_is_saved_as_failure_not_zero_inventory(tmp_path):
    class Blocked:
        evidence = []

        def get(self, url):
            raise AccessBlocked("HTTP 403")

    db, archive = tmp_path / "data.sqlite3", tmp_path / "archive"
    result = collect_school(db, archive, "north_gwinnett", Blocked())
    assert result["quality"] == "failed" and result["access_blocked"]
    assert not result["listings"]
    assert len(index_archive(archive)) == 1
    restored = tmp_path / "restored.sqlite3"
    assert rebuild(restored, archive) == 1
    assert rebuild(restored, archive) == 0
    assert canonical_runs(read_frames(restored, "observed")[0]).empty


def test_source_scope_not_mixed_across_boundary_versions(tmp_path):
    db = tmp_path / "x.sqlite3"
    sample = next(snapshots())
    sample.update(quality="source_complete", scope=SOURCE_SCOPE + ":zone-a", boundary_version="zone-a")
    sample["coverage"]["official_zone_verified"] = False
    import_snapshot(db, sample)
    second = copy.deepcopy(sample)
    second.update(observed_at="2026-09-01T10:00:00Z", scope=SOURCE_SCOPE + ":zone-b", boundary_version="zone-b")
    import_snapshot(db, second)
    runs = canonical_runs(read_frames(db, "observed")[0])
    assert len(runs) == 1 and runs.iloc[0].boundary_version == "zone-b"


@pytest.mark.parametrize('school', ['chattahoochee', 'northview'])
def test_cloud_sync_accepts_new_school_and_rejects_unknown_paths(tmp_path, monkeypatch, school):
    import gzip
    import io
    import json
    from tracker import archive as module
    sample = next(snapshots())
    sample['school'] = school
    archive = tmp_path / 'archive'
    run_id, _ = import_snapshot(tmp_path / 'source.db', sample)
    relative = f'snapshots/2026-08-31/{school}-{run_id}.json.gz'
    write_json(archive / relative, sample)
    index = {'version': 1, 'snapshots': index_archive(archive)}

    def reply(url, **kwargs):
        if 'index.json' in url:
            return io.BytesIO(json.dumps(index).encode())
        assert url.endswith(relative)
        return io.BytesIO(gzip.compress(json.dumps(sample).encode()))

    monkeypatch.setattr(module.urllib.request, 'urlopen', reply)
    target = tmp_path / 'cloud.db'
    assert module.sync(target) == 1
    assert read_frames(target, 'observed')[0].school.tolist() == [school]
    assert module.sync(target) == 0
    index['snapshots'][0]['path'] = relative.replace(school, 'unknown_school')
    with pytest.raises(ValueError, match='Invalid archive path'):
        module.sync(tmp_path / 'invalid.db')


def test_inventory_precedes_enrichment_and_rate_limit_stops_details(tmp_path, monkeypatch):
    from tracker import collect as module
    order = []
    archive = tmp_path / "archive"

    class NoNetwork:
        def __init__(self, *args, **kwargs):
            self.evidence = []

    def search(db, folder, school, client, detail_limit):
        assert detail_limit == 0
        order.append("search:" + school)
        sample = next(snapshots())
        sample.update(school=school, quality="source_complete", scope=SOURCE_SCOPE + ":test", evidence_files=[])
        write_json(folder / "state" / (school + "-details.json.gz"), {})
        write_json(folder / "state" / (school + "-zone.json.gz"), {})
        return sample

    def enrich(db, school, *args):
        order.append("detail:" + school)
        raise AccessBlocked("HTTP 429", 3600)

    monkeypatch.setattr(module, "Client", NoNetwork)
    monkeypatch.setattr(module, "collect_school", search)
    monkeypatch.setattr(module, "enrich_school", enrich)
    result = module.collect(tmp_path / "x.sqlite3", archive)
    assert len(result) == len(module.SOURCES)
    assert order == ['search:' + school for school in module.SOURCES] + ["detail:north_gwinnett"]
    assert result[0]["access_blocked"]
    order.clear()
    assert module.collect(tmp_path / "x.sqlite3", archive) == []
    assert not order
