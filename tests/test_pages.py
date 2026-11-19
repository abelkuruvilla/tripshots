"""Page layouts (pages.py): the gallery print and the route split."""
import json

import numpy as np

from conftest import ff, needs_ffmpeg
from tripshots import fxlib, pages


def _shot(i, scene, gps, t, kind="video", w=1920, h=1080):
    return {"id": f"S{i}", "kind": kind, "src": f"/x/{i}.mp4", "w": w, "h": h, "t0": 0, "t1": 8,
            "gps": gps, "created": f"2026-10-0{1 + i}T12:00:00", "ai": {"scene": scene}, "_t": t}


def _plan(shots, hook=True):
    segs = [{"shot_id": s["id"], "kind": "video", "src": s["src"], "src_w": s["w"], "src_h": s["h"], "in": 0.0,
             "speed": 1.0, "dur": 1.5, "out_start": 1.5 * i, "layout": "crop", "trans_out": "whip",
             "trans_dur": 0.3, "shake": True} for i, s in enumerate(shots)]
    ovs = [{"type": "location", "text": "Big Sur", "start": 1.6, "duration": 1.0},
           {"type": "caption", "text": "la la", "start": 0.2, "duration": 4.0}]
    if hook:
        ovs.insert(0, {"type": "hook", "text": "Ten days, one road", "start": 0.1, "duration": 3.0})
    return {"segments": segs, "overlays": ovs, "grid": {"cols": 8}}


SHOTS = [_shot(0, "mountains", [44.4, -110.6], 1), _shot(1, "beach", [36.3, -121.9], 3, w=1080, h=1920),
         _shot(2, "desert", [36.9, -111.5], 2), _shot(3, "forest", [41.2, -124.0], 4)]
FACTS = [{"landmark": "Old Faithful, Yellowstone", "region": "Wyoming"}, {"region": "California"},
         {"landmark": "Horseshoe Bend"}, {"region": "California"}]


def test_prints_have_a_word_above_and_where_and_when_under():
    plan = _plan(SHOTS)
    by_id = {s["id"]: s for s in SHOTS}
    got = pages.apply(plan, by_id, SHOTS, "print", {"paper": "cream"}, facts=FACTS)
    segs = plan["segments"]
    assert got and plan["page"]["kind"] == "print" and plan["page"]["paper"] == "cream"
    assert "page" not in segs[0]   # the hook's shot stays full screen
    assert segs[1]["page"]["title"] == "The Coast" and segs[1]["page"]["left"] == "California"
    assert segs[2]["page"]["left"] == "Horseshoe Bend" and segs[2]["page"]["right"]
    # only the hook stays, over its own shot; the rest of the lettering waits for the pages to come off
    assert [o["type"] for o in plan["overlays"]] == ["hook"] and plan["overlays"][0]["duration"] <= 1.4
    assert "grid" not in plan and all("shake" not in s for s in segs[1:]) and segs[1]["trans_out"] is None
    # an upright print stands tall, a wide one lies across the page
    up, wide = pages.box(plan, segs[1]), pages.box(plan, segs[2])
    assert up[1] > up[0] and wide[1] < wide[0] and up[4] == "#f4eee2"
    pages.clear(plan)
    assert "page" not in plan and len(plan["overlays"]) == 3 and plan["grid"] and segs[1]["shake"]


def test_route_pages_follow_the_trip_in_the_order_it_was_filmed(monkeypatch):
    import tripshots.diversity as D
    monkeypatch.setattr(D, "_when", lambda s: s.get("_t"))
    plan = _plan(SHOTS, hook=True)
    by_id = {s["id"]: s for s in SHOTS}
    pages.apply(plan, by_id, SHOTS, "route", {}, facts=FACTS)
    segs = plan["segments"]
    assert [s["shot_id"] for s in segs] == ["S0", "S2", "S1", "S3"]   # filmed order; slots keep their lengths
    assert [s["page"]["stop"] for s in segs] == [0, 1, 2, 3] and len(plan["page"]["stops"]) == 4
    assert segs[0]["page"]["label"] == "Ten days, one road"   # the opening line captions the first page
    assert segs[1]["page"]["label"] == "Horseshoe Bend" and segs[2]["page"]["label"] == "California"
    b = pages.box(plan, segs[0])
    assert b[0] == 1080 and b[1] < 700 and b[3] < 300
    layer = pages.furniture(plan, segs[1])
    assert layer.shape == (1920, 1080, 4) and layer[1100:1700, :, 3].mean() > 200   # the map fills its band


