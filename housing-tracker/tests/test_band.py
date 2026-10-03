from copy import deepcopy

import pytest
from streamlit.testing.v1 import AppTest

from tests.scenarios import snapshots
from tracker.band import in_band, prune_archive, prune_database, restrict_snapshot
from tracker.collect import write_json, read_json
from tracker.storage import import_snapshot, read_frames


def mixed():
    sample = next(snapshots())
    sample['listings'] = sample['listings'][:4]
    for row, price in zip(sample['listings'], [400000, 700000, 1199999, 399999]):
        row['price'] = price
    sample['listings'][2]['address'] = '3560 Allee Elm Dr, Johns Creek, GA 30022'
    sample['expected_unique_count'] = len(sample['listings'])
    return sample


def test_inclusive_band_and_atomic_database_cleanup(tmp_path):
    assert in_band(400000) and in_band(700000)
    assert not in_band(None) and not in_band(700001)
    db = tmp_path / 'x.sqlite3'
    sample = mixed()
    import_snapshot(db, sample)
    assert prune_database(db) == 2
    assert prune_database(db) == 0
    runs, rows = read_frames(db, 'observed')
    assert set(rows.price) == {400000, 700000}
    assert runs.iloc[0].row_count == 2
    assert runs.iloc[0].quality == 'partial'
    assert 'Allee Elm' not in ' '.join(rows.address)


def test_cleanup_failure_rolls_back_all_records(tmp_path, monkeypatch):
    from tracker import band
    db = tmp_path / 'x.sqlite3'
    import_snapshot(db, mixed())
    def fail(*args):
        raise ValueError('Invalid replacement')
    monkeypatch.setattr(band, 'insert_snapshot', fail)
    with pytest.raises(ValueError):
        prune_database(db)
    assert len(read_frames(db, 'observed')[1]) == 4


def test_archive_cleanup_and_rebuild_cannot_restore_noise(tmp_path):
    from tracker.archive import rebuild
    root = tmp_path / 'archive'
    sample = mixed()
    path = root / 'snapshots/2026-08-31/legacy.json.gz'
    write_json(path, sample)
    assert prune_archive(root) == 2
    assert not path.exists()
    assert prune_archive(root) == 0
    db = tmp_path / 'x.sqlite3'
    rebuild(db, root)
    assert len(read_frames(db, 'observed')[1]) == 2


def test_old_cached_outlier_cannot_appear_in_property_picker(tmp_path, monkeypatch):
    from pathlib import Path
    db = tmp_path / 'ui.sqlite3'
    sample = mixed()
    import_snapshot(db, sample)
    monkeypatch.setenv('HOUSING_DB_PATH', str(db))
    monkeypatch.setenv('HOUSING_OFFLINE', '1')
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'streamlit_app.py').run()
    assert not app.exception
    assert not app.toggle and not app.number_input
    options = [option for box in app.selectbox for option in box.options]
    assert not any('Allee Elm' in option for option in options)
    assert read_frames(db, 'observed')[1].price.between(400000, 700000).all()
