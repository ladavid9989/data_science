from datetime import date

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tests.test_alerts import put
from tests.test_app import APP
from tests.test_price_windows import record
from tracker.metrics import daily_metrics, rolling_market_metrics
from tracker.storage import read_frames


def weekly(db, day='2026-10-10', schools=None, **filters):
    return rolling_market_metrics(*read_frames(db, 'observed'), schools or ['north_gwinnett'], day, day, **filters)


def test_equal_weight_includes_unchanged_and_excludes_newcomers(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [600000, 500000, 600000])
    put(db, 5, [570000, 500000, 600000])
    put(db, 10, [540000, 500000, 630000, 650000])
    result = weekly(db).iloc[0]
    assert result.weekly_ready
    assert result.active == 4 and result.active_change_7d == 1
    assert result.comparable_count == 3 and result.comparison_coverage == 75
    assert result.mean_change_7d == pytest.approx((-10 + 0 + 5) / 3)
    assert result.cut_count == 1 and result.cut_share_7d == pytest.approx(100 / 3)
    assert result.cut_event_count == 2
    assert result.median_cut_percent == pytest.approx((5 + 30000 / 570000 * 100) / 2)
    assert result.observed_days == 3


def test_reversals_still_count_as_cuts_but_not_net_declines(tmp_path):
    db = tmp_path / 'db'
    record(db, '2026-10-03T13:00:00Z', 600000)
    record(db, '2026-10-06T13:00:00Z', 540000)
    record(db, '2026-10-06T14:00:00Z', 540000, price_stamp='2026-10-06T13:00:00Z')
    record(db, '2026-10-06T15:00:00Z', 600000)
    record(db, '2026-10-10T13:00:00Z', 600000)
    result = weekly(db).iloc[0]
    assert result.mean_change_7d == 0
    assert result.cut_share_7d == 100 and result.cut_event_count == 1
    assert result.median_cut_percent == 10


@pytest.mark.parametrize('issue', ['missing_baseline', 'partial', 'stale', 'scope'])
def test_no_invented_weekly_baseline(tmp_path, issue):
    db = tmp_path / 'db'
    put(db, 4 if issue == 'missing_baseline' else 3, [600000])
    put(db, 10, [540000], quality='partial' if issue == 'partial' else 'source_complete',
        price_day=9 if issue == 'stale' else 10, boundary='new' if issue == 'scope' else 'zone')
    result = weekly(db).iloc[0]
    assert not result.weekly_ready
    assert pd.isna(result.mean_change_7d) and pd.isna(result.cut_share_7d)


def test_known_relisting_hidden_by_unknown_endpoints_is_excluded(tmp_path):
    db = tmp_path / 'db'
    for day, episode, price in [(3, 'unknown', 600000), (4, 'one', 580000), (6, 'two', 550000), (10, 'unknown', 540000)]:
        put(db, day, [price], episode=episode)
    result = weekly(db).iloc[0]
    assert result.weekly_ready and result.comparable_count == 0
    assert pd.isna(result.mean_change_7d) and pd.isna(result.cut_share_7d)


def test_school_totals_deduplicate_homes_and_wait_for_new_school(tmp_path):
    db = tmp_path / 'db'
    schools = ['north_gwinnett', 'johns_creek']
    for school in schools:
        put(db, 3, [600000], school=school)
        put(db, 10, [540000], school=school)
    result = weekly(db, schools=schools).set_index('school')
    assert result.loc['__all__', 'active'] == 1
    assert result.loc['__all__', 'comparable_count'] == 1
    assert result.loc['__all__', 'cut_event_count'] == 1
    put(db, 10, [510000], school='northview')
    result = weekly(db, schools=schools + ['northview']).set_index('school')
    assert result.loc['north_gwinnett', 'mean_change_7d'] == -10
    assert not result.loc['__all__', 'weekly_ready']
    assert pd.isna(result.loc['__all__', 'mean_change_7d'])


def test_filters_apply_to_both_endpoints_and_no_cut_is_not_missing(tmp_path):
    db = tmp_path / 'db'
    record(db, '2026-10-03T13:00:00Z', 600000, year=1990)
    record(db, '2026-10-10T13:00:00Z', 600000, year=1990)
    result = weekly(db).iloc[0]
    assert result.mean_change_7d == 0 and result.cut_share_7d == 0
    assert pd.isna(result.median_cut_percent)
    result = weekly(db, years=(2000, 2030)).iloc[0]
    assert result.active == 0 and result.comparable_count == 0
    assert pd.isna(result.cut_share_7d)


def test_aggregate_weights_properties_not_school_averages(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [600000, 500000, 500000])
    put(db, 10, [540000, 500000, 500000])
    put(db, 3, [600000], school='johns_creek')
    put(db, 10, [660000], school='johns_creek')
    runs, obs = read_frames(db, 'observed')
    # Different homes in the second school (put otherwise uses the same IDs).
    jc = obs.run_id.isin(runs.loc[runs.school.eq('johns_creek'), 'run_id'])
    obs.loc[jc, 'property_id'] = 'zillow:4'
    result = rolling_market_metrics(runs, obs, ['north_gwinnett', 'johns_creek'], '2026-10-10', '2026-10-10')
    total = result[result.school.eq('__all__')].iloc[0]
    assert total.comparable_count == 4 and total.mean_change_7d == 0
    assert total.cut_share_7d == 25


def test_historical_source_badge_and_prebaseline_cut_are_not_weekly_cuts(tmp_path):
    db = tmp_path / 'db'
    put(db, 2, [600000])
    put(db, 3, [540000])
    put(db, 10, [540000])
    runs, obs = read_frames(db, 'observed')
    obs['price_cut'] = 60000
    obs['price_cut_date'] = '2026-10-03'
    result = rolling_market_metrics(runs, obs, ['north_gwinnett'], '2026-10-10', '2026-10-10').iloc[0]
    assert result.mean_change_7d == 0 and result.cut_share_7d == 0
    assert result.cut_event_count == 0


def test_historical_range_does_not_use_a_future_search_scope(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [600000])
    put(db, 10, [570000])
    put(db, 11, [500000], boundary='new-zone')
    runs, obs = read_frames(db, 'observed')
    daily = daily_metrics(runs, obs, ['north_gwinnett'], '2026-10-10', '2026-10-10').iloc[0]
    assert daily.active == 1 and daily.median_price == 570000
    assert weekly(db).iloc[0].mean_change_7d == -5


def test_eastern_dates_and_weekly_baseline_outside_visible_range(tmp_path, monkeypatch):
    db = tmp_path / 'db'
    record(db, '2026-10-04T02:00:00Z', 600000)  # October 3 ET
    record(db, '2026-10-11T02:00:00Z', 540000)  # October 10 ET
    assert weekly(db).iloc[0].mean_change_7d == -10
    monkeypatch.setenv('HOUSING_DB_PATH', str(db))
    monkeypatch.setenv('HOUSING_OFFLINE', '1')
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.selectbox(key='school').select_index(1).run()
    app.date_input[0].set_value((date(2026, 10, 10), date(2026, 10, 10))).run()
    assert not app.exception
    assert app.metric[0].value == '1'
    assert app.metric[1].value == '100.00%'
    assert app.metric[2].value == '-10.00%'
    assert app.metric[3].value == '10.00%'
    assert any(header.value == '일별 매물 수' for header in app.subheader)
    assert any('중간' in caption.value or '수집 사이' in caption.value for caption in app.caption)
