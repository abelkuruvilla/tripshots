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
