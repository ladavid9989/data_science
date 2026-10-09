from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.scenarios import seed, snapshots
from tracker.storage import import_snapshot

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "app.sqlite3"
    monkeypatch.setenv("HOUSING_DB_PATH", str(db))
    monkeypatch.setenv("HOUSING_OFFLINE", "1")
    seed(db)
    return AppTest.from_file(APP, default_timeout=30).run()


def test_default_dashboard_and_filters(app):
    assert not app.exception
    assert app.title[0].value == "학군으로 보는 주택 시장"
    assert len(app.tabs) == 4
    assert not app.radio
    assert not app.toggle
    assert not app.number_input
    app.selectbox(key="school").select("Johns Creek High School").run()
    assert not app.exception
    app.checkbox(key="unknown").uncheck().run()
    assert not app.exception
    app.selectbox(key="school").select("Chattahoochee High School").run()
    assert not app.exception
    assert int(app.metric[0].value) > 0


def test_new_school_complete_search_has_metrics_and_price_history(tmp_path, monkeypatch):
    from tests.test_alerts import put
    db = tmp_path / 'new-school.sqlite3'
    put(db, 3, [600000], school='chattahoochee')
    put(db, 4, [570000], school='chattahoochee')
    monkeypatch.setenv('HOUSING_DB_PATH', str(db))
    monkeypatch.setenv('HOUSING_OFFLINE', '1')
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.selectbox(key='school').select('Chattahoochee High School').run()
    assert not app.exception
    assert app.metric[0].value == '1'
    assert app.metric[1].value == '$570,000'
    assert app.selectbox(key='change_window').value == '최근 7일'
    changes = next(d.value for d in app.dataframe if '변화 ($)' in d.value.columns)
    assert changes['변화 ($)'].tolist() == [-30000]


def test_observed_partial_does_not_show_market_median(tmp_path, monkeypatch):
    db = tmp_path / "partial.sqlite3"
    monkeypatch.setenv("HOUSING_DB_PATH", str(db))
    monkeypatch.setenv("HOUSING_OFFLINE", "1")
    sample = next(snapshots())
    sample.update(quality="partial", boundary_version="unverified", scope="sample")
    import_snapshot(db, sample)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    assert app.metric[1].value == "미산출"
    assert any("완전 수집 기록" in warning.value for warning in app.warning)
    app.selectbox(key="school").select("Johns Creek High School").run()
    assert not app.exception
    assert any("관측 기록이 없습니다" in info.value for info in app.info)


def test_failed_runs_render_without_invented_inventory(tmp_path, monkeypatch):
    db = tmp_path / "failed.sqlite3"
    monkeypatch.setenv("HOUSING_DB_PATH", str(db))
    monkeypatch.setenv("HOUSING_OFFLINE", "1")
    sample = next(snapshots())
    sample.update(quality="failed", listings=[])
    import_snapshot(db, sample)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    assert app.metric[1].value == "미산출"


def test_empty_result_filters(app):
    app.selectbox(key="beds").select(6).run()
    assert not app.exception
    assert app.metric[0].value == "0"
