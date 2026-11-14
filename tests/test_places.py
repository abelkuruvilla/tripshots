"""Places: a reel is spread over the stops of a trip, not cut from the three best angles of one headland."""
from pathlib import Path

from tripshots import diversity, geo, media, planner, story, text
from tripshots.config import load_style


def _shot(i, created=None, gps=None, landmark=None, score=7, kind="video", src=None, tags=(), issues=()):
    return {"id": f"S{i:03d}", "kind": kind, "src": src or f"/x/{i}.{'mp4' if kind == 'video' else 'jpg'}",
            "sig": f"g{i}", "t0": 0.0, "t1": 4.0, "w": 1920, "h": 1080, "fps": 30, "thumb": "",
            "created": created, "gps": gps, "metrics": {"pan": 0.0, "activity": 0.3},
            "ai": {"score": score, "mood": "calm", "scene": "landscape", "landmark": landmark,
                   "tags": list(tags), "issues": list(issues), "people": {"count": 0, "activity": ""}}}


def test_the_critic_is_not_offered_a_grey_shot_for_a_colourful_reel():
    from tripshots import critic
    shots = [{"id": f"S{i}", "metrics": {"color": 30.0}, "ai": {"score": 7.0 + 0.01 * i}} for i in range(30)]
    shots.append({"id": "FOG", "metrics": {"color": 4.0}, "ai": {"score": 8.0}})      # steam: the best score, no colour
    shots.append({"id": "DUSK", "metrics": {"color": 28.0}, "ai": {"score": 8.0}})
    by_id = {s["id"]: s for s in shots}
    got = [s["id"] for s in critic.spares({"segments": [{"shot_id": "S0"}]}, by_id, {}, n=20)]
    assert got[0] == "DUSK" and "FOG" not in got and "S0" not in got
    grey = [{**s, "metrics": {"color": 5.0}} for s in shots]                             # a grey trip has no grey shot
    assert critic.spares({"segments": []}, {s["id"]: s for s in grey}, {}, n=3)[0]["id"] in ("FOG", "DUSK")


def test_the_critic_is_not_offered_a_landmark_the_reel_already_shows():
    from tripshots import critic
    shots = [{"id": f"S{i}", "ai": {"score": 7.0}} for i in range(5)]
    shots += [{"id": "HD1", "ai": {"score": 8.4, "landmark": "Half Dome, Yosemite"}},
              {"id": "HD2", "ai": {"score": 8.0, "landmark": "Half Dome"}}]
    got = [s["id"] for s in critic.spares({"segments": [{"shot_id": "HD1"}]}, {s["id"]: s for s in shots}, {})]
    assert "HD2" not in got and len(got) == 5


def test_the_critic_is_not_offered_an_upright_photo_for_a_horizontal_reel():
    from tripshots import critic, framing
    shots = [{"id": f"S{i}", "w": 4000, "h": 3000, "ai": {"score": 7.0 + 0.01 * i}} for i in range(30)]
    shots.append({"id": "TALL", "w": 3000, "h": 4000, "ai": {"score": 8.0}})   # the frame would keep a third of it
    by_id = {s["id"]: s for s in shots}
    try:
        framing.set_canvas(True)
        framing.set_frame(None)
        assert "TALL" not in [s["id"] for s in critic.spares({"segments": []}, by_id, {}, n=20)]
    finally:
        framing.set_canvas(False)
        framing.set_frame(None)
    assert critic.spares({"segments": []}, by_id, {}, n=20)[0]["id"] == "TALL"            # upright reel: welcome


def test_a_colourless_shot_has_to_be_clearly_better():
    """Grey sand from above in a reel of red canyons and blue lakes: it needs more than an equal score to get in."""
    shots = [_shot(i, score=7.6, tags=[f"t{i}"]) for i in range(12)]
    for s in shots:
        s["metrics"]["color"] = 30.0
    shots[0]["metrics"]["color"] = 4.0
    shots[0]["ai"]["score"] = 7.8
    style = load_style("beat-montage")
    assert planner.colourless(shots) == {"S000": 1.0}
    assert "S000" not in [s["id"] for s in planner.select_shots(shots, 6, style)]
    shots[0]["ai"]["score"] = 9.2  # the one everybody stops for: in, colour or not
    assert "S000" in [s["id"] for s in planner.select_shots(shots, 6, style)]
    for s in shots:  # a snow trip: nothing stands out as grey
        s["metrics"]["color"] = 5.0
    assert planner.colourless(shots) == {}


