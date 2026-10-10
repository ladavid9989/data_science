import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tests.test_app import APP
from tracker.flows import confirmed_sales, listing_flows
from tracker.storage import BAND_SCOPE, import_snapshot, read_frames


def home(pid, status='active', **extra):
    return dict(property_id=f'zillow:{pid}', episode_id=f'zillow:{pid}:unknown', address=f'{pid} Test St',
                price=600000, bedrooms=3, bathrooms=2, property_type='SINGLE_FAMILY', year_built=2000,
                status=status, evidence='Explicit fixture source status', url=f'https://www.zillow.com/homedetails/{pid}_zpid/', **extra)


def put(db, day, homes, school='north_gwinnett', quality='source_complete', zone='zone'):
    stamp = f'2026-10-{day:02d}T13:00:00Z'
    import_snapshot(db, dict(schema_version=1, dataset='observed', school=school, observed_at=stamp,
        quality=quality, scope=BAND_SCOPE + ':' + zone, boundary_version=zone, reported_count=len(homes),
        expected_unique_count=len(homes), coverage=dict(price_range=[400000, 700000], all_prices=False,
            all_pages=quality == 'source_complete', query_validated=quality == 'source_complete'),
        source='test fixture', listings=[dict(price_observed_at=stamp, **row) if 'price_observed_at' not in row else row for row in homes]))


def flow(db, start='2026-10-03', end='2026-10-03', schools=None, **filters):
    return listing_flows(*read_frames(db, 'observed'), schools or ['north_gwinnett'], start, end, **filters)


def test_flows_reconcile_and_absence_is_not_a_sale(tmp_path):
    db = tmp_path / 'db'
    put(db, 2, [home(1), home(2), home(3), home(4), home(5, 'pending'), home(6)])
    put(db, 3, [home(2), home(3, 'pending'), home(4, 'Closed', in_inventory=False, sold_date='2026-10-03', sold_price=580000,
                price_observed_at='2026-10-02T13:00:00Z', status_observed_at='2026-10-03T13:00:00Z'),
                home(5), home(6, 'withdrawn', in_inventory=False), home(7), home(8)])
    daily, events = flow(db)
    row = daily.iloc[0]
    assert row.entered == 3 and row.left == 4 and row.net == -1
    assert row.net == row.entered - row.left
    assert row.first_observed == 2 and row.reactivated == 1
    assert row.to_contract == row.to_sold == row.withdrawn == row.unexplained_left == 1
    assert events.set_index('property_id').loc['zillow:1', 'reason'] == 'unexplained_left'
    sales = confirmed_sales(*read_frames(db, 'observed'), ['north_gwinnett'], '2026-10-03')
    assert sales.property_id.tolist() == ['zillow:4']


def test_first_snapshot_gaps_and_reappearance(tmp_path):
    db = tmp_path / 'db'
    put(db, 2, [home(1)])
    put(db, 3, [])
    put(db, 4, [home(1)])
    put(db, 6, [home(1), home(2)])
    daily, events = flow(db, '2026-10-02', '2026-10-06')
    daily = daily.set_index('date')
    assert pd.isna(daily.loc['2026-10-02', 'entered'])
    assert daily.loc['2026-10-03', 'left'] == 1
    assert daily.loc['2026-10-04', 'reappeared'] == 1
    assert daily.loc['2026-10-04', 'first_observed'] == 0
    assert daily.loc[['2026-10-05', '2026-10-06'], 'entered'].isna().all()
    assert len(events) == 2


@pytest.mark.parametrize('issue', ['partial', 'scope', 'stale'])
def test_incomplete_incompatible_or_stale_comparison_is_not_zero(tmp_path, issue):
    db = tmp_path / 'db'
    put(db, 2, [home(1)])
    put(db, 3, [home(2, price_observed_at='2026-10-02T13:00:00Z' if issue == 'stale' else '2026-10-03T13:00:00Z')],
        quality='partial' if issue == 'partial' else 'source_complete', zone='new' if issue == 'scope' else 'zone')
    daily, events = flow(db)
    assert not daily.iloc[0].flow_complete and pd.isna(daily.iloc[0].entered)
    assert events.empty


