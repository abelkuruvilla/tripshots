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