CAPE = [48.383, -124.714]
FALLS = [44.718, -110.496]


def test_a_stop_is_one_visit_whatever_the_camera():
    shots = [
        _shot(0, "2026-10-17T20:40:00", CAPE),                      # phone, with GPS
        _shot(1, "2026-10-17T20:44:00"),                            # camera without GPS, minutes later
        _shot(2, "2026-10-17T20:52:00", [48.384, -124.716]),
        _shot(3, "2026-10-17T23:30:00", [48.3832, -124.7142]),      # back at the same spot after a break
        _shot(4, "2026-10-18T09:00:00", FALLS),                     # the next day, elsewhere
        _shot(5, "2026-10-18T09:03:00", [44.80, -110.40]),          # minutes later but 12 km on: a drive
        _shot(6),                                                   # no clock at all
        _shot(7, src="/x/6.mp4"),                                   # ... another chunk of that clip
    ]
    st = diversity.sessions(shots)
    assert st["S000"] == st["S001"] == st["S002"] == st["S003"]
    assert len({st["S000"], st["S004"], st["S005"], st["S006"]}) == 4
    assert st["S006"] == st["S007"]


def test_a_landmark_names_the_place_across_visits_and_spellings():
    assert diversity.place_name(_shot(0, landmark="Half Dome, Yosemite")) == "half dome"
    assert diversity.place_name(_shot(0, landmark="The Half Dome (from Glacier Point)")) == "half dome"
    assert diversity.place_name(_shot(0, landmark="Artist's Palette")) == "artists palette"
    assert diversity.place_name(_shot(0, landmark="Zion National Park")) == "zion"
    assert diversity.place_name(_shot(0, landmark=None)) is None and diversity.place_name(_shot(0, landmark="null")) is None
    shots = [
        _shot(0, "2026-10-17T20:40:00", CAPE, "Cape Flattery"),
        _shot(1, "2026-10-17T20:44:00", CAPE, "Cape Flattery, Washington"),
        _shot(2, "2026-10-17T20:47:00"),                            # the drone at that stop: no name, no GPS
        _shot(3, "2026-10-19T10:00:00", None, "Cape Flattery"),     # two days later, named by the AI
        _shot(4, "2026-10-18T09:00:00", FALLS),
    ]
    pk = diversity.place_keys(shots)
    assert pk["S000"] == pk["S001"] == pk["S002"] == pk["S003"] == "at:cape flattery"
    assert pk["S004"].startswith("stop:")


def test_the_drone_clock_with_two_times_is_read():
    assert media._norm_time("2026-10-21T07:59:11.000000Z;2026-10-21T00:59:11-07:00").startswith("2026-10-21T00:59:11")
    assert diversity._when({"created": "2026-10-21T07:59:11Z;2026-10-21T00:59:11"}) == \
        diversity._when({"created": "2026-10-21T00:59:11"})


def test_selection_spreads_over_places():
    style = load_style("beat-montage")
    cape = [_shot(i, f"2026-10-17T20:{10 + i}:00", CAPE, "Cape Flattery", score=9, tags=[f"t{i}"]) for i in range(6)]
    rest = [_shot(10 + i, f"2026-10-{18 + i}T12:00:00", [44.0 + i, -110.0], score=8, tags=[f"u{i}"]) for i in range(6)]
    got = planner.select_shots(cape + rest, 6, style)
    n_cape = sum(1 for s in got if s["id"] in {c["id"] for c in cape})
    assert n_cape <= 2 and len({s["id"] for s in got}) == 6        # the best place twice at most, then the others
    # the opening hold's place counts as shown
    got = planner.select_shots(cape[1:] + rest, 3, style, cast=[cape[0]])
    assert sum(1 for s in got if s["id"] in {c["id"] for c in cape}) <= 1
    # a style can turn it off: then the scores decide
    style["shots"]["place_variety"] = 0
    got = planner.select_shots(cape + rest, 6, style)
    assert sum(1 for s in got if s["id"] in {c["id"] for c in cape}) == 6


