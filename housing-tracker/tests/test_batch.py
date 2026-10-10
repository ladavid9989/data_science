import copy
import json
from datetime import timedelta

import pandas as pd
import pytest

from tracker.batch import Batch, BatchFull, PRICE_RANGE, utcnow
from tracker.collect import AccessBlocked, SOURCES, filters, read_json, write_json
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
    monkeypatch.setattr(module, 'utcnow', lambda: started + timedelta(minutes=24))
    restored = Batch(batch.db, batch.root, client=FakeClient([]))
    assert restored.run()['status'] == 'interval_wait'
    assert restored.client.urls == [] and restored.state['turn'] == 1
    monkeypatch.setattr(module, 'utcnow', lambda: started + timedelta(minutes=29, seconds=55))
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


def completed_schools(batch, job):
    stamp = utcnow().isoformat()
    job.update(finished_at=stamp, published=True, total=2, next_page=3,
               rows={f'zillow:{pid}': extract_search(item(pid), stamp) for pid in (1, 2)})
    other = copy.deepcopy(job)
    other['rows'] = {'zillow:3': dict(extract_search(item(3), stamp), year_built=2005)}
    batch.state['jobs']['johns_creek'] = other
    for school in SOURCES:
        if school not in batch.state['jobs']:
            batch.state['jobs'][school] = dict(copy.deepcopy(other), rows={})
    batch.state['details']['zillow:3'] = dict(year_built=2005, next_check=(utcnow() + timedelta(days=90)).isoformat())
    batch.state['turn'] = 1  # Previously this wasted a batch on the completed school.
    return other


def detail_html(pid, year):
    return f'<link rel="canonical" href="https://www.zillow.com/homedetails/{pid}_zpid/"><div>Built in {year}</div>'


@pytest.mark.parametrize('school', ['chattahoochee', 'northview'])
def test_existing_checkpoint_bootstraps_new_school_without_reset(tmp_path, school):
    batch, job = ready(tmp_path, FakeClient([]))
    completed_schools(batch, job)
    batch.state['jobs'].pop(school)
    batch.state['turn'] = 0
    before = copy.deepcopy(batch.state)
    batch.save()
    restored = Batch(batch.db, batch.root, client=FakeClient([]))
    assert restored.choose_school(utcnow().isoformat()) == school
    assert restored.state == before
    # Once started, finish its saved pages before refreshing an older full search.
    restored.state['jobs'][school] = dict(started_at=utcnow().isoformat(), next_page=2)
    later = (utcnow() + timedelta(hours=2)).isoformat()
    assert restored.choose_school(later) == school


def interrupted_page_one(tmp_path):
    batch, job = ready(tmp_path, FakeClient([page(1, 1)]))
    original = copy.deepcopy(job)
    completed_schools(batch, job)
    batch.state['jobs']['north_gwinnett'] = original
    with pytest.raises(BatchFull):
        batch.search('north_gwinnett', original)
    return batch


@pytest.mark.parametrize('changed', [page(2, 1), page(2, 2, 3)])
def test_live_pagination_change_restarts_and_reconciles_within_budget(tmp_path, changed):
    old = interrupted_page_one(tmp_path)
    client = FakeClient([changed, page(1, 3), page(2, 4)])
    resumed = Batch(old.db, old.root, 3, 0, client=client)
    result = resumed.run()
    assert result['status'] == 'complete' and result['requests'] == 3
    assert result['recovery_reason'].startswith('Pagination')
    job = resumed.state['jobs']['north_gwinnett']
    assert set(job['rows']) == {'zillow:3', 'zillow:4'}
    assert job['next_page'] == 3 and job['finished_at']
    runs, rows = read_frames(old.db, 'observed')
    selected = canonical_runs(runs)
    assert selected.iloc[0].row_count == 2
    assert set(rows[rows.run_id.isin(selected.run_id)].property_id) == {'zillow:3', 'zillow:4'}
    assert runs.quality.eq('partial').any()


