"""Place names (parks and landmarks before counties) and split screens that fit the clips' shape."""
import io
import json

from tripshots import geo


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(nominatim: dict, overpass: list):
    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        body = {"address": nominatim} if "nominatim" in url else {"elements": overpass}
        return _Resp(json.dumps(body).encode())
    return urlopen


def _run(monkeypatch, tmp_path, nominatim, overpass):
    monkeypatch.setattr(geo, "CACHE", tmp_path / "geo.json")
    monkeypatch.setattr(geo, "_offline", False)
    monkeypatch.setattr(geo, "_last", 0.0)
    monkeypatch.delenv("TRIPSHOTS_OFFLINE", raising=False)
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    monkeypatch.setattr(geo.urllib.request, "urlopen", _fake(nominatim, overpass))
    return geo.place_name(37.728, -119.574)


COUNTY = {"county": "Mariposa County", "state": "California", "country_code": "us", "country": "United States"}
PARK = {"type": "area", "tags": {"name": "Yosemite National Park", "boundary": "national_park"}}
WILDERNESS = {"type": "area", "tags": {"name": "Yosemite Wilderness", "boundary": "protected_area", "protect_class": "1b"}}


def test_park_beats_the_county(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, COUNTY, [WILDERNESS, PARK]) == "Yosemite National Park, California"


def test_famous_spot_inside_a_park(monkeypatch, tmp_path):
    spots = [{"type": "node", "lat": 37.7307, "lon": -119.5734, "tags": {"name": "Glacier Point", "tourism": "viewpoint", "wikidata": "Q1"}},
             {"type": "node", "lat": 37.746, "lon": -119.533, "tags": {"name": "Half Dome", "natural": "peak", "wikidata": "Q2"}}]
    assert _run(monkeypatch, tmp_path, COUNTY, [PARK] + spots) == "Glacier Point, Yosemite National Park"


def test_town_when_nothing_famous(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, {**COUNTY, "town": "Mariposa"}, []) == "Mariposa, California"
    # landmark lookup down: still a name
    monkeypatch.setattr(geo, "_landmark", lambda lat, lon: (None, None))
    monkeypatch.setattr(geo, "CACHE", tmp_path / "geo2.json")
    assert geo.place_name(37.5, -119.9) == "Mariposa, California"


def test_columns_become_rows_for_landscape_clips():
    from tripshots.planner import _is_wide
    assert _is_wide({"w": 3840, "h": 2160}) and not _is_wide({"w": 1080, "h": 1920})
    assert not _is_wide({"w": 3840, "h": 2160, "rotation": 90})


def test_location_title_names_the_shot_it_is_over():
    from tripshots.config import load_style
    from tripshots.planner import add_location_overlays
    segs = [{"shot_id": "A", "out_start": 0.0, "dur": 2.0},
            {"shot_id": None, "panel": "split3", "out_start": 2.0, "dur": 3.0, "clips": []},
            {"shot_id": "B", "out_start": 5.0, "dur": 3.0}]
    plan = {"segments": segs, "overlays": [{"type": "hook", "text": "x", "start": 0.1, "duration": 1.9}],
            "duration": 8.0}
    style = load_style("cinematic")
    style["text"]["location"].update({"mode": "each", "behind": "off"})
    places = {"A": None, "P": "Monument Valley, Arizona", "B": "Yosemite National Park, California"}
    segs[1]["shot_id"] = "P"
    add_location_overlays(plan, {}, places, style)
    locs = [o["text"] for o in plan["overlays"] if o["type"] == "location"]
    assert "Monument Valley, Arizona" not in locs                      # never over somebody else's shot
    assert locs == ["Yosemite National Park, California"]