def test_an_edited_export_with_titles_is_a_last_resort():
    style = load_style("beat-montage")
    assert diversity.baked_text(_shot(0, tags=["desert", "text overlay"]))
    assert diversity.baked_text(_shot(0, issues=["burned-in-text"]))
    assert not diversity.baked_text(_shot(0, tags=["road sign", "desert"]))
    s = _shot(0, tags=["valley"]); s["ai"]["note"] = "iconic steady vista with title overlay"
    assert diversity.baked_text(s)                                  # older verdicts only say so in the note
    s["ai"]["note"] = "a park sign: useful location title card"
    assert not diversity.baked_text(s)
    shots = [_shot(0, "2026-10-01T10:00:00", score=9.5, tags=["mesa", "title overlay"])] + \
            [_shot(i, f"2026-10-{i + 1:02d}T10:00:00", score=7.5, tags=[f"u{i}"]) for i in range(1, 6)]
    assert "S000" not in [s["id"] for s in planner.select_shots(shots, 4, style)]
    assert "S000" in [s["id"] for s in planner.select_shots(shots, 6, style)]      # thin footage: still usable


def test_casting_never_puts_a_place_twice_in_a_row():
    style = load_style("beat-montage")
    shots = [_shot(i, score=9 - 0.1 * i) for i in range(8)]
    where = {s["id"]: ("at:cape" if i < 3 else f"stop:{i}") for i, s in enumerate(shots)}
    segs = [{"out_start": float(i), "dur": 1.0, "level": "medium", "role": r}
            for i, r in enumerate(["hook", "build", "build", "build", "peak", "release", "release", "ending"])]
    order = story.cast(shots, segs, style, where=where)
    keys = [where[s["id"]] for s in order]
    assert sorted(s["id"] for s in order) == sorted(s["id"] for s in shots)
    assert all(a != b for a, b in zip(keys, keys[1:]))
    # slot by slot leaves one place for two neighbours at the end: the middle is re-shuffled, the ends stay
    order = [shots[0], shots[4], shots[5], shots[6], shots[3], shots[1], shots[2], shots[7]]
    story._part_places(order, [1, 2, 3, 5, 6], where)
    keys = [where[s["id"]] for s in order]
    assert all(a != b for a, b in zip(keys, keys[1:]))
    assert [order[i]["id"] for i in (0, 4, 7)] == ["S000", "S003", "S007"]


def test_the_storyboard_shows_a_wide_picture_wide(tmp_path):
    from PIL import Image
    seg = {"shot_id": "S000", "dur": 1.0, "layout": "crop", "note": "a wide view"}
    plan = {"style": "x", "duration": 2.0, "tempo": None, "segments": [seg, dict(seg)], "overlays": []}
    tall = Image.open(text.storyboard(plan, {}, Path(tmp_path / "a.jpg"))).size
    plan["frame"] = {"aspect": "16:9", "ar": 1.7778, "band": 608}
    wide = Image.open(text.storyboard(plan, {}, Path(tmp_path / "b.jpg"))).size
    assert tall[1] > 320 and wide[1] < tall[1] and wide[0] > 4 * 372       # 16:9 tiles, four across


def test_a_camera_without_gps_borrows_the_phones_position():
    shots = [_shot(0, "2026-10-17T20:40:00", CAPE), _shot(1, "2026-10-17T20:44:00"),
             _shot(2, "2026-10-18T09:00:00", FALLS), _shot(3, "2026-10-19T12:00:00"), _shot(4)]
    pos = diversity.positions(shots)
    assert pos["S000"] == CAPE and pos["S001"] == CAPE and pos["S002"] == FALLS
    assert "S003" not in pos and "S004" not in pos               # a day later, or no clock: not guessed


def test_a_region_is_looked_up_once_per_area(monkeypatch, tmp_path):
    asked = []

    def fake(lat, lon):
        asked.append((lat, lon))
        return {"state": "Washington", "country": "United States", "country_code": "us"}
    monkeypatch.setattr(geo, "CACHE", tmp_path / "geo.json")
    monkeypatch.setattr(geo, "_nominatim", fake)
    monkeypatch.delenv("TRIPSHOTS_OFFLINE", raising=False)
    monkeypatch.setattr(geo, "_offline", False)
    assert geo.region(*CAPE, coarse=True) == "Washington"
    assert geo.region(CAPE[0] + 0.01, CAPE[1] - 0.01, coarse=True) == "Washington" and len(asked) == 1
    monkeypatch.setenv("TRIPSHOTS_OFFLINE", "1")                 # offline: the area's answer stands in
    assert geo.region(CAPE[0] + 0.02, CAPE[1], coarse=False) == "Washington" and len(asked) == 1
    assert geo.region(*FALLS) is None
    monkeypatch.delenv("TRIPSHOTS_OFFLINE")
    monkeypatch.setattr(geo, "_nominatim", lambda lat, lon: {"country": "Iceland", "country_code": "is",
                                                              "state": "Southern Region"})
    assert geo.region(64.0, -19.0) == "Iceland"                  # outside US/CA/AU: the country