def test_drift_at_budget_limit_saves_fresh_bookmark_then_resumes(tmp_path, monkeypatch):
    from tracker import batch as module
    old = interrupted_page_one(tmp_path)
    resumed = Batch(old.db, old.root, 1, 0, client=FakeClient([page(2, 2, 3)]))
    result = resumed.run()
    assert result['status'] == 'checkpointed' and result['error'] is None
    checkpoint = read_json(resumed.path)['jobs']['north_gwinnett']
    assert checkpoint['next_page'] == 1 and not checkpoint['rows']
    assert 'response' not in checkpoint and 'total' not in checkpoint
    assert not canonical_runs(read_frames(old.db, 'observed')[0]).shape[0]
    later = utcnow() + timedelta(minutes=26)
    monkeypatch.setattr(module, 'utcnow', lambda: later)
    fresh = Batch(old.db, old.root, 2, 0, client=FakeClient([page(1, 3), page(2, 4)]))
    assert fresh.run()['status'] == 'complete'
    assert set(fresh.state['jobs']['north_gwinnett']['rows']) == {'zillow:3', 'zillow:4'}


def test_finished_school_yields_to_missing_years_and_publishes_one_batch(tmp_path):
    client = FakeClient([detail_html(2, 2000), detail_html(1, 2016)])
    batch, job = ready(tmp_path, client, limit=2)
    completed_schools(batch, job)
    batch.detail_limit = 2
    job['rows']['zillow:2']['price_cut'] = 30000
    result = batch.run()
    assert result['school'] == 'north_gwinnett'
    assert result['detail_requests'] == result['years_added'] == 2
    assert result['enrichment']['north_gwinnett']['missing'] == 0
    assert client.urls[0].endswith('/2_zpid/')
    assert len(list(batch.root.glob('snapshots/*/*'))) == 1
    assert set(read_frames(batch.db, 'observed')[1].year_built) == {2000, 2016}


def test_idle_does_not_consume_a_batch_slot(tmp_path):
    batch, job = ready(tmp_path, FakeClient([]))
    completed_schools(batch, job)
    job['rows'] = {}
    batch.detail_limit = 2
    assert batch.run()['status'] == 'idle'
    assert 'last_batch_started_at' not in batch.state
    assert batch.state['turn'] == 1


def test_enrichment_checkpoint_survives_request_budget(tmp_path):
    batch, job = ready(tmp_path, FakeClient([detail_html(1, 2000)]), limit=1)
    completed_schools(batch, job)
    batch.detail_limit = 2
    result = batch.run()
    assert result['status'] == 'checkpointed'
    assert result['enrichment']['north_gwinnett']['known'] == 1
    assert len(list(batch.root.glob('snapshots/*/*'))) == 1
    assert batch.state['details']['zillow:1']['year_built'] == 2000


def test_daily_budget_still_limits_more_frequent_batches(tmp_path):
    from tracker.batch import day, DAILY_REQUEST_LIMIT
    batch, job = ready(tmp_path, FakeClient([]))
    completed_schools(batch, job)
    batch.state['requests'] = {day(utcnow().isoformat()): DAILY_REQUEST_LIMIT}
    assert batch.run()['status'] == 'daily_budget_wait'
    assert not batch.client.urls


def test_cached_details_publish_after_crash_without_new_request(tmp_path):
    batch, job = ready(tmp_path, FakeClient([detail_html(1, 2000)]))
    completed_schools(batch, job)
    batch.detail_limit = 1
    batch.details('north_gwinnett', job)
    assert not list(batch.root.glob('snapshots/*/*'))
    resumed = Batch(batch.db, batch.root, client=FakeClient([]))
    resumed.state['last_batch_started_at'] = utcnow().isoformat()
    assert resumed.run()['status'] == 'interval_wait'
    assert len(list(batch.root.glob('snapshots/*/*'))) == 1
    assert not resumed.client.urls


