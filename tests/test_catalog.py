import os
from pathlib import Path

import pytest
from conftest import needs_ffmpeg

import tripgen
from tripshots import catalog
from tripshots.config import HOME


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    root = tripgen.make_library(tmp_path_factory.mktemp("trips"))
    tripgen.seed_place(HOME, "Yellowstone National Park", (44.6, -110.6), 0.45)
    return root


@needs_ffmpeg
def test_place_by_gps_plus_same_day_clips(lib):
    r = catalog.find([lib], place="Yellowstone National Park")
    names = {Path(f["path"]).name for f in catalog.load_selection(r["selection"])["files"]}
    assert {"IMG_0001.jpg", "IMG_0004.jpg", "DJI_20250712101500_0001_D.MP4"} <= names
    assert "VID_20250712_120000.mp4" in names            # no GPS, same day, during the park hours
    assert "IMG_20250714_101000.jpg" not in names        # Denver, the next day
    assert "VID_20250714_110000.mp4" not in names
    assert r["matched_by"]["same day, no GPS"] == 1


@needs_ffmpeg
def test_only_matching_and_dates(lib):
    r = catalog.find([lib], place="Yellowstone National Park", whole_days=False, date_from="2025-07-13")
    assert r["count"] == 2 and set(r["days"]) == {"2025-07-13"}


@needs_ffmpeg
def test_folder_name_matches_without_map(lib):
    r = catalog.find([lib], text="yellowstone")
    assert r["count"] == 5  # everything in "SSD/Yellowstone 2025"


@needs_ffmpeg
def test_selection_feeds_make(lib):
    r = catalog.find([lib], near=[38.72, -9.14], radius_km=5)
    paths, label = catalog.expand_inputs([f"sel:{r['selection']}"])
    assert len(paths) == 2 and all(p.exists() for p in paths) and label


@needs_ffmpeg
def test_trips(lib):
    t = catalog.trips([lib], name=False)
    assert [x["from"] for x in t] == ["2025-03-10", "2025-07-12", "2025-07-14"]
    assert t[1]["days"] == 2 and t[1]["videos"] == 2


def test_footage_roots_from_env(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    monkeypatch.setenv("TRIPSHOTS_FOOTAGE", os.pathsep.join([str(a), str(b), str(tmp_path / "gone")]))
    assert catalog.footage_roots() == [a, b]


def test_offline_means_no_place_lookups(monkeypatch):
    from tripshots import geo
    monkeypatch.setenv("TRIPSHOTS_OFFLINE", "1")
    monkeypatch.setattr(geo.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert geo.search("Somewhere Never Cached") is None
    assert geo.place_name(1.234, 5.678) is None