def test_filter_entry_is_not_first_observation(tmp_path):
    db = tmp_path / 'db'
    older = home(1)
    older['year_built'] = 1990
    put(db, 2, [older])
    put(db, 3, [home(1)])
    daily, _ = flow(db, years=(2000, 2030))
    assert daily.iloc[0].filter_entered == 1 and daily.iloc[0].first_observed == 0


def test_overlapping_school_movement_is_not_combined_market_entry(tmp_path):
    db = tmp_path / 'db'
    put(db, 2, [home(1)])
    put(db, 3, [])
    put(db, 2, [], school='johns_creek')
    put(db, 3, [home(1)], school='johns_creek')
    daily, _ = flow(db, schools=['north_gwinnett', 'johns_creek'])
    daily = daily.set_index('school')
    assert daily.loc['north_gwinnett', 'left'] == 1
    assert daily.loc['johns_creek', 'entered'] == 1
    assert daily.loc['__all__', 'entered'] == daily.loc['__all__', 'left'] == daily.loc['__all__', 'net'] == 0


def test_cached_followup_status_does_not_invalidate_fresh_search(tmp_path):
    db = tmp_path / 'db'
    closed = home(9, 'sold', in_inventory=False, price_observed_at='2026-10-01T13:00:00Z')
    put(db, 2, [home(1), closed])
    put(db, 3, [home(1), home(2), closed])
    daily, _ = flow(db)
    assert daily.iloc[0].flow_complete and daily.iloc[0].entered == 1


def test_sale_confirmation_retains_unknown_dates_and_later_detail(tmp_path):
    db = tmp_path / 'db'
    put(db, 2, [home(1), home(2), home(3)])
    put(db, 3, [home(1, 'sold', in_inventory=False), home(2, 'sold', in_inventory=False)])
    put(db, 4, [home(1, 'sold', in_inventory=False, sold_date='2026-10-02', sold_price=750000),
                home(2, 'sold', in_inventory=False), home(3, 'pending')])
    rows = confirmed_sales(*read_frames(db, 'observed'), ['north_gwinnett'], '2026-10-04').set_index('property_id')
    assert len(rows) == 2
    assert rows.loc['zillow:1', 'confirmed_date'] == '2026-10-03'
    assert rows.loc['zillow:1', 'sold_price'] == 750000  # Closing price is not the asking-price filter.
    assert pd.isna(rows.loc['zillow:2', 'sold_date'])
    assert confirmed_sales(*read_frames(db, 'observed'), ['north_gwinnett'], '2026-10-02').empty


def test_untracked_sold_property_is_not_a_tracked_sale(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [home(1, 'sold', in_inventory=False), home(2, 'pending')])
    assert confirmed_sales(*read_frames(db, 'observed'), ['north_gwinnett'], '2026-10-03').empty


def test_flow_ui_controls_and_evidence_tables(tmp_path, monkeypatch):
    db = tmp_path / 'db'
    put(db, 2, [home(1)])
    put(db, 3, [home(1, 'closed', in_inventory=False), home(2)])
    monkeypatch.setenv('HOUSING_DB_PATH', str(db))
    monkeypatch.setenv('HOUSING_OFFLINE', '1')
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.selectbox(key='school').select_index(1).run()
    assert not app.exception
    assert app.selectbox(key='flow_window').value == '최근 7일'
    app.selectbox(key='flow_window').select('최근 1일').run()
    assert not app.exception
    cards = {metric.label: metric.value for metric in app.metric}
    assert cards['판매 중 목록 진입'] == cards['판매 중 목록 이탈'] == cards['기간 내 판매 완료 확인'] == '1'
    assert cards['매물 순증감'] == '+0'
    assert any('분류' in table.value.columns for table in app.dataframe)
    assert any('최초 확인일 (ET)' in table.value.columns for table in app.dataframe)