def test_disappearance_status_check_does_not_wait_for_year_refresh(tmp_path):
    batch, job = ready(tmp_path, FakeClient([]))
    row = extract_search(item(1), utcnow().isoformat())
    job['watch'] = {'zillow:1': row}
    batch.state['details']['zillow:1'] = dict(year_built=2000, next_check=(utcnow() + timedelta(days=90)).isoformat())
    assert batch.detail_candidates(job)[0][-1] == 'zillow:1'
    batch.state['details']['zillow:1']['status_next_check'] = (utcnow() + timedelta(days=1)).isoformat()
    assert batch.detail_candidates(job) == []


def test_closed_followup_retains_last_asking_price_and_sale_evidence(tmp_path, monkeypatch):
    from tracker import batch as module
    stamp = utcnow().isoformat()
    batch, job = ready(tmp_path, FakeClient(['fixture detail']))
    batch.detail_limit = 1
    asking_stamp = (utcnow() - timedelta(days=2)).isoformat()
    row = extract_search(item(1, price=690000), asking_stamp)
    row['first_seen'] = asking_stamp
    job['watch'] = {'zillow:1': row}
    monkeypatch.setattr(module, 'extract_detail', lambda *args: dict(homeStatus='CLOSED', price=720000,
        extracted_year=2000, year_status='verified', year_source='fixture',
        priceHistory=[dict(event='Sold', price=720000, date=stamp[:10])]))
    batch.details('north_gwinnett', job)
    saved = job['followed']['zillow:1']
    assert saved['price'] == 690000 and saved['sold_price'] == 720000
    assert saved['sold_date'] == stamp[:10] and saved['status'] == 'sold'
    assert saved['price_observed_at'] == asking_stamp
    assert saved['status_observed_at'] > asking_stamp
    assert 'Explicit source sold event' in saved['evidence']
    assert batch.detail_candidates(job) == []


def test_missing_off_market_price_keeps_status_followup_eligible(tmp_path, monkeypatch):
    from tracker import batch as module
    batch, job = ready(tmp_path, FakeClient(['fixture detail']))
    batch.detail_limit = 1
    original_stamp = (utcnow() - timedelta(days=2)).isoformat()
    job['watch'] = {'zillow:1': extract_search(item(1), original_stamp)}
    monkeypatch.setattr(module, 'extract_detail', lambda *args: dict(homeStatus='OTHER', price=None,
        extracted_year=2000, year_status='verified', year_source='fixture'))
    batch.details('north_gwinnett', job)
    saved = job['followed']['zillow:1']
    assert saved['status'] == 'off_market_unknown' and saved['price'] == 590000
    assert saved['price_observed_at'] == original_stamp
    assert 'zillow:1' in job['watch']


def test_same_day_search_refresh_discovers_new_listings_and_changed_prices(tmp_path, monkeypatch):
    from tracker import batch as module
    start = utcnow()
    client = FakeClient([page(1, 2).replace('590000', '500000'), page(2, 4)])
    batch, job = ready(tmp_path, client, limit=2)
    completed_schools(batch, job)
    batch.detail_limit = 0
    batch.state['turn'] = 0
    monkeypatch.setattr(module, 'utcnow', lambda: start + timedelta(hours=1, minutes=1))
    monkeypatch.setattr(module, 'zone_for', lambda *a: job['zone'])
    result = batch.run()
    fresh = batch.state['jobs']['north_gwinnett']
    assert result['school'] == 'north_gwinnett'
    assert set(fresh['rows']) == {'zillow:2', 'zillow:4'}
    assert fresh['rows']['zillow:2']['price'] == 500000
    assert 'zillow:1' in fresh['watch']
    assert len(client.urls) == 2


def test_property_comparison_shows_cut_without_listing_episode_id():
    from tracker.metrics import changes_between
    row = dict(property_id='zillow:58608398', episode_id='zillow:58608398:unknown', school='north_gwinnett')
    before = pd.DataFrame([dict(row, price=599000)])
    after = pd.DataFrame([dict(row, price=500000)])
    result = changes_between(before, after)
    assert len(result) == 1 and result.iloc[0].price_change == -99000
    assert result.iloc[0].price_change_percent == pytest.approx(-16.5275459)
    assert changes_between(before.assign(episode_id='first'), after.assign(episode_id='second')).empty
