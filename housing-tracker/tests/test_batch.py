import copy
import json
from datetime import timedelta

import pandas as pd
import pytest

from tracker.batch import Batch, BatchFull, PRICE_RANGE, utcnow
from tracker.collect import AccessBlocked, filters, read_json, write_json
from tracker.extraction import extract_detail, extract_search, facts_hash
from tracker.metrics import canonical_runs, rank_price_cuts
from tracker.storage import read_frames


def item(pid=1, price=590000):
    return dict(zpid=pid, unformattedPrice=price, address=f'{pid} Main St', beds=4, baths=3,
                area=2000, statusText='House for sale', detailUrl=f'/homedetails/{pid}_zpid/',
                latLong=dict(latitude=1, longitude=1), hdpData=dict(homeInfo=dict(homeType='SINGLE_FAMILY')))


def page(number, pid, total=2):
    state = dict(queryState=dict(schoolId=102507, filterState=filters(*PRICE_RANGE), pagination=dict(currentPage=number)),
                 cat1=dict(searchList=dict(totalResultCount=total, totalPages=2), searchResults=dict(listResults=[item(pid)])))
    return '<script id="__NEXT_DATA__">' + json.dumps(dict(props=dict(pageProps=dict(searchPageState=state)))) + '</script>'


class FakeClient:
    def __init__(self, responses):
        self.responses, self.urls = iter(responses), []

    def get(self, url):
        self.urls.append(url)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def ready(tmp_path, client, limit=1):
    batch = Batch(tmp_path / 'db.sqlite3', tmp_path / 'archive', limit, 0, client=client)
    job = dict(started_at=utcnow().isoformat(), next_page=1, rows={}, ids=[], evidence=[],
               query=dict(schoolId=102507, filterState=filters(*PRICE_RANGE)), defaults={},
               zone=dict(version='test', geometry={'features': [{'geometry': {'type': 'Polygon',
                     'coordinates': [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}}]}))
    batch.state['jobs']['north_gwinnett'] = job
    batch.save()
    return batch, job


def test_resume_next_page_and_replay_archive(tmp_path):
    first = FakeClient([page(1, 1)])
    batch, job = ready(tmp_path, first)
    with pytest.raises(BatchFull):
        batch.search('north_gwinnett', job)
    assert read_json(batch.path)['jobs']['north_gwinnett']['next_page'] == 2
    second = FakeClient([page(2, 2)])
    resumed = Batch(batch.db, batch.root, 1, 0, client=second)
    resumed.search('north_gwinnett', resumed.state['jobs']['north_gwinnett'])
    assert len(second.urls) == 1 and '2_p/' in second.urls[0]
    runs, rows = read_frames(batch.db, 'observed')
    assert len(canonical_runs(runs)) == 1 and len(rows) == 2
    assert rows.price.between(400000, 700000).all()
    from tracker.archive import rebuild
    assert rebuild(tmp_path / 'replay.sqlite3', batch.root) == 1
    assert rebuild(tmp_path / 'replay.sqlite3', batch.root) == 0


def test_crash_after_response_before_checkpoint_never_refetches(tmp_path, monkeypatch):
    batch, job = ready(tmp_path, FakeClient([page(1, 1)]))
    original = batch.save
    def crash():
        if job['next_page'] == 2:
            raise OSError('simulated crash before checkpoint commit')
        original()
    monkeypatch.setattr(batch, 'save', crash)
    with pytest.raises(OSError):
        batch.search('north_gwinnett', job)
    client = FakeClient([page(2, 2)])
    resumed = Batch(batch.db, batch.root, 1, 0, client=client)
    resumed.search('north_gwinnett', resumed.state['jobs']['north_gwinnett'])
    assert len(client.urls) == 1 and '2_p/' in client.urls[0]
    assert len(read_frames(batch.db, 'observed')[1]) == 2


@pytest.mark.parametrize('second', [page(2, 1), page(2, 2, 3)])
def test_changed_pagination_cannot_publish_complete(tmp_path, second):
    batch, job = ready(tmp_path, FakeClient([page(1, 1), second]), limit=2)
    with pytest.raises(ValueError, match='Pagination'):
        batch.search('north_gwinnett', job)
    assert not list(batch.root.glob('snapshots/*/*'))
    assert read_json(batch.path)['jobs']['north_gwinnett']['next_page'] == 2


def test_cooldown_performs_no_requests_and_budget_persists(tmp_path):
    batch, job = ready(tmp_path, FakeClient([AccessBlocked('HTTP 429')]))
    assert batch.run()['status'] == 'blocked'
    restored = Batch(batch.db, batch.root, client=FakeClient([]))
    assert restored.run()['status'] == 'cooldown'
    assert restored.client.urls == []
    assert sum(restored.state['requests'].values()) == 1


def test_delayed_wakeups_do_not_burst_requests_or_skip_school(tmp_path, monkeypatch):
    from tracker import batch as module
    batch, _ = ready(tmp_path, FakeClient([]))
    started = utcnow()
    batch.state['last_batch_started_at'] = started.isoformat()
    batch.state['turn'] = 1
    batch.save()
    monkeypatch.setattr(module, 'utcnow', lambda: started + timedelta(minutes=59))
    restored = Batch(batch.db, batch.root, client=FakeClient([]))
    assert restored.run()['status'] == 'interval_wait'
    assert restored.client.urls == [] and restored.state['turn'] == 1
    monkeypatch.setattr(module, 'utcnow', lambda: started + timedelta(hours=1))
    visited = []
    monkeypatch.setattr(restored, 'search', lambda school, job: (visited.append(school), job.update(finished_at=module.utcnow().isoformat())))
    monkeypatch.setattr(restored, 'details', lambda *args: None)
    assert restored.run()['status'] == 'complete'
    assert visited == ['johns_creek']
    assert read_json(restored.path)['turn'] == 2


def test_structured_resofacts_and_visible_year_with_identity():
    payload = dict(props=dict(pageProps=dict(componentProps=dict(gdpClientCache=json.dumps({'x': {'property': {
        'zpid': 123, 'yearBuilt': None, 'resoFacts': {'yearBuilt': 2014}}}})))))
    html = '<script id="__NEXT_DATA__">' + json.dumps(payload) + '</script>'
    assert extract_detail(html, 'zillow:123')['extracted_year'] == 2014
    with pytest.raises(ValueError, match='identity'):
        extract_detail(html, 'zillow:999')
    visible = '<link rel="canonical" href="https://www.zillow.com/homedetails/123_zpid/"><div>Built in <b>1998</b></div>'
    assert extract_detail(visible, 'zillow:123')['extracted_year'] == 1998
    assert extract_detail(visible.replace('1998', 'unknown'), 'zillow:123')['year_status'] == 'not_in_response'


def test_price_cut_from_search_and_stable_checksum():
    source = item()
    source['hdpData']['homeInfo'].update(priceChange=-30000, datePriceChanged=1788505200000)
    row = extract_search(source, utcnow().isoformat())
    assert row['price_cut'] == 30000 and row['price_cut_date'] == '2026-09-04'
    same = dict(row, price_observed_at='a later observation')
    assert facts_hash(row) == facts_hash(same)
    assert facts_hash(row) != facts_hash(dict(row, price=580000))
    other = dict(row, property_id='zillow:2', price=450000, price_cut=40000)
    frame = pd.DataFrame([row, other])
    ranked = rank_price_cuts(frame, pd.DataFrame())
    assert ranked.iloc[0].property_id == 'zillow:2'
    assert ranked.iloc[1].cut_percent == pytest.approx(30000 / 620000 * 100)


def test_outbox_recovers_without_duplicate_import(tmp_path, monkeypatch):
    batch, job = ready(tmp_path, FakeClient([page(1, 1), page(2, 2)]), limit=2)
    from tracker import batch as module
    original = module.write_json
    def fail_archive(path, value):
        if 'snapshots' in str(path):
            raise OSError('publication interrupted')
        original(path, value)
    monkeypatch.setattr(module, 'write_json', fail_archive)
    with pytest.raises(OSError):
        batch.search('north_gwinnett', job)
    assert len(read_frames(batch.db, 'observed')[0]) == 1
    monkeypatch.setattr(module, 'write_json', original)
    recovered = Batch(batch.db, batch.root, client=FakeClient([]))
    recovered.flush_outbox()
    assert len(read_frames(batch.db, 'observed')[0]) == 1
    assert len(list(batch.root.glob('snapshots/*/*'))) == 1


def test_out_of_band_result_never_commits_page(tmp_path):
    html = page(1, 1).replace('590000', '1000000')
    batch, job = ready(tmp_path, FakeClient([html]))
    with pytest.raises(ValueError, match='criteria'):
        batch.search('north_gwinnett', job)
    assert read_json(batch.path)['jobs']['north_gwinnett']['next_page'] == 1
    assert not job['rows']


def test_raw_replay_recovers_year_without_network(tmp_path):
    from tracker.batch import replay_details
    html = '<link rel="canonical" href="https://www.zillow.com/homedetails/123_zpid/"><div>Built in 2014</div>'
    batch, job = ready(tmp_path, FakeClient([html]))
    batch.response(job, 'https://www.zillow.com/homedetails/123_zpid/')
    manifest = tmp_path / 'manifest.json.gz'
    write_json(manifest, [job['response']])
    assert replay_details(batch.db, batch.root, manifest, batch.root / 'raw') == 1
    assert read_json(batch.path)['details']['zillow:123']['year_built'] == 2014
    assert len(batch.client.urls) == 1


def test_enrichment_keeps_original_market_day(tmp_path):
    batch, job = ready(tmp_path, FakeClient([page(1, 1), page(2, 2)]), limit=2)
    batch.search('north_gwinnett', job)
    prior = (utcnow() - timedelta(days=2)).isoformat()
    job.update(started_at=prior, finished_at=prior)
    record = batch.snapshot('north_gwinnett', job, 'source_complete')
    from tracker.storage import import_snapshot
    from tracker.batch import day
    run_id, _ = import_snapshot(batch.db, record)
    runs = read_frames(batch.db, 'observed')[0]
    assert runs[runs.run_id == run_id].iloc[0].market_date == day(prior)


def test_unknown_listing_episode_does_not_invent_observed_cut():
    row = extract_search(item(), utcnow().isoformat())
    row.update(school='north_gwinnett', observed_at='2026-10-02T12:00:00Z', market_date='2026-10-02')
    prior = dict(row, price=650000, observed_at='2026-10-01T12:00:00Z')
    result = rank_price_cuts(pd.DataFrame([row]), pd.DataFrame([prior]))
    assert pd.isna(result.iloc[0].cut_amount)
