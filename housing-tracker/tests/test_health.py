import io
import json
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from urllib.error import HTTPError

import pytest

from tracker.collect import AccessBlocked, access_failure, read_json, write_json
from tracker.health import local_status_path, read_status, status_notice, write_status


def rejection(retry=None):
    headers = Message()
    if retry is not None:
        headers['Retry-After'] = retry
    headers['X-Request-ID'] = 'diagnostic-id'
    return access_failure(HTTPError('https://example.com/search?private=value', 403, 'Forbidden', headers,
                                   io.BytesIO(b'<html>Access denied</html>')),
                          'https://example.com/search?private=value')


@pytest.mark.parametrize('retry,expected', [(None, 10800), ('300', 10800), ('21600', 21600), ('bad value', 10800)])
def test_403_three_hour_floor_and_server_retry_after(retry, expected):
    failure = rejection(retry)
    assert failure.wait_seconds == expected
    assert failure.diagnostics['request_path'] == 'https://example.com/search'
    assert failure.diagnostics['response_headers']['X-Request-ID'] == 'diagnostic-id'
    assert failure.diagnostics['response_kind'] == 'access_denied'


def test_retry_after_http_date():
    deadline = datetime.now(timezone.utc) + timedelta(hours=6)
    failure = rejection(format_datetime(deadline, usegmt=True))
    assert 21595 <= failure.wait_seconds <= 21600


def test_repeated_403_stays_three_hours_and_success_resets_streak(tmp_path, monkeypatch):
    from tracker import batch as module
    from tests.test_batch import FakeClient, page, ready
    stamp = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'utcnow', lambda: stamp)
    monkeypatch.setattr(module, 'SOURCES', {'north_gwinnett': module.SOURCES['north_gwinnett']})
    batch, _ = ready(tmp_path, FakeClient([rejection()]))
    assert batch.run()['status'] == 'blocked'
    policy = read_json(batch.root / 'state/access.json.gz')
    assert datetime.fromisoformat(policy['retry_after']) == stamp + timedelta(hours=3)
    stamp += timedelta(hours=3, seconds=1)
    repeated = module.Batch(batch.db, batch.root, 2, 0, client=FakeClient([rejection()]))
    assert repeated.run()['status'] == 'blocked'
    policy = read_json(batch.root / 'state/access.json.gz')
    assert policy['strikes'] == 2 and policy['review_required']
    assert datetime.fromisoformat(policy['retry_after']) == stamp + timedelta(hours=3)
    waiting = module.Batch(batch.db, batch.root, client=FakeClient([]))
    assert waiting.run()['status'] == 'cooldown'
    assert not waiting.client.urls
    stamp += timedelta(hours=3, seconds=1)
    recovered = module.Batch(batch.db, batch.root, 2, 0, client=FakeClient([page(1, 1), page(2, 2)]))
    assert recovered.run()['status'] == 'complete'
    assert read_json(batch.root / 'state/access.json.gz')['strikes'] == 0
    assert len(read_json(batch.root / 'state/access-events.json.gz')) == 2


def test_cooldown_cli_fails_and_publishes_status_without_new_observations(tmp_path, monkeypatch):
    from tracker import cli
    stamp = datetime.now(timezone.utc)
    archive = tmp_path / 'archive'
    write_json(archive / 'state/access.json.gz', dict(reason='HTTP 403: source access stopped', strikes=2,
               retry_after=(stamp + timedelta(hours=3)).isoformat(), review_required=True))
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    monkeypatch.setattr('sys.argv', ['tracker', '--db', str(tmp_path / 'db.sqlite3'), 'collect', '--archive', str(archive)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    index = read_status(archive / 'index.json')
    assert index['snapshots'] == []
    assert index['collection_status']['status'] == 'cooldown'
    assert index['collection_status']['requests'] == 0
    assert '재시도 가능 시각' in summary.read_text(encoding='utf-8')
    assert '마지막 검색 성공' in summary.read_text(encoding='utf-8')


def test_status_sync_works_without_new_market_snapshots(tmp_path, monkeypatch):
    from tracker import archive
    status = dict(status='cooldown', retry_after='2026-10-27T01:00:00+00:00')
    index = dict(version=1, snapshots=[], collection_status=status)
    monkeypatch.setattr(archive.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(json.dumps(index).encode()))
    db = tmp_path / 'cloud.sqlite3'
    assert archive.sync(db) == 0
    assert read_status(local_status_path(db)) == status


def test_parallel_archive_restore_checks_hashes_and_commits_in_order(tmp_path, monkeypatch):
    import gzip
    import hashlib
    from tracker import archive
    from tracker.storage import connection
    from tests.scenarios import snapshots
    payloads = [next(snapshots())]
    second = json.loads(json.dumps(payloads[0]))
    second['observed_at'] = '2026-09-01T10:17:00+00:00'
    payloads.append(second)
    entries, files = [], {}
    for payload in payloads:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        path = f"snapshots/{payload['observed_at'][:10]}/{payload['school']}-{digest}.json.gz"
        entries.append(dict(run_id=digest, path=path))
        files[archive.REMOTE + path] = gzip.compress(json.dumps(payload).encode())
    index = dict(version=1, snapshots=entries)
    def reply(url, **kwargs):
        return io.BytesIO(json.dumps(index).encode() if 'index.json' in url else files[url])
    monkeypatch.setattr(archive.urllib.request, 'urlopen', reply)
    db = tmp_path / 'parallel.sqlite3'
    assert archive.sync(db) == 2
    with connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 2
    files[archive.REMOTE + entries[1]['path']] = gzip.compress(json.dumps(payloads[0]).encode())
    bad_db = tmp_path / 'invalid.sqlite3'
    with pytest.raises(ValueError, match='checksum'):
        archive.sync(bad_db)
    with connection(bad_db) as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_last_success_uses_search_time_not_year_enrichment_time(tmp_path):
    from tracker.archive import index_archive
    snapshot = dict(school='northview', observed_at='2026-10-26T23:00:00+00:00',
                    collection_finished_at='2026-10-25T15:00:00+00:00', quality='source_complete', listings=[])
    write_json(tmp_path / 'snapshots/2026-10-26/northview-test.json.gz', snapshot)
    index_archive(tmp_path)
    assert read_status(tmp_path / 'index.json')['collection_status']['last_success_by_school']['northview'] == snapshot['collection_finished_at']


def test_expired_cooldown_does_not_claim_collection_resumed():
    level, notice = status_notice(dict(status='cooldown', retry_after='2026-10-26T10:00:00+00:00'),
                                  datetime(2026, 10, 26, 11, tzinfo=timezone.utc))
    assert level == 'error'
    assert '다음 배치 결과를 기다립니다' in notice


def test_dashboard_displays_stop_retry_and_last_success(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.test_app import APP
    from tests.scenarios import seed
    db = tmp_path / 'display.sqlite3'
    seed(db)
    monkeypatch.setenv('HOUSING_DB_PATH', str(db))
    monkeypatch.setenv('HOUSING_OFFLINE', '1')
    write_status(local_status_path(db), dict(status='cooldown', reason='HTTP 403', strikes=2, review_required=True,
                 checked_at=datetime.now(timezone.utc).isoformat(), retry_after='2026-10-27T01:30:00+00:00',
                 last_success_by_school={'northview': '2026-10-26T20:00:00+00:00'}))
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    assert any('수집 중단' in error.value and '09:30 PM EDT' in error.value for error in app.error)
    assert any('반복 접근 거부 2회' in warning.value for warning in app.warning)
    assert any('Northview · 마지막 검색 성공: 2026-10-26 04:00 PM EDT' in item.value for item in app.markdown)
