"""The story engine: roles, varied rhythm, casting, formats, words, match cuts, critic, results, parallax."""
import json

import numpy as np
import pytest

from tripshots import critic, formats, lyrics, matchcut, parallax, results, story
from tripshots.config import load_style


def _grid(bl=0.5, n=80, drop_at=8.0):
    beats = [round(i * bl, 3) for i in range(n)]
    energy = [0.3 if b < drop_at else 0.85 for b in beats]
    return {"beats_all": beats, "energy_all": energy, "beat_len": bl, "beats": beats, "thresholds": (0.35, 0.7)}


def test_rhythm_has_an_arc_and_varies():
    r = story.rhythm(_grid(), load_style("beat-montage"), 15)
    segs = r["segments"]
    roles = [s["role"] for s in segs]
    assert roles[0] == "hook" and roles[-1] == "ending" and roles.count("peak") == 1
    assert roles.index("peak") > roles.index("build")             # the build runs into the payoff
    ds = [s["dur"] for s in segs]
    assert max(ds) / min(ds) >= 3                                 # not a metronome
    t = 0.0
    for s in segs:                                                # tiles the timeline on whole frames
        assert abs(s["out_start"] - t) < 1e-3 and abs(s["dur"] * 30 - round(s["dur"] * 30)) < 1e-3
        t += s["dur"]
    assert abs(t - r["duration"]) < 1e-3 and 13.5 <= r["duration"] <= 16
    peak = next(s for s in segs if s["role"] == "peak")
    assert peak["dur"] >= 2.0 and abs(peak["out_start"] - 7.0) <= 1.0    # held, on the drop
    builds = [s["dur"] for s in segs if s["role"] == "build"]
    assert builds == sorted(builds, reverse=True)                  # accelerating


def test_dialogue_rhythm_cuts_between_lines_and_lands_the_punchline():
    words = {"kind": "dialogue", "lines": [{"start": 0.2, "end": 1.9, "text": "a"}, {"start": 2.3, "end": 4.0, "text": "b"},
                                           {"start": 4.4, "end": 6.2, "text": "c"}, {"start": 6.8, "end": 8.0, "text": "d"},
                                           {"start": 8.3, "end": 10.5, "text": "e"}], "punch_t": 6.8}
    r = story.rhythm(_grid(), load_style("beat-montage"), 12, words=words)
    starts = [s["out_start"] for s in r["segments"]]
    assert any(abs(t - 2.1) <= 0.12 for t in starts) and any(abs(t - 6.5) <= 0.12 for t in starts)
    peak = next(s for s in r["segments"] if s["role"] == "peak")
    assert abs(peak["out_start"] - 6.5) <= 0.12


def _shot(i, score=7, people=0, kind="video", mood="calm", pan=0.0, role=None):
    return {"id": f"S{i:03d}", "kind": kind, "src": f"/x/{i}.mp4", "sig": f"g{i}", "t0": 0, "t1": 10, "w": 1920,
            "h": 1080, "fps": 30, "thumb": "", "metrics": {"pan": pan, "activity": 0.0},
            "ai": {"score": score, "mood": mood, "role": role, "people": {"count": people, "activity": ""}}}


def test_cast_puts_the_best_where_it_matters_and_people_early():
    shots = [_shot(0, 9, role="hook", pan=0.01), _shot(1, 8.5, mood="dynamic", pan=0.01), _shot(2, 6, people=1),
             _shot(3, 6), _shot(4, 6), _shot(5, 7, role="closer")]
    segs = [{"role": r, "out_start": t, "dur": 1.0} for r, t in
            (("hook", 0), ("setup", 1.5), ("build", 2.5), ("peak", 3.5), ("release", 6), ("ending", 7))]
    style = load_style("beat-montage")
    style["loop"] = False
    order = story.cast(shots, segs, style)
    ids = [s["id"] for s in order]
    assert ids[0] == "S000" and ids[3] == "S001" and ids[5] == "S005"
    assert ids[1] == "S002"                                          # the person, inside the first 3 s
    assert len(set(ids)) == 6


def test_format_choice_and_list_labels():
    places = {"S001": "Horseshoe Bend, Arizona", "S002": "Arches, Utah", "S003": "Zion, Utah"}
    assert formats.choose("auto", [], places, None) == "list"
    assert formats.choose("auto", [], {}, {"kind": "dialogue"}) == "pov"
    assert formats.choose("auto", [], {}, None) == "montage"
    plan = {"segments": [{"role": "hook", "out_start": 0, "dur": 1, "shot_id": "S003"},
                         {"role": "setup", "out_start": 1, "dur": 1.5, "shot_id": "S001"},
                         {"role": "peak", "out_start": 2.5, "dur": 2, "shot_id": "S002"}], "overlays": []}
    formats.apply(plan, "list", {}, places, {})
    assert [o["text"] for o in plan["overlays"]] == ["1 · Horseshoe Bend", "2 · Arches"]
    pool = [{"id": "S001", "ai": {"score": 9}}, {"id": "S002", "ai": {"score": 6}}, {"id": "S003", "ai": {"score": 7}}]
    assert [s["id"] for s in formats.list_order(pool, places)] == ["S002", "S003", "S001"]   # best place last


