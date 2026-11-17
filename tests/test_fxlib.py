"""The effects library (fxlib.py, vfx.py, the new transitions and text looks) and its director."""
import json

import numpy as np
import pytest

from tripshots import fxlib, motion, planedit, vfx


def _frames():
    a = np.zeros((320, 180, 3), np.uint8)
    a[..., 0] = np.linspace(0, 255, 180, dtype=np.uint8)[None, :]
    b = np.full((320, 180, 3), (40, 120, 200), np.uint8)
    return a, b


def test_every_library_transition_runs_and_lands_on_the_next_shot():
    a, b = _frames()
    for name in fxlib.TRANSITIONS:
        assert name in motion.TRANSITIONS, name
        for p in (0.0, 0.3, 0.5, 0.7):
            out = motion.apply_transition(name, a, b, p)
            assert out.shape == a.shape and out.dtype == np.uint8, name
        end = motion.apply_transition(name, a, b, 1.0)
        assert np.abs(end.astype(int) - b).mean() < 40, name     # the window ends on (nearly) the new shot
        assert name in motion.NATURAL, name


def test_every_shot_effect_keeps_the_frame_and_changes_it():
    a, _ = _frames()
    for fid in fxlib.SHOT_EFFECTS:
        assert fid in vfx.EFFECTS
        out = vfx.apply(a, {"id": fid, "amount": 0.8}, 0.5, [0.5])
        assert out.shape == a.shape and out.dtype == np.uint8, fid
        assert np.abs(out.astype(int) - a).mean() > 0.5, fid
    assert vfx.apply(a, None, 0.0) is a and vfx.apply(a, {"id": "nope"}, 0.0) is a


