"""Reels as projects (projects.py) and one trip in parts (catalog.split_trip)."""
import json
from datetime import datetime, timedelta

import pytest

from tripshots import catalog, projects
from tripshots.util import ReelError


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(projects, "STORE", h / "projects.json")
    monkeypatch.setattr(projects, "HOME", h)
    import tripshots.config as C
    monkeypatch.setattr(C, "HOME", h)
    return h


def _reel(folder, name="trip"):
    folder.mkdir(parents=True, exist_ok=True)
    for ext in (".plan.json", ".mp4", ".cover.jpg", ".caption.txt", ".draft.mp4"):
        (folder / f"{name}{ext}").write_text("{}" if ext == ".plan.json" else "x")
    (folder / f"{name}.carousel").mkdir()
    (folder / f"{name}.carousel" / "01.jpg").write_text("x")
    (folder / f"{name} 2.plan.json").write_text("{}")         # another reel that starts with the same name
    (folder / f"{name}-x.mp4").write_text("x")
    return folder / f"{name}.plan.json"


def test_flags_collections_and_pinned_first(tmp_path, home):
    p = _reel(tmp_path / "reels")
    other = tmp_path / "reels" / "trip 2.plan.json"
    projects.manage(p, "pin")
    projects.manage(p, "favorite")
    projects.manage(other, "collection", "Iceland 2026")
    cards = projects.annotate([{"plan": str(other), "modified": 9}, {"plan": str(p), "modified": 1}])
    assert cards[0]["plan"] == str(p) and cards[0]["pinned"] and cards[0]["favorite"]
    assert cards[1]["collection"] == "Iceland 2026" and projects.collections() == ["Iceland 2026"]
    projects.manage(p, "unpin")
    assert not projects.flags(p).get("pinned") and projects.flags(p)["favorite"]


def test_rename_moves_every_file_and_the_records(tmp_path, home):
    p = _reel(tmp_path / "reels")
    projects.manage(p, "favorite")
    (home / "history.json").write_text(json.dumps([{"out": str((tmp_path / "reels" / "trip.mp4").resolve()), "uses": []}]))
    from tripshots.planedit import _history
    h = _history(p)
    (h / "undo").mkdir(parents=True)
    (h / "undo" / "000001.json").write_text("{}")
    new = projects.rename(p, "Iceland day 1")
    names = sorted(f.name for f in (tmp_path / "reels").iterdir())
    assert "Iceland day 1.mp4" in names and "Iceland day 1.carousel" in names and "Iceland day 1.draft.mp4" in names
    assert "trip 2.plan.json" in names and "trip-x.mp4" in names and "trip.mp4" not in names   # others untouched
    assert projects.flags(new)["favorite"] and _history(new).exists() and not h.exists()
    assert json.loads((home / "history.json").read_text())[0]["out"].endswith("Iceland day 1.mp4")
    with pytest.raises(ReelError):
        projects.rename(new, "trip 2")       # taken
    with pytest.raises(ReelError):
        projects.rename(new, "a.b")


def test_duplicate_and_trash(tmp_path, home, monkeypatch):
    p = _reel(tmp_path / "reels")
    projects.manage(p, "collection", "Road trip")
    c = projects.duplicate(p)
    assert c.name == "trip copy.plan.json" and c.exists() and not c.with_name("trip copy.mp4").exists()
    assert projects.flags(c)["collection"] == "Road trip"
    assert projects.duplicate(p).name == "trip copy 2.plan.json"
    monkeypatch.setattr(projects.Path, "home", lambda: tmp_path / "nohome")   # no ~/.Trash: TripShots' own trash
    res = projects.manage(p, "delete")
    assert len(res["trashed"]) == 6 and not p.exists() and (tmp_path / "reels" / "trip 2.plan.json").exists()
    assert all(str(home / "trash") in t for t in res["trashed"])


def test_a_trip_splits_by_day_and_by_place(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 1, 9)
    recs = []
    for d, place, n in ((0, "Reykjavik", 10), (1, "Vik", 12), (2, "Vik", 3), (3, "Hofn", 9)):
        for k in range(n):
            recs.append({"path": f"/f/{d}_{k}.jpg", "kind": "photo", "time": t0 + timedelta(days=d, minutes=k),
                         "created": (t0 + timedelta(days=d)).isoformat(), "place": place})
    monkeypatch.setattr(catalog, "records", lambda folders=None, *a, **k: [dict(r) for r in recs])
    monkeypatch.setattr(catalog, "name_places", lambda recs: None)
    monkeypatch.setattr(catalog, "SEL_DIR", tmp_path / "sel")
    res = catalog.split_trip(None, ["/f"], by="day", min_files=8)
    # day 3 (3 files) joins day 2
    assert [p["files"] for p in res["parts"]] == [10, 15, 9]
    assert res["parts"][1]["days"] == ["2026-07-02", "2026-07-03"]
    assert res["collection"] == "Vik, Reykjavik (2026-07-01)" and res["parts"][1]["label"] == "2026-07-01-day02-Vik"
    assert len(catalog.load_selection(res["parts"][0]["selection"])["files"]) == 10
    by_place = catalog.split_trip(None, ["/f"], by="place", min_files=8)
    assert [p["places"][0] for p in by_place["parts"]] == ["Reykjavik", "Vik", "Hofn"]
    with pytest.raises(ReelError):
        catalog.split_trip("trip-1999-01-01", ["/f"])