def test_a_camera_without_gps_takes_the_place_of_the_photo_taken_nearest_in_time(monkeypatch):
    import tripshots.diversity as D
    monkeypatch.setattr(D, "_when", lambda s: s.get("_t"))
    cam = {**_shot(4, "forest", None, 3.2), "src": "/x/cam.mp4"}
    far = {**_shot(5, "forest", None, 9e6), "src": "/x/far.mp4"}
    shots = SHOTS + [cam, far]
    plan = _plan(shots, hook=False)
    pages.apply(plan, {s["id"]: s for s in shots}, shots, "route", {}, facts=FACTS + [{}, {}])
    stop = {s["shot_id"]: s["page"]["stop"] for s in plan["segments"]}
    assert stop["S4"] == stop["S1"] and stop["S5"] == -1   # just after S1: there; months away: no pin


def test_one_place_is_no_route():
    one = [_shot(i, "beach", [36.3, -121.9], i) for i in range(4)]
    plan = _plan(one)
    assert pages.apply(plan, {s["id"]: s for s in one}, one, "route", {}, facts=[{}] * 4) == []
    assert "page" not in plan


def test_the_director_offers_pages_to_a_reel_that_can_carry_them():
    plan = _plan(SHOTS)
    el = fxlib.eligible(plan, {}, {s["id"]: s for s in SHOTS})
    assert el["print"] == ["whole reel"] and el["route"] == ["whole reel"]
    cfg = {"_eligible": el, "max_moves": 2}
    got = fxlib.check_moves([{"id": "route_split", "settings": {"theme": "dark"}},
                             {"id": "gallery_print"}], cfg)
    assert [m["id"] for m in got] == ["route_split"] and got[0]["settings"] == {"theme": "dark"}
    assert not fxlib.eligible({**plan, "recipe": {"n": 1}}, {}, {s["id"]: s for s in SHOTS}).get("route")


def test_the_route_still_draws_without_map_data(monkeypatch):
    import tripshots.routemap as R

    def gone(*a, **k):
        raise RuntimeError("map data missing")
    monkeypatch.setattr(R, "topo", gone)
    pages._map.cache_clear()
    img = pages._map(((44.4, -110.6), (36.3, -121.9)), "light", 200, 120)
    assert img.shape == (120, 200, 4) and img[..., 3].min() == 255
    pages._map.cache_clear()


def test_page_edits(tmp_path, monkeypatch):
    from tripshots import planedit
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    (tmp_path / "shots_scored.json").write_text(json.dumps(SHOTS))
    plan = {**_plan(SHOTS), "style": "beat-montage", "work": str(tmp_path), "duration": 6.0, "color": {},
            "tempo": 120}
    p = tmp_path / "t.plan.json"
    p.write_text(json.dumps(plan))
    monkeypatch.setattr(pages, "_facts", lambda *a: FACTS)
    planedit.apply(p, [{"op": "page", "kind": "print"}])
    planedit.apply(p, [{"op": "page", "segment": 2, "title": "Big Sur", "right": "Day 3"}])
    s = json.loads(p.read_text())
    assert s["page"]["kind"] == "print" and s["segments"][1]["page"]["title"] == "Big Sur"
    planedit.apply(p, [{"op": "page", "kind": "off"}])
    assert "page" not in json.loads(p.read_text())


@needs_ffmpeg
def test_a_paged_shot_renders_in_its_window_on_the_paper(tmp_path):
    from tripshots import render
    src = tmp_path / "c.mp4"
    ff("-f", "lavfi", "-i", "color=c=red:s=640x360:d=2:r=30", str(src))
    plan = {"page": {"kind": "print", "paper": "white"}}
    seg = {"kind": "video", "src": str(src), "src_w": 640, "src_h": 360, "in": 0.0, "speed": 1.0, "dur": 1.0,
           "layout": "crop", "subject_x": 0.5, "page": {"title": "", "left": "", "right": ""}}
    b = pages.box(plan, seg)
    out = tmp_path / "s.mp4"
    render.render_video_seg({**seg, "_box": b}, 1.0, {}, out)
    raw = ff_frame(out)
    assert raw[20, 20].min() > 235   # paper
    cy, cx = b[3] + b[1] // 2, b[2] + b[0] // 2
    assert raw[cy, cx, 0] > 180 and raw[cy, cx, 1] < 80   # the picture inside its window


def ff_frame(path):
    import subprocess
    from tripshots.util import ffmpeg_base
    buf = subprocess.run(ffmpeg_base() + ["-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return np.frombuffer(buf[:1080 * 1920 * 3], np.uint8).reshape(1920, 1080, 3)


def test_a_reference_that_set_its_shots_on_pages_teaches_its_recipe_to():
    from tripshots import recipes
    m = {"shot_lens": [1.0] * 8, "duration": 8.0, "tempo": 120, "aspect": 0.5625}
    r = recipes.build(m, {"format": "montage", "page": "print", "text": {"kind": "none"}}, "ref.mp4", 1)
    assert r["page"] == "print"
    assert "page" not in recipes.build(m, {"page": "collage"}, "ref.mp4", 2)
    style = {}
    recipes.apply(style, r)
    assert style["page"] == {"kind": "print"}