def test_text_looks_draw_differently():
    from tripshots import typo
    f = typo.font(None, 90)
    plain, _ = typo._render_text("Big Sur", f)
    for lk in typo.LOOKS:
        img, pad = typo._render_text("Big Sur", f, fill=(255, 80, 200), look=lk)
        assert img.shape[2] == 4 and img[..., 3].max() > 0.9, lk
    import cv2
    hollow, _ = typo._render_text("I", typo.font(None, 200), look="outline")
    solid, _ = typo._render_text("I", typo.font(None, 200), shadow=0)
    core = cv2.erode((solid[..., 3] > 0.9).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    assert core.sum() > 50 and hollow[..., 3][core].mean() < 0.3      # the inside of the letter is empty


def _plan(tmp_path, n=6, trans=(None, "whip", None, "dissolve", None)):
    shots = [{"id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "w": 4000, "h": 3000,
              "t0": 0, "t1": 0, "ai": {"score": 7, "note": f"shot {i}", "tags": ["sunset"] if i == 4 else ["road"]},
              "metrics": {}} for i in range(n)]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    segs = [{"shot_id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "layout": "kenburns",
             "dur": 1.5, "out_start": 1.5 * i, "level": "intense" if i == 5 else "medium", "drop": i == 5,
             "trans_out": trans[i] if i < len(trans) else None, "trans_dur": 0.3 if i < len(trans) and trans[i] else 0}
            for i in range(n)]
    plan = {"style": "beat-montage", "work": str(tmp_path), "duration": 1.5 * n, "segments": segs, "color": {},
            "tempo": 120, "overlays": [{"type": "hook", "text": "Six parks, one road", "start": 0.1, "duration": 2}]}
    p = tmp_path / "f.plan.json"
    p.write_text(json.dumps(plan))
    return p, plan, {s["id"]: s for s in shots}


class FakeAI:
    name = "fake"

    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def ask(self, prompt, images=None, max_tokens=4000):
        self.prompts.append(prompt)
        return json.dumps(self.answer)


def test_the_director_keeps_to_the_library_and_the_styles_restraint(tmp_path):
    _, plan, by_id = _plan(tmp_path)
    ai = FakeAI({"transitions": [{"cut": 1, "id": "push"}, {"cut": 2, "id": "luma"}, {"cut": 3, "id": "burn"},
                                 {"cut": 4, "id": "zoomblur"}, {"cut": 5, "id": "shake"}, {"cut": 2, "id": "teleport"}],
                 "texts": [{"index": 1, "motion": "slam", "look": "neon"}, {"index": 9, "motion": "slam"}],
                 "effects": [{"shot": 4, "id": "glow", "amount": 0.5}, {"shot": 2, "id": "vhs"},
                             {"shot": 3, "id": "dust"}, {"shot": 1, "id": "sparkles"}],
                 "summary": "warm and punchy"})
    rec = fxlib.direct(plan, by_id, {"name": "beat-montage"}, ai)
    assert rec["by"] == "ai" and "Six parks" in ai.prompts[0] and "zoomblur" in ai.prompts[0]
    on = [s.get("trans_out") for s in plan["segments"][:-1]]
    kinds = {t for t in on if t}
    assert len(kinds) <= 3 and kinds <= set(fxlib.TRANSITIONS)
    # 2 planned -> at most 2 (+0) kept, plus the cut into the drop
    assert sum(1 for t in on if t) <= 3 and on[4]
    assert plan["overlays"][0]["motion"] == "slam" and plan["overlays"][0]["style"]["look"] == "neon"
    fx = [s.get("effect") for s in plan["segments"] if s.get("effect")]
    assert len(fx) == 2 and {f["id"] for f in fx} == {"glow", "vhs"} and all(f["auto"] for f in fx)
    assert plan["effects"]["summary"] == "warm and punchy"


def test_without_an_ai_the_style_stands_unless_rules_are_asked_for(tmp_path):
    _, plan, by_id = _plan(tmp_path)
    before = [s.get("trans_out") for s in plan["segments"]]
    assert fxlib.direct(plan, by_id, {"name": "x"}, None) == {}
    assert [s.get("trans_out") for s in plan["segments"]] == before
    rec = fxlib.direct(plan, by_id, {"name": "x", "effects": {"use": "rules"}}, None)
    assert rec["by"] == "rules"
    after = [s.get("trans_out") for s in plan["segments"]]
    assert [bool(t) for t in after] == [bool(t) for t in before]     # the same cuts carry a transition
    assert after[3] in ("leak", "luma")                               # into the sunset: warm light leads in


def test_ordered_transitions_and_recipes_are_left_alone(tmp_path):
    _, plan, by_id = _plan(tmp_path)
    ai = FakeAI({"transitions": [{"cut": 1, "id": "push"}], "texts": [], "effects": []})
    before = [s.get("trans_out") for s in plan["segments"]]
    fxlib.direct(plan, by_id, {"name": "x", "transitions": {"order": ["iris"]}}, ai)
    assert [s.get("trans_out") for s in plan["segments"]] == before
    assert "leave transitions empty" in ai.prompts[0]


def test_effect_edits_and_the_new_transitions(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p, _, _ = _plan(tmp_path)
    planedit.apply(p, [{"op": "effect", "segment": 2, "id": "dream", "amount": 0.4},
                       {"op": "transition", "segment": 1, "to": "burn"},
                       {"op": "edit_text", "index": 1, "style": {"look": "glow"}}])
    plan = json.loads(p.read_text())
    assert plan["segments"][1]["effect"] == {"id": "dream", "amount": 0.4}
    assert plan["segments"][0]["trans_out"] == "burn" and plan["segments"][0]["trans_dur"] > 0
    assert plan["overlays"][0]["style"]["look"] == "glow"
    planedit.apply(p, [{"op": "effect", "segment": 2, "id": None}])
    assert "effect" not in json.loads(p.read_text())["segments"][1]
    from tripshots.util import ReelError
    with pytest.raises(ReelError):
        planedit.apply(p, [{"op": "effect", "segment": 2, "id": "sparkles"}])
    with pytest.raises(ReelError):
        planedit.apply(p, [{"op": "edit_text", "index": 1, "style": {"look": "chrome"}}])


def test_the_catalog_is_complete_and_the_pickers_draw_it(tmp_path):
    lib = fxlib.catalog()
    assert {r["id"] for r in lib["transitions"]} == set(fxlib.TRANSITIONS)
    assert all(r["energy"] in ("calm", "medium", "intense") for k in lib for r in lib[k])
    from PIL import Image
    from tripshots import server
    p, plan, by_id = _plan(tmp_path, n=2, trans=(None,))
    shots = json.loads((tmp_path / "shots_scored.json").read_text())
    for i, s in enumerate(shots):
        f = tmp_path / f"t{i}.jpg"
        Image.new("RGB", (400, 300), (60 * i + 40, 100, 160)).save(f)
        s["thumb"] = str(f)
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    t = server.fx_thumb(p, 1, "transition", "push")
    e = server.fx_thumb(p, 1, "effect", "glow")
    with Image.open(t) as im:
        assert im.size == (432, 256)
    with Image.open(e) as im:
        assert im.size == (288, 256)
    assert server.fx_thumb(p, 1, "effect", "nope") is None


def _people_plan(tmp_path, n=8):
    """A reel with you in it: shot 4 a long clip of you big in frame, shot 3 a held photo of you."""
    from PIL import Image
    p, plan, by_id = _plan(tmp_path, n=n, trans=(None,) * n)
    for i, s in enumerate(by_id.values()):
        f = tmp_path / f"th{i}.jpg"
        Image.new("RGB", (160, 90), (30 * i % 255, 120, 200)).save(f)
        s["thumb"] = str(f)
        s["ai"]["landmark"] = f"place {i}"
    for i in (2, 3):
        plan["segments"][i]["people"] = True
    you = plan["segments"][3]
    you.update({"kind": "video", "dur": 3.0, "subject": {"x0": 0.3, "y0": 0.2, "x1": 0.7, "y1": 0.9}})
    t = 0.0
    for sg in plan["segments"]:
        sg["out_start"], t = t, t + float(sg["dur"])
    plan["segments"][-2]["role"] = "peak"
    shots = list(by_id.values()) + [{"id": f"X{i}", "thumb": by_id["S0"]["thumb"], "kind": "photo",
                                     "ai": {"score": 6, "landmark": f"other {i}"}} for i in range(12)]
    return plan, by_id, shots


def test_signature_moves_come_without_a_style_asking(tmp_path):
    """A reel made from just a song gets the photo wall, colour bloom, ... when the footage can carry them."""
    plan, by_id, shots = _people_plan(tmp_path)
    ai = FakeAI({"transitions": [], "texts": [], "effects": [],
                 "moves": [{"id": "photo_wall", "shots": [1]},                  # shot 1 can't carry it: dropped
                           {"id": "photo_wall", "shots": [3], "why": "you mid-reel"},
                           {"id": "colour_bloom", "shots": [7, 1, 2]},           # at most two shots
                           {"id": "silhouette", "shots": [4]},                   # a third kind: over the limit
                           {"id": "teleport", "shots": [2]}]})
    rec = fxlib.direct(plan, by_id, {"name": "beat-montage"}, ai, shots)
    assert "SIGNATURE MOVES" in ai.prompts[0] and '"photo_wall": [3, 4]' in ai.prompts[0]
    segs = plan["segments"]
    assert segs[2].get("mosaic") and segs[2]["mosaic"]["cells"]
    assert [i + 1 for i, s in enumerate(segs) if s.get("colour_in")] == [1, 7]
    assert not any(s.get("silhouette") for s in segs)
    assert [m["id"] for m in plan["moves"]] == ["photo_wall", "colour_bloom"]
    assert any("photo wall" in c for c in rec["changes"])


def test_moves_keep_to_the_shots_that_can_carry_them(tmp_path):
    plan, by_id, shots = _people_plan(tmp_path)
    ai = FakeAI({"moves": [{"id": "backdrop_places", "shots": [2]},              # a photo: no backdrop swap
                           {"id": "silhouette", "shots": [1, 3, 4]},            # shot 1 has nobody in it
                           {"id": "grid_lines"}]})
    fxlib.direct(plan, by_id, {"name": "x"}, ai, shots)
    segs = plan["segments"]
    assert not any(s.get("backdrop") for s in segs)
    assert [i + 1 for i, s in enumerate(segs) if s.get("silhouette")] == [3, 4] and plan["grid"]["cols"] == 8
    # a style that already does a move isn't offered it again
    plan2, by2, shots2 = _people_plan(tmp_path)
    el = fxlib.eligible(plan2, {"motion": {"mosaic": True, "grid": {"cols": 8}}})
    assert el["photo_wall"] == [] and "grid_lines" not in el


def test_without_an_ai_one_move_by_rules_and_the_editor_chooses_again(tmp_path, monkeypatch):
    plan, by_id, shots = _people_plan(tmp_path)
    rec = fxlib.direct(plan, by_id, {"name": "x"}, None, shots)
    assert rec["by"] == "rules" and plan["segments"][3].get("backdrop", {}).get("mode") == "places"
    assert [s.get("trans_out") for s in plan["segments"]] == [None] * len(plan["segments"])   # transitions stand
    assert fxlib.clear_moves(plan) == 1 and not plan["segments"][3].get("backdrop") and "moves" not in plan
    plan["tempo"] = 80   # a slower song: the photo wall instead
    fxlib.direct(plan, by_id, {"name": "x"}, None, shots)
    assert any(s.get("mosaic") for s in plan["segments"])


def test_trend_moves_draw_what_they_promise():
    a, b = _frames()
    m = np.zeros(a.shape[:2], np.float32)
    m[100:220, 60:120] = 1.0   # "the person"
    pop = motion.isolate(a, m, "pop", 1.0)
    assert (pop[150, 90] == a[150, 90]).all()                          # the person keeps their colour
    assert np.ptp(pop[20, 170].astype(int)) < 4                        # the world round them is grey
    lit = motion.isolate(a, m, "spotlight", 1.0)
    assert lit[10:40, :40].mean() < 0.5 * a[10:40, :40].mean() and (lit[150, 90] == a[150, 90]).all()
    st = motion.sticker(a, m)
    assert (st[150, 90] == a[150, 90]).all() and st[100 - 3, 90].min() > 220   # a white outline round them
    thumbs = [np.full((40, 40, 3), v, np.uint8) for v in (30, 90, 150, 210)]
    first = motion.camera_roll(b, thumbs, 4, 0.1)
    assert np.abs(first.astype(int) - b).mean() > 20                     # the grid, not the shot
    assert np.abs(motion.camera_roll(b, thumbs, 4, 0.999).astype(int) - b).mean() < 6   # opened into the shot


def test_the_director_sets_up_the_trend_moves_with_its_own_settings(tmp_path):
    plan, by_id, shots = _people_plan(tmp_path)
    plan["tempo"], plan["beats"] = 120, [k * 0.5 for k in range(40)]
    by_id["S2"]["ai"]["shot_size"] = "medium"                                # you head to toe in shot 3
    by_id["S5"]["ai"]["shot_size"] = "wide"                                  # a speck in a landscape: no cut-out
    assert 3 in fxlib.eligible(plan, {}, by_id)["isolate"]
    ai = FakeAI({"transitions": [{"cut": 5, "id": "cube", "params": {"direction": "up", "speed": 9}}],
                 "moves": [{"id": "freeze_intro", "shots": [4], "settings": {"beats": 3, "outline": False}},
                           {"id": "spotlight", "shots": [3], "settings": {"amount": 2}}]})
    rec = fxlib.direct(plan, by_id, {"name": "x"}, ai, shots)
    segs = plan["segments"]
    assert segs[4]["trans_out"] == "cube" and segs[4]["trans_params"] == {"direction": "up"}   # unknown param dropped
    pz = segs[3]["pose"]
    assert pz["dur"] == 1.4 and pz["outline"] is False and pz["at"] >= 0.25 and pz["at"] + 1.4 <= 3.0
    assert segs[2]["isolate"] == {"kind": "spotlight", "amount": 0.9}                          # clipped into range
    assert any("freeze-frame intro" in c for c in rec["changes"]) and "Settings each move takes" in ai.prompts[0]
    assert fxlib.clear_moves(plan) == 2 and not segs[3].get("pose") and not segs[2].get("isolate")
    # a tripod clip of you: the clone trail, with its copies clipped to five, early in the shot
    plan, by_id, shots = _people_plan(tmp_path)
    plan["tempo"], plan["beats"] = 120, [k * 0.5 for k in range(40)]
    by_id["S3"]["ai"]["motion"] = "static"
    ai = FakeAI({"moves": [{"id": "clone_trail", "shots": [4], "settings": {"copies": 9}}]})
    fxlib.direct(plan, by_id, {"name": "x"}, ai, shots)
    cl = plan["segments"][3]["clones"]["times"]
    assert 2 <= len(cl) <= 5 and cl == sorted(cl) and cl[-1] < 3.0 and '"clone": [4]' in ai.prompts[0]


def test_clone_trail_needs_a_still_camera_and_camera_roll_opens_the_reel(tmp_path):
    plan, by_id, shots = _people_plan(tmp_path)
    by_id["S3"]["ai"]["motion"] = "pan"
    plan["segments"][0]["dur"] = 2.0
    el = fxlib.eligible(plan, {}, by_id)
    assert el["clone"] == [] and 1 in el["opener"] and 4 in el["isolate"]
    ai = FakeAI({"moves": [{"id": "camera_roll", "shots": [1], "settings": {"seconds": 1.2}},
                           {"id": "colour_pop", "shots": [4]}]})
    fxlib.direct(plan, by_id, {"name": "x"}, ai, shots)
    segs = plan["segments"]
    assert segs[0]["roll"]["dur"] == 1.1 and len(segs[0]["roll"]["cells"]) >= 6   # at most 0.55 of the shot
    assert segs[3]["isolate"] == {"kind": "pop", "amount": 1.0}


def test_people_tracker_looks_again_after_missing_someone(monkeypatch):
    from tripshots import render
    seen = iter([None, None, np.ones((4, 4), np.float32), None, np.zeros((4, 4), np.float32)])
    pt = render.People()
    monkeypatch.setattr(pt, "at", lambda fr: next(seen))
    fr = np.zeros((4, 4, 3), np.uint8)
    assert pt.follow(0, fr, 0) is None and pt.follow(0, fr, 3) is None    # (waits a few frames before looking again)
    assert pt.follow(0, fr, 6) is None and pt.follow(0, fr, 12).mean() == 1.0
    assert pt.follow(0, fr, 14).mean() == 1.0                             # a frame without them keeps the last mask
    assert 0.4 < pt.follow(0, fr, 16).mean() < 0.5                        # smoothed over time


def test_flash_zoom_punches_in_on_the_person_on_the_beats():
    from tripshots import motion
    zp = {"times": [0.5, 1.0, 1.5], "zooms": [1.2, 1.44, 1.0]}
    assert motion.flash_zoom_at(zp, 0.3) == (1.0, 0.0, 0.0)                 # nothing before the first hit
    z, fl, bl = motion.flash_zoom_at(zp, 0.5)
    assert z == 1.0 and fl == 0.8 and bl > 0                                # the hit: full flash, the snap starts
    assert motion.flash_zoom_at(zp, 0.8)[:2] == (1.2, 0.0)                  # landed, flash gone
    assert motion.flash_zoom_at(zp, 1.2)[0] == 1.44 and motion.flash_zoom_at(zp, 1.8)[0] == 1.0   # ... and back out
    assert 0.2 < motion.flash_zoom_at(zp, 0.49)[1] < 0.3                    # a frame of glow before the hit
    # the person is on the right: the zoom keeps them in frame, centred on their head
    fr = np.zeros((320, 180, 3), np.uint8)
    fr[60:300, 120:160] = 200
    mask = np.zeros((320, 180), np.float32)
    mask[60:300, 120:160] = 1.0
    x, y = motion.subject_point(mask, "face")
    assert 0.69 < x < 0.86 and y < 0.3
    assert motion.subject_point(mask, "person")[1] > 0.45 and motion.subject_point(None) is None
    out = motion.flash_zoom(fr, (x, y), 1.5, 0.0, 0.0)
    lit = np.nonzero(out[200, :, 0] > 100)[0]
    assert len(lit) >= 55 and lit.min() < 100 < 120 < lit.max()      # bigger (40 -> 60 px) and moved in from the edge
    warm = motion.flash_zoom(fr, (0.5, 0.5), 1.0, 0.8, 0.0, "warm")
    assert warm[5, 5, 0] > warm[5, 5, 2] > 100               # a warm flash is warm


def test_the_director_sets_up_the_flash_zoom_on_the_beats_before_the_cut(tmp_path):
    plan, by_id, shots = _people_plan(tmp_path)
    plan["tempo"], plan["beats"] = 120, [k * 0.5 for k in range(40)]
    el = fxlib.eligible(plan, {}, by_id)
    assert 4 in el["zoom"]
    ai = FakeAI({"moves": [{"id": "flash_zoom", "shots": [4],
                            "settings": {"hits": 3, "zoom": 3, "flash": "warm", "focus": "chin", "out": True}}]})
    rec = fxlib.direct(plan, by_id, {"name": "x"}, ai, shots)
    seg = plan["segments"][3]
    zp = seg["zoompunch"]
    a, b = fxlib._ends(seg, plan)
    assert len(zp["times"]) == 3 and zp["times"] == sorted(zp["times"]) and a < zp["times"][0] and zp["times"][-1] <= b - 0.2
    assert zp["zooms"] == [round(1.8 ** 0.5, 3), 1.8, 1.0]           # clipped to 1.8; out = back to the whole frame
    assert zp["flash"] == "warm" and zp["focus"] == "face"            # (an unknown focus falls back)
    assert any("flash zoom" in c for c in rec["changes"]) and "zoom 1.25-1.8" in ai.prompts[0]
    assert fxlib.clear_moves(plan) == 1 and "zoompunch" not in seg


def test_without_an_ai_the_drop_gets_the_flash_zoom(tmp_path):
    plan, by_id, shots = _people_plan(tmp_path)
    plan["tempo"], plan["beats"] = 128, [k * 60 / 128 for k in range(60)]
    for s in plan["segments"]:
        s["people"] = False
    plan["segments"][4]["people"] = True
    plan["segments"][4]["drop"] = True
    moves = fxlib._rule_moves(plan, by_id, fxlib.eligible(plan, {}, by_id))
    assert moves and moves[0]["id"] == "flash_zoom" and moves[0]["shots"] == [5]
