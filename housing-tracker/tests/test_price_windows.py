from pathlib import Path

from streamlit.testing.v1 import AppTest

from tracker.metrics import price_change_history
from tracker.storage import BAND_SCOPE, import_snapshot, read_frames


def record(db, stamp, price, *, price_stamp=None, quality='source_complete', episode='unknown',
           year=2001, boundary='zone', present=True):
    rows = [dict(property_id='zillow:1', episode_id=f'zillow:1:{episode}', address='1 Test St',
                 price=price, bedrooms=3, bathrooms=2, property_type='SINGLE_FAMILY',
                 status='active', year_built=year, price_observed_at=price_stamp or stamp)] if present else []
    import_snapshot(db, dict(schema_version=1, dataset='observed', school='north_gwinnett',
        observed_at=stamp, quality=quality, scope=BAND_SCOPE + ':' + boundary, boundary_version=boundary,
        reported_count=len(rows), expected_unique_count=len(rows), source='test fixture',
        coverage=dict(price_range=[400000, 700000], all_pages=quality == 'source_complete',
                      all_prices=False, query_validated=quality == 'source_complete'), listings=rows))


def history(db, start='2026-10-01', end='2026-10-10', **filters):
    return price_change_history(*read_frames(db, 'observed'), start, end, **filters)


def test_window_keeps_each_move_and_uses_baseline_before_start(tmp_path):
    db = tmp_path / 'db'
    for day, price in [(1, 650000), (2, 600000), (5, 550000), (10, 575000)]:
        record(db, f'2026-10-{day:02d}T13:00:00Z', price)
    assert history(db, '2026-10-10').price_change.tolist() == [25000]
    assert history(db, '2026-10-04').price_change.tolist() == [25000, -50000]
    assert history(db, '2026-09-11').price_change.tolist() == [25000, -50000, -50000]
    assert history(db, '2026-10-02', '2026-10-05').price_change.tolist() == [-50000, -50000]


def test_intraday_reversal_is_not_erased_or_repeated_by_enrichment(tmp_path):
    db = tmp_path / 'db'
    record(db, '2026-10-05T13:00:00Z', 600000)
    record(db, '2026-10-06T13:00:00Z', 500000)
    record(db, '2026-10-06T14:00:00Z', 500000, price_stamp='2026-10-06T13:00:00Z')
    record(db, '2026-10-06T15:00:00Z', 600000)
    record(db, '2026-10-07T13:00:00Z', 600000)
    events = history(db, '2026-10-06', '2026-10-07')
    assert events.price_change.tolist() == [100000, -100000]
    assert events.change_date.astype(str).tolist() == ['2026-10-06', '2026-10-06']


def test_eastern_date_gap_filters_and_removed_listing(tmp_path):
    db = tmp_path / 'db'
    record(db, '2026-10-02T13:00:00Z', 599000)
    record(db, '2026-10-04T13:00:00Z', 520000, quality='partial')
    record(db, '2026-10-06T02:00:00Z', 500000)  # October 5 in New York.
    record(db, '2026-10-07T13:00:00Z', 500000, present=False)
    events = history(db, '2026-10-05', '2026-10-07')
    assert events.price_change.tolist() == [-99000]
    assert str(events.iloc[0].change_date) == '2026-10-05'
    assert history(db, '2026-10-06', '2026-10-07').empty
    assert history(db, years=(2010, 2030)).empty


def test_relisting_and_scope_changes_are_not_price_changes(tmp_path):
    db = tmp_path / 'db'
    record(db, '2026-10-01T13:00:00Z', 600000, episode='first')
    record(db, '2026-10-02T13:00:00Z', 550000, episode='second')
    assert history(db).empty
    record(db, '2026-10-03T13:00:00Z', 500000, episode='second', boundary='new-zone')
    assert history(db).empty


def test_dashboard_window_controls_and_persistent_history(tmp_path, monkeypatch):
    db = tmp_path / 'db'
    for day, price in [(1, 650000), (2, 600000), (5, 550000), (10, 575000)]:
        record(db, f'2026-10-{day:02d}T13:00:00Z', price)
    monkeypatch.setenv('HOUSING_DB_PATH', str(db))
    monkeypatch.setenv('HOUSING_OFFLINE', '1')
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'streamlit_app.py', default_timeout=30).run()
    app.selectbox(key='school').select_index(1).run()

    def displayed_changes():
        assert not app.exception
        return next(frame.value for frame in app.dataframe if '변화 ($)' in frame.value.columns)['변화 ($)'].tolist()

    assert app.selectbox(key='change_window').value == '최근 7일'
    assert displayed_changes() == [25000, -50000]
    app.selectbox(key='change_window').select('최근 1일').run()
    assert displayed_changes() == [25000]
    app.selectbox(key='change_window').select('최근 30일').run()
    assert displayed_changes() == [25000, -50000, -50000]
    app.selectbox(key='change_window').select('선택 기간 전체').run()
    assert displayed_changes() == [25000, -50000, -50000]