def test_words_cleaning_window_and_captions():
    w = lyrics._clean({"kind": "dialogue", "language": "ml", "punch": 1,
                       "lines": [{"start": 1.0, "end": 2.5, "text": "നീ", "english": "You"},
                                 {"start": 2.2, "end": 4.0, "text": "വാ", "english": "Come here"},
                                 {"start": 5, "end": 4, "text": "bad"}]})
    assert len(w["lines"]) == 2 and w["lines"][0]["end"] == 2.2 and w["punch_t"] == 2.2
    win = lyrics.window(w, 1.0, 10)
    assert win["lines"][0]["start"] == 0.0 and win["punch_t"] == 1.2
    caps = lyrics.caption_overlays(win, 10, "auto")
    assert [c["text"] for c in caps] == ["You", "Come here"]          # Malayalam dialogue -> English subtitles
    assert lyrics.caption_overlays({**win, "kind": "song"}, 10, "auto") == []


def test_matchcut_direction_and_whip(monkeypatch):
    assert matchcut.direction((0.1, 0.0)) == "right" and matchcut.direction((0.0, -0.2)) == "up"
    assert matchcut.direction((0.01, 0.0)) is None
    segs = [{"kind": "video", "flow": [0.1, 0], "trans_out": "whip", "trans_params": {}, "role": "release",
             "out_start": 0, "dur": 1},
            {"kind": "video", "flow": [0.12, 0], "trans_out": "dissolve", "role": "release", "out_start": 1, "dur": 1},
            {"kind": "video", "flow": [0.1, 0], "trans_out": None, "role": "ending", "out_start": 2, "dur": 1}]
    monkeypatch.setattr(matchcut, "_measure", lambda plan: None)
    matchcut.apply({"segments": segs}, {})
    assert segs[0]["trans_params"]["direction"] == "left"            # the swipe follows the camera
    assert segs[1]["trans_out"] is None and segs[1]["match"] == "motion"


def test_critic_finds_and_fixes():
    segs = [{"kind": "photo", "layout": "kenburns", "out_start": 0, "dur": 1.6, "shot_id": "A", "src": "a", "role": "hook"},
            {"kind": "photo", "layout": "kenburns", "out_start": 1.6, "dur": 1.6, "shot_id": "B", "src": "b"},
            {"kind": "photo", "layout": "kenburns", "out_start": 3.2, "dur": 1.6, "shot_id": "C", "src": "c"}]
    plan = {"segments": segs, "overlays": [{"type": "hook", "text": "a b c", "start": 0.5, "duration": 2}],
            "duration": 4.8, "motion": {}}
    by_id = {k: {"id": k, "kind": "photo", "thumb": "", "ai": {"people": {"count": 1 if k == "C" else 0}}} for k in "ABC"}
    cs = critic.checks(plan, by_id, list(by_id.values()))
    bad = {c["check"] for c in cs if not c["ok"]}
    assert {"first_second", "hook_text", "rhythm", "ending"} <= bad
    critic.fix(plan, by_id, list(by_id.values()), cs)
    assert plan["motion"]["hook_punch"] and plan["loop"] and plan["overlays"][0]["start"] == 0.1


def test_results_score_and_preferences(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "STORE", tmp_path / "results.json")
    for i, (fmt, watch, sends) in enumerate([("list", 9, 30), ("list", 8, 25), ("montage", 4, 2), ("montage", 5, 1),
                                             ("pov", 6, 5)]):
        p = tmp_path / f"r{i}.plan.json"
        p.write_text(json.dumps({"style": "x", "duration": 12, "segments": [], "overlays": [],
                                 "story": {"format": fmt, "hook_type": "number" if fmt == "list" else "feeling"}}))
        row = results.add(tmp_path / f"r{i}.mp4", {"views": 1000, "avg_watch": watch, "sends": sends})
        assert 0 <= row["score"] <= 1
    pr = results.preferences()
    assert pr["format"] == "list" and pr["hook_type"] == "number" and pr["confident"]


def test_parallax_depth_estimate_and_shift():
    img = np.zeros((360, 640, 3), np.uint8)
    img[:150] = (120, 170, 230)                                      # sky
    img[150:] = (60, 110, 50)
    img[150:] = np.clip(img[150:].astype(int) + np.random.default_rng(0).integers(-40, 40, img[150:].shape), 0, 255)
    img[250:330, 300:340] = (30, 30, 30)                             # something near
    d = parallax._estimate_depth(img)
    assert d[:100].mean() < d[300:].mean()                           # the sky is far, the ground near
    mv = parallax.Mover(img, d, 20, 1.0)
    M = np.array([[1, 0, 0], [0, 1, 0]], np.float64)
    a, b = mv.frame(img, M, 0.0), mv.frame(img, M, 1.0)
    assert a.shape == img.shape and np.abs(a.astype(int) - b.astype(int)).mean() > 0.5


def test_hook_rules():
    from tripshots.ai import _hook_rules
    assert _hook_rules("3 stops in Utah you can't skip", "list") > _hook_rules("Wanderlust vibes in paradise forever and ever", "list")


def test_transitions_are_restrained():
    segs = [{"role": r, "level": l, "trans_out": t, "trans_params": {}} for r, l, t in
            (("hook", "medium", "whip"), ("setup", "medium", "glitch"), ("setup", "medium", "blur"),
             ("build", "medium", "blur"), ("build", "intense", "whip"), ("peak", "intense", "zoom_in"),
             ("release", "intense", "whip"), ("release", "medium", "blur"), ("ending", "calm", None))]
    story.restrain_transitions(segs)
    kept = [i for i, s in enumerate(segs) if s.get("trans_out")]
    assert 4 in kept                                   # into the payoff
    assert 0 not in kept and 1 not in kept             # no effect on the hook, no glitch in a medium section
    assert len(kept) <= 3