def test_a_reel_told_place_by_place_keeps_each_place_together():
    style = load_style("beat-montage")
    style["loop"] = False
    region = ["California"] * 4 + ["Oregon"] * 3 + ["Washington"] * 3
    shots = [_shot(i, f"2026-10-{10 + i:02d}T10:00:00", score=7 + (i * 7 % 5) * 0.4) for i in range(10)]
    places = {s["id"]: r for s, r in zip(shots, region)}
    roles = ["hook", "setup", "build", "build", "build", "peak", "release", "release", "release", "ending"]
    segs = [{"out_start": float(i), "dur": 1.0, "level": "medium", "role": r} for i, r in enumerate(roles)]
    order = story.cast(shots, segs, style, places=places, fmt="list")
    seq = [places[s["id"]] for s in order]
    assert sorted(s["id"] for s in order) == sorted(s["id"] for s in shots)
    runs = [r for i, r in enumerate(seq) if i == 0 or seq[i - 1] != r]
    # one chapter per place; only the place the reel both opens and ends on may come back, at the very end
    assert len(runs) == len(set(runs)) or (runs[0] == runs[-1] and len(runs) == len(set(runs)) + 1)
    # shots whose place isn't known are only picked when the named ones run out
    style["_named"] = {s["id"] for s in shots if s["ai"]["score"] < 8}
    picked = planner.select_shots(shots, 6, style)
    assert {s["id"] for s in picked} == style["_named"]


def test_a_reel_that_names_every_shot_gives_each_region_its_share():
    style = load_style("beat-montage")
    style["loop"] = False
    # six strong shots of California, two each of three other states, filmed days apart
    region = ["California"] * 6 + ["Oregon"] * 2 + ["Utah"] * 2 + ["Montana"] * 2
    shots = [_shot(i, f"2026-10-{10 + i:02d}T10:00:00", [36.0 + i, -120.0 + i], score=9 if i < 6 else 7,
                   tags=[f"t{i}"]) for i in range(12)]
    places = {s["id"]: r for s, r in zip(shots, region)}
    style["_named"], style["_places"] = set(places), places
    picked = planner.select_shots(shots, 8, style)
    per = {r: sum(1 for s in picked if places[s["id"]] == r) for r in set(region)}
    assert per == {"California": 2, "Oregon": 2, "Utah": 2, "Montana": 2}
    # ...and the cast keeps it when it has more shots than slots
    roles = ["hook", "setup", "build", "build", "peak", "release", "release", "ending"]
    segs = [{"out_start": float(i), "dur": 1.0, "level": "medium", "role": r} for i, r in enumerate(roles)]
    order = story.cast(shots, segs, style, places=places, fmt="list")
    per = {r: sum(1 for s in order if places[s["id"]] == r) for r in set(region)}
    assert max(per.values()) - min(per.values()) <= 1, per


def test_a_county_is_not_a_name_for_a_shot(monkeypatch):
    from tripshots import pipeline
    names = {37.5: "Mariposa County, California", 44.4: "Yellowstone National Park, Wyoming"}
    monkeypatch.setattr(geo, "place_name", lambda lat, lon: names[lat])
    monkeypatch.setattr(geo, "region", lambda lat, lon, coarse=False: names[lat].split(", ")[1])
    shots = [_shot(0, "2026-10-10T10:00:00", [37.5, -119.9]), _shot(1, "2026-10-12T10:00:00", [44.4, -110.5])]
    plan = {"segments": [{"shot_id": "S000"}, {"shot_id": "S001"}]}
    facts = pipeline._seg_facts(plan, {s["id"]: s for s in shots}, shots, full=True)
    assert facts == [{"region": "California"}, {"place": "Yellowstone National Park, Wyoming", "region": "Wyoming"}]
