import json

import pytest

from tests.test_batch import FakeClient, item, ready
from tracker.collect import filters, read_json
from tracker.batch import PaginationDrift, PRICE_RANGE
from tracker.storage import read_frames


def page(number, items, total=3):
    state = dict(queryState=dict(schoolId=102507, filterState=filters(*PRICE_RANGE), pagination=dict(currentPage=number)),
                 cat1=dict(searchList=dict(totalResultCount=total, totalPages=2), searchResults=dict(listResults=items)))
    return '<script id="__NEXT_DATA__">' + json.dumps(dict(props=dict(pageProps=dict(searchPageState=state)))) + '</script>'


def auction():
    value = item(9, 0)
    value.update(statusText='Auction', zestimate=584000, shouldShowZestimateAsPrice=True)
    value['hdpData']['homeInfo']['listing_sub_type'] = {'is_forAuction': True}
    return value


def test_unpriced_auction_is_reconciled_but_not_saved_as_inventory(tmp_path):
    client = FakeClient([page(1, [item(1), auction()]), page(2, [item(2)])])
    batch, job = ready(tmp_path, client, limit=2)
    job['previous'] = {'zillow:9': dict(status='active', price=600000)}
    batch.search('north_gwinnett', job)
    runs, rows = read_frames(batch.db, 'observed')
    assert runs.quality.tolist() == ['source_complete']
    assert runs.reported_count.tolist() == [3]
    assert set(rows.property_id) == {'zillow:1', 'zillow:2'}
    assert 'zillow:9' not in job['watch']
    assert set(job['ids']) == {'zillow:1', 'zillow:2', 'zillow:9'}
    snapshot = read_json(next(batch.root.glob('snapshots/*/*.json.gz')))
    assert snapshot['expected_unique_count'] == 2
    assert snapshot['excluded_search_results'][0]['reason'] == 'unpriced_auction'


def test_excluded_auction_still_counts_for_duplicate_detection(tmp_path):
    batch, job = ready(tmp_path, FakeClient([page(1, [item(1), auction()]), page(2, [auction()])]), limit=2)
    with pytest.raises(PaginationDrift, match='duplicate'):
        batch.search('north_gwinnett', job)
    assert not job.get('finished_at')


def test_unknown_zero_price_is_not_silently_excluded(tmp_path):
    batch, job = ready(tmp_path, FakeClient([page(1, [item(1), item(9, 0)])]), limit=2)
    with pytest.raises(ValueError, match='criteria'):
        batch.search('north_gwinnett', job)
    assert not job['rows'] and not job['ids']
