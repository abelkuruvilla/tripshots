import json

from tripshots import planedit


def _plan(tmp_path):
    shots = [{"id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "w": 4000, "h": 3000,
              "t0": 0, "t1": 0, "ai": {"score": 8 - i, "note": f"shot {i}"}, "metrics": {}} for i in range(5)]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    segs = []
    for i in range(3):
        segs.append({"shot_id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg",
                     "layout": "kenburns", "kb": "in", "dur": 1.0 + i, "out_start": float(sum(range(1, i + 1))) + i * 0,
                     "level": "mid", "trans_out": None})
    plan = {"style": "beat-montage", "work": str(tmp_path), "duration": 6.0, "segments": segs, "overlays": [],
            "color": {}, "tempo": 120}
    p = tmp_path / "t.plan.json"
    p.write_text(json.dumps(plan))
    return p


def test_edits_keep_slot_timing(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _plan(tmp_path)
    res = planedit.apply(p, [{"op": "exchange", "a": 1, "b": 3}, {"op": "swap", "segment": 2, "shot_id": "S4"},
                             {"op": "text", "type": "hook", "text": "Two days in Yellowstone"},
                             {"op": "transition", "segment": 1, "to": "whip"}])
    plan = json.loads(p.read_text())
    assert [s["shot_id"] for s in plan["segments"]] == ["S2", "S4", "S0"]
    assert [s["dur"] for s in plan["segments"]] == [1.0, 2.0, 3.0]     # the beat grid didn't move
    assert plan["segments"][0]["trans_out"] == "whip"
    assert plan["overlays"][0]["text"] == "Two days in Yellowstone"
    assert len(res["changes"]) == 4


def test_a_slot_keeps_its_place_in_the_story(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _plan(tmp_path)
    plan = json.loads(p.read_text())
    for seg, role in zip(plan["segments"], ("hook", "peak", "ending")):
        seg["role"] = role
    plan["segments"][0]["hold"] = True
    plan["segments"][1]["incam_out"] = {"type": "whip_pan", "at": 3.2, "src": "local"}
    plan["segments"][2]["incam_in"] = True
    p.write_text(json.dumps(plan))
    planedit.apply(p, [{"op": "exchange", "a": 1, "b": 3}, {"op": "swap", "segment": 2, "shot_id": "S4"}])
    plan = json.loads(p.read_text())
    # the camera's own swing went with the footage that had it
    assert not any("incam_out" in s or "incam_in" in s for s in plan["segments"])
    assert [s["shot_id"] for s in plan["segments"]] == ["S2", "S4", "S0"]
    assert [s["role"] for s in plan["segments"]] == ["hook", "peak", "ending"]     # roles belong to the slots
    assert plan["segments"][0].get("hold") and not plan["segments"][2].get("hold")


def test_candidates(tmp_path):
    c = planedit.candidates(_plan(tmp_path), top=10)
    assert c[0]["id"] == "S0" and c[0]["used"] and not c[-1]["used"]


def test_text_can_be_added_styled_and_removed(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _plan(tmp_path)
    planedit.apply(p, [{"op": "add_text", "text": "Day 3", "start": 1.0, "duration": 2.0,
                        "style": {"color": "#ffd23c", "size": 110, "font": "anton"}}])
    plan = json.loads(p.read_text())
    o = plan["overlays"][0]
    assert o["type"] == "text" and o["style"] == {"color": [255, 210, 60], "size": 110, "font": "anton"}
    planedit.apply(p, [{"op": "edit_text", "index": 1, "text": "Day three", "start": 2.0,
                        "style": {"size": None, "font": "gf:Playfair Display:700", "position": "upper", "uppercase": True}}])
    o = json.loads(p.read_text())["overlays"][0]
    assert o["text"] == "Day three" and o["start"] == 2.0 and "size" not in o["style"]
    assert o["style"]["font"] == "gf:Playfair Display:700" and o["style"]["position"] == "upper"
    import pytest
    from tripshots.util import ReelError
    for bad in ({"font": "Comic Sans"}, {"color": "blue-ish"}, {"position": "sideways"}, {"wobble": 1}):
        with pytest.raises(ReelError):
            planedit.apply(p, [{"op": "edit_text", "index": 1, "style": bad}])
    planedit.apply(p, [{"op": "delete_text", "index": 1}])
    assert json.loads(p.read_text())["overlays"] == []


def test_a_place_title_given_its_own_lettering_becomes_plain_text(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _plan(tmp_path)
    plan = json.loads(p.read_text())
    plan["overlays"] = [{"type": "location", "text": "Big Sur, California", "main": "Big Sur", "sub": "California",
                         "gps": [36.2, -121.8], "start": 0.5, "duration": 1.5}]
    p.write_text(json.dumps(plan))
    planedit.apply(p, [{"op": "edit_text", "index": 1, "style": {"color": "#ffffff"}}])
    o = json.loads(p.read_text())["overlays"][0]
    assert o["type"] == "text" and o["text"] == "Big Sur, California" and "gps" not in o


def test_the_timeline_can_be_cut_lengthened_and_reordered(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _plan(tmp_path)
    plan = json.loads(p.read_text())
    plan["overlays"] = [{"type": "hook", "text": "go", "start": 0.1, "duration": 1.0},
                        {"type": "cta", "text": "save it", "start": 4.0, "duration": 1.5}]
    p.write_text(json.dumps(plan))
    planedit.apply(p, [{"op": "duration", "segment": 1, "dur": 1.5}])   # slot 1: 1.0 -> 1.5
    plan = json.loads(p.read_text())
    assert [s["dur"] for s in plan["segments"]] == [1.5, 2.0, 3.0]
    assert [s["out_start"] for s in plan["segments"]] == [0.0, 1.5, 3.5] and plan["duration"] == 6.5
    assert plan["overlays"][1]["start"] == 4.5 and plan["overlays"][0]["start"] == 0.1  # later text moved with the cut
    planedit.apply(p, [{"op": "split", "segment": 3, "at": 1.0}])
    plan = json.loads(p.read_text())
    assert [s["dur"] for s in plan["segments"]] == [1.5, 2.0, 1.0, 2.0]
    assert plan["segments"][2]["shot_id"] == plan["segments"][3]["shot_id"] == "S2"
    planedit.apply(p, [{"op": "delete", "segment": 2}, {"op": "insert", "after": 0, "shot_id": "S4", "dur": 0.5},
                       {"op": "duplicate", "segment": 2}])
    plan = json.loads(p.read_text())
    assert [s["shot_id"] for s in plan["segments"]] == ["S4", "S0", "S0", "S2", "S2"]
    assert plan["overlays"][0]["start"] == 0.1          # the hook still opens the reel
    assert abs(sum(s["dur"] for s in plan["segments"]) - plan["duration"]) < 1e-6
    assert all(abs(s["dur"] * 30 - round(s["dur"] * 30)) < 1e-3 for s in plan["segments"])   # whole frames
    assert plan["segments"][-1]["trans_out"] is None
    planedit.apply(p, [{"op": "music", "start": 3.0, "gain_db": -6}])
    assert json.loads(p.read_text())["music"] == {"start": 3.0, "gain_db": -6.0}


def test_undo_and_redo(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _plan(tmp_path)
    planedit.apply(p, [{"op": "add_text", "text": "one"}])
    planedit.apply(p, [{"op": "add_text", "text": "two"}])
    assert planedit.history(p) == {"undo": 2, "redo": 0}
    planedit.step(p, back=True)
    assert [o["text"] for o in json.loads(p.read_text())["overlays"]] == ["one"]
    planedit.step(p, back=False)
    assert [o["text"] for o in json.loads(p.read_text())["overlays"]] == ["one", "two"]
    planedit.step(p)
    planedit.apply(p, [{"op": "add_text", "text": "three"}])   # a new edit: nothing left to redo
    assert planedit.history(p)["redo"] == 0


def test_colour_a_look_for_the_reel_and_corrections_per_shot(tmp_path, monkeypatch):
    import tripshots.text as T
    from tripshots import grade
    from tripshots.fx import adjust_chain, color_chain, seg_color
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    calls = []
    monkeypatch.setattr(grade, "grade_plan", lambda plan, by_id, cfg, backend, work: calls.append(cfg) or
                        plan.update(grade={"look": cfg["look"], "strength": cfg["strength"], "grain": 0, "vignette": False}))
    p = _plan(tmp_path)
    planedit.apply(p, [{"op": "grade", "look": "moody", "strength": 0.6, "grain": 4}])
    plan = json.loads(p.read_text())
    assert calls[-1]["look"] == "moody" and calls[-1]["ai"] is False          # no new AI calls in the editor
    assert plan["grade"]["strength"] == 0.6 and plan["grade"]["grain"] == 4    # grain set by hand stays
    planedit.apply(p, [{"op": "adjust", "segment": 2, "exposure": 0.5, "warmth": 3, "contrast": 1.0}])
    seg = json.loads(p.read_text())["segments"][1]
    assert seg["adjust"] == {"exposure": 0.5, "warmth": 1.0}                   # clamped; neutral values dropped
    chain = color_chain(seg_color({"saturation": 1.0}, seg))
    assert any(f.startswith("exposure=") for f in chain) and any(f.startswith("colorbalance=") for f in chain)
    assert adjust_chain({}) == [] and adjust_chain(None) == []
    planedit.apply(p, [{"op": "adjust", "segment": "all", "saturation": 1.2, "graded": False}])
    segs = json.loads(p.read_text())["segments"]
    assert all(s["adjust"]["saturation"] == 1.2 and s["no_grade"] for s in segs)
    assert "lut" not in seg_color({"lut": "/x.cube"}, {**segs[0], "lut": __file__})   # as filmed: no look
    planedit.apply(p, [{"op": "adjust", "segment": 2, "reset": True}, {"op": "grade", "look": "none"}])
    plan = json.loads(p.read_text())
    assert "adjust" not in plan["segments"][1] and plan["grade"] == {"look": "none"}
    import pytest
    from tripshots.util import ReelError
    with pytest.raises(ReelError):
        planedit.apply(p, [{"op": "grade", "look": "no-such-look"}])


def _long_clip_plan(tmp_path):
    """A 40 s file cut into four shots, plus photos; slot 1 is a 1.2 s photo slot."""
    p = _plan(tmp_path)
    shots = json.loads((tmp_path / "shots_scored.json").read_text())
    for k in range(4):
        shots.append({"id": f"V{k}", "kind": "video", "src": "/x/long.mp4", "t0": 10.0 * k, "t1": 10.0 * (k + 1),
                      "dur": 10.0, "fps": 30, "w": 1920, "h": 1080, "created": f"2026-10-0{k + 1}T10:00",
                      "ai": {"score": 7, "caption": "bison crossing the road" if k == 2 else "a road"},
                      "metrics": {"pan": 0.0, "activity": 0.0}})
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    return p


def test_every_shot_can_be_found_and_paged(tmp_path):
    from tripshots.clippick import browse
    p = _long_clip_plan(tmp_path)
    r = browse(p, limit=3, group=False)
    assert r["total"] == 9 and len(r["items"]) == 3
    assert len(browse(p, offset=3, limit=60, group=False)["items"]) == 6
    hit = browse(p, q="bison", kind="video")
    assert [i["id"] for i in hit["items"]] == ["V2"] and hit["items"][0]["file_s"] == 40.0
    assert [i["id"] for i in browse(p, kind="video", sort="time", group=False)["items"]] == ["V0", "V1", "V2", "V3"]
    assert browse(p, kind="video")["total"] == 1     # one card per file: the part is chosen in the trim step
    assert browse(p, kind="photo")["total"] == 5
    assert planedit.candidates(p, top=20)[0].get("file_s") is None   # photos have no length


def test_the_part_that_plays_can_be_anywhere_in_the_file(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _long_clip_plan(tmp_path)
    # V0 covers 0-10 s, but the part chosen is at 33 s: past this shot's edge, inside the file
    planedit.apply(p, [{"op": "swap", "segment": 1, "shot_id": "V0", "in": 33.0}])
    s = json.loads(p.read_text())["segments"][0]
    assert s["shot_id"] == "V0" and s["in"] == 33.0 and s["track"] is False
    planedit.apply(p, [{"op": "slip", "segment": 1, "in": 99.0}])        # never past the end of the file
    s = json.loads(p.read_text())["segments"][0]
    assert s["in"] == round(40.0 - s["dur"] * s["speed"], 3)
    planedit.apply(p, [{"op": "insert", "after": 0, "shot_id": "V3", "dur": 1.5, "in": 2.0}])
    assert json.loads(p.read_text())["segments"][0]["in"] == 2.0


def test_the_ai_chooses_the_part_and_a_bad_answer_falls_back(tmp_path, monkeypatch):
    from pathlib import Path
    from tripshots import ai, clippick
    p = _long_clip_plan(tmp_path)
    monkeypatch.setattr(clippick, "filmstrip", lambda sh, length, n=14: None)
    monkeypatch.setattr(clippick, "_sheet", lambda sh, length, n=12: (Path("/x/sheet.jpg"), []))
    seen = {}

    class Fake(ai.Backend):
        name = "fake"

        def __init__(self, answer):
            self.answer = answer

        def ask(self, prompt, images=None, max_tokens=4000):
            seen["prompt"] = prompt
            return self.answer
    monkeypatch.setattr(ai, "get_backend", lambda name=None: Fake('{"start": 21.5, "why": "the bison steps out"}'))
    r = clippick.ai_window(p, "V0", slot=1)
    assert r == {"in": 21.5, "by": "fake", "why": "the bison steps out"}
    assert "1.00 s" in seen["prompt"] and "40.0 s clip" in seen["prompt"]
    monkeypatch.setattr(ai, "get_backend", lambda name=None: Fake("no idea"))
    assert clippick.ai_window(p, "V0", slot=1)["by"] == "rules"
    monkeypatch.setattr(ai, "get_backend", lambda name=None: None)
    r = clippick.ai_window(p, "V0", slot=1)
    assert r["by"] == "rules" and 0 <= r["in"] <= 39
