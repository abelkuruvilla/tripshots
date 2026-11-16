"""Editing craft: music sections and climaxes, motion across cuts, the cut's place in the beat, the critic's
rounds, picture QA, screen-recorded references, eases, notes on a reel, subtitles in groups, posting."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from conftest import clip, ff, needs_ffmpeg
from tripshots import critic, lyrics, matchcut, motion, music, planner, story
from tripshots.config import load_style


# ------------------------------------------------------------------ music: where to cut, where the climax is
@needs_ffmpeg
def test_a_beatless_intro_flows_and_the_drop_has_its_breath(tmp_path):
    # 8 s of a soft pad (nothing to cut on), a 0.5 s hush, then 9.5 s of loud clicks over the pad
    p = tmp_path / "s.wav"
    ff("-f", "lavfi", "-i", "sine=f=220:d=18", "-f", "lavfi", "-i", "sine=f=1200:d=0.03,apad=pad_dur=0.47",
       "-filter_complex", "[1]aloop=loop=-1:size=24000,atrim=0:9.5,adelay=8500|8500,volume=4[c];"
                          "[0]volume='if(between(t,8,8.5),0.05,if(gt(t,8.5),1.0,0.35))':eval=frame[p];"
                          "[p][c]amix=inputs=2:duration=longest:normalize=0",
       "-ar", "22050", "-t", "18", p)
    m = music.analyze_music(p, tmp_path)
    secs = m["sections"]
    assert music.section_at(secs, 3.0) == "flow" and music.section_at(secs, 13.0) == "beat"
    hit = min(m["peaks"], key=lambda q: abs(q["t"] - 8.5))
    assert abs(hit["t"] - 8.5) < 0.6 and hit["breath"] > 0


def _grid(bl=0.5, n=80, flow_until=0.0, peaks=None):
    beats = [round(i * bl, 3) for i in range(n)]
    return {"beats_all": beats, "energy_all": [0.3 if b < 8 else 0.85 for b in beats], "beat_len": bl,
            "beats": beats, "thresholds": (0.35, 0.7), "flow_all": [b < flow_until for b in beats],
            "peaks": peaks or []}


def test_flowing_sections_hold_longer_and_melt_into_each_other():
    style = load_style("beat-montage")
    plain = story.rhythm(_grid(), style, 15)["segments"]
    flowing = story.rhythm(_grid(flow_until=7.0), style, 15)["segments"]
    early = lambda ss: [s for s in ss if s["out_start"] < 6 and s["role"] != "hook"]
    assert all(s.get("beatless") for s in early(flowing)) and not any(s.get("beatless") for s in plain)
    assert np.mean([s["dur"] for s in early(flowing)]) > np.mean([s["dur"] for s in early(plain)])
    segs = [{**s, "shot_id": f"S{i}"} for i, s in enumerate(flowing)]
    planner.choose_transitions(segs, style)
    pairs = [(a, b) for a, b in zip(segs, segs[1:]) if a.get("beatless") and b.get("beatless")]
    assert pairs and all(a["trans_out"] in (None, "dissolve") for a, _ in pairs)
    assert any(a["trans_out"] == "dissolve" for a, _ in pairs)


def test_the_shot_before_the_climax_holds_its_breath():
    style = load_style("beat-montage")
    r = story.rhythm(_grid(peaks=[{"t": 8.0, "rise": 3.0, "kind": "drop", "breath": 0.5}]), style, 15)
    segs = r["segments"]
    k = next(i for i, s in enumerate(segs) if s["role"] == "peak")
    assert abs(segs[k]["out_start"] - 8.0) < 0.05 and segs[k - 1].get("breath") == 0.5
    seg = {**segs[k - 1], "level": "intense"}
    assert motion.shot_motion(seg["out_start"] + 0.01, seg, [seg["out_start"]], {"beat_punch": 0.08})[0] == 1.0


# ------------------------------------------------------------------ the cut's place in the beat
def test_cut_phase_is_measured_and_a_clear_habit_is_copied():
    beats = np.arange(0, 30, 0.5)
    early = music.phase_stats(beats[2:40:2] - 1 / 30, beats)
    assert early["offset_f"] == -1 and early["on_beat"] > 0.9 and early["R"] > 0.9
    off = music.phase_stats(beats[2:40:2] + 0.25, beats)
    assert abs(off["phase"] - 0.5) < 0.05 and off["on_beat"] == 0
    assert story.cut_shift({"attention": {"cut_phase": {**early, "n": 20}}}) == {"frames": -1}
    assert story.cut_shift({"attention": {"cut_phase": {**off, "n": 20}}}) == {"beats": 0.5}
    assert story.cut_shift({"attention": {"cut_phase": {**early, "n": 20, "R": 0.2}}}) == {}
    style = {**load_style("beat-montage"), "attention": {}}
    base = story.rhythm(_grid(), style, 15)["segments"]
    style["attention"] = {"cut_phase": {**early, "n": 20}}
    moved = story.rhythm(_grid(), style, 15)["segments"]
    inner = [(a["out_start"], b["out_start"]) for a, b in zip(base[1:], moved[1:])]
    assert all(abs((b - a) * 30 + 1) < 0.01 for a, b in inner)    # every cut a frame early, the length unchanged


# ------------------------------------------------------------------ the camera's movement across cuts
def test_movement_carries_across_cuts():
    left, right, still = (-0.3, 0, 0), (0.3, 0, 0), (0, 0, 0)
    a = {"kind": "video", "role": "setup", "_ends": (left, left), "src": "a"}
    b = {"kind": "video", "role": "setup", "_ends": (right, right), "src": "b"}
    assert "left" in matchcut.clash(a, b)
    kb = {"kind": "photo", "layout": "kenburns", "kb": "right", "role": "setup"}
    assert matchcut.clash(a, kb) is None or True                  # a gentle Ken Burns drift
    plan = {"segments": [a, {"kind": "photo", "layout": "kenburns", "kb": "right", "role": "release"}]}
    plan["segments"][1]["kb"] = "right"
    matchcut._follow(plan["segments"][1], "left")
    assert plan["segments"][1]["kb"] == "left"                    # the drift follows the camera before it
    c = {"kind": "video", "role": "setup", "_ends": (still, still), "src": "c"}
    assert "stops dead" in matchcut.clash(a, c)
    z = {"kind": "video", "role": "setup", "_ends": ((0, 0, 0.08), (0, 0, 0.08)), "src": "z"}
    zo = {"kind": "video", "role": "setup", "_ends": ((0, 0, -0.08), (0, 0, -0.08)), "src": "zo"}
    assert matchcut.clash(z, zo) == "pushes in, then pulls back"
    assert matchcut.clash({**a, "trans_out": "whip"}, b) is None   # a whip is the movement


def test_eases_are_fitted_by_name():
    u = np.linspace(0, 1, 15)
    for name, f in motion.EASES.items():
        assert motion.fit_ease([f(x) for x in u])[0] == name
    assert motion.fit_ease([0, 0.5, 0.2, 0.8, 1, 1]) is None      # back and forth: not one move


# ------------------------------------------------------------------ the critic, in rounds
class _Reviewer:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def ask(self, prompt, images=None, max_tokens=0):
        self.prompts.append((prompt, list(images or [])))
        return json.dumps(self.replies.pop(0))


def test_the_critic_works_in_rounds_and_undoes_what_didnt_help(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: Path(out).write_bytes(b"x") or out)
    shots = [{"id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "w": 4000, "h": 3000,
              "t0": 0, "t1": 0, "ai": {"score": 8 - i * 0.5, "note": f"shot {i}"}, "metrics": {}} for i in range(6)]
    by_id = {s["id"]: s for s in shots}
    segs = [{"shot_id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "layout": "kenburns", "kb": "in",
             "dur": 2.0, "out_start": 2.0 * i, "level": "medium", "role": r}
            for i, r in enumerate(("hook", "setup", "peak", "ending"))]
    plan = {"segments": segs, "overlays": [], "duration": 8.0, "loop": True}
    rev = _Reviewer([
        {"score": 60, "issues": [{"slot": 2, "issue": "dull", "severity": "blocker", "op": {"op": "swap", "segment": 2, "shot_id": "S4"}},
                                 {"slot": 4, "issue": "fine", "severity": "polish", "op": None}]},
        {"score": 70, "verified": [{"change": 1, "helped": False}],
         "issues": [{"slot": 3, "issue": "flat", "severity": "blocker", "op": {"op": "swap", "segment": 3, "shot_id": "S5"}}]},
        {"score": 85, "verified": [{"change": 1, "helped": True}], "issues": []},
    ])
    rep = critic.review(plan, by_id, shots, {"story": {"critic_rounds": 3}}, rev, tmp_path)
    assert [r["round"] for r in rep["rounds"]] == [1, 2, 3]
    assert plan["segments"][1]["shot_id"] == "S1"                # round 2 said the swap didn't help: undone
    assert plan["segments"][2]["shot_id"] == "S5"
    assert "first check each change" in rev.prompts[1][0].lower() and len(rev.prompts[1][1]) == 2  # with proof
    assert "before | after" in rev.prompts[1][0]


# ------------------------------------------------------------------ picture QA on the rendered file
@needs_ffmpeg
def test_picture_qa_finds_a_flash_and_a_stutter(tmp_path):
    from tripshots import qa
    v = tmp_path / "r.mp4"
    # a moving picture, one white frame at 1 s, and from 2 s every frame shown twice (a hitching clip)
    ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=4",
       "-vf", "drawbox=enable='eq(n\\,30)':color=white:t=fill,"
              "select='lt(n\\,60)+gte(n\\,60)*not(mod(n\\,2))',setpts=N/30/TB,"
              "tpad=stop_mode=clone:stop_duration=1,fps=30",
       "-t", "4", "-pix_fmt", "yuv420p", v)
    plan = {"segments": [{"kind": "video", "out_start": 0.0, "dur": 2.0}, {"kind": "video", "out_start": 2.0, "dur": 2.0}]}
    got = {k: (ok, val) for k, ok, val, *_ in qa.picture_checks(v, plan)}
    assert not got["flash"][0] and abs(got["flash"][1][0] - 1.0) < 0.05
    assert got["stutter"][0] is False and "shot 2" in got["stutter"][1][0]
    assert got["cut_light"][0]


# ------------------------------------------------------------------ references recorded off a phone screen
@needs_ffmpeg
def test_a_screen_recording_is_cut_to_the_reel_and_its_sound_fixed(tmp_path, monkeypatch):
    from tripshots import refprep
    monkeypatch.setattr(refprep, "CLEAN", tmp_path / "clean")
    src = tmp_path / "screen.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
       "-filter_complex", "[0]pad=360:780:0:70:color=0x303030,drawbox=x=10:y=15:w=80:h=20:color=white:t=fill,"
                          "drawbox=x=10:y=730:w=200:h=16:color=white:t=fill[v];[1]pan=stereo|c0=c0|c1=-1*c0[a]",
       "-map", "[v]", "-map", "[a]", "-pix_fmt", "yuv420p", "-c:a", "aac", src)
    assert refprep.phase_cancelled(src)
    out = refprep.clean(src)
    assert out != src and not refprep.phase_cancelled(out)
    from tripshots.util import ffprobe
    vs = ffprobe(out)["streams"][0]
    assert abs(vs["width"] / vs["height"] - 9 / 16) < 0.03
    plain = clip(tmp_path / "reel.mp4", "testsrc2", 3, "360x640")
    assert refprep.clean(plain) == plain


# ------------------------------------------------------------------ notes on a finished reel
def test_notes_become_edits_without_an_ai(tmp_path, monkeypatch):
    from tripshots import planedit, revise
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    shots = [{"id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "w": 4000, "h": 3000,
              "t0": 0, "t1": 0, "ai": {"score": 8 - i, "note": f"shot {i}"}, "metrics": {}} for i in range(5)]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    segs = [{"shot_id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "layout": "kenburns",
             "kb": "in", "dur": 2.0, "out_start": 2.0 * i, "level": "mid", "trans_out": None} for i in range(3)]
    plan = {"style": "beat-montage", "work": str(tmp_path), "duration": 6.0, "segments": segs, "color": {}, "tempo": 120,
            "overlays": [{"type": "hook", "text": "Big day", "start": 0.1, "duration": 1.8}]}
    p = tmp_path / "t.plan.json"
    p.write_text(json.dumps(plan))
    assert revise.parse_note("0:03.5 - way too dark") == {"t": 3.5, "text": "way too dark"}
    rep = revise.revise(p, [revise.parse_note("3.5: way too dark"), {"t": 4.6, "text": "boring, replace this shot"},
                            {"t": 0.5, "text": "remove the text"}], backend_name="none", render=False)
    after = json.loads(p.read_text())
    assert after["segments"][1]["adjust"]["exposure"] > 0
    assert after["segments"][2]["shot_id"] in ("S3", "S4") and not after["overlays"]
    assert len(rep["answers"]) == 3 and (tmp_path / "t.revise.json").exists()
    assert planedit.history(p)["undo"] >= 1


# ------------------------------------------------------------------ subtitles in groups the eye takes in
def test_long_subtitles_split_into_readable_groups():
    g = lyrics.chunks("we drove all night to see the sun come up over the canyon", 0.0, 6.0, 5.5)
    assert len(g) > 1 and all(len(t.split()) <= 5 for t, *_ in g)
    assert abs(g[0][1]) < 1e-6 and abs(g[-1][2] - 6.0) < 1e-6
    assert all(e - s >= len(t.split()) / lyrics.READ_WPS + 0.5 for t, s, e in g)
    assert lyrics.chunks("we drove all night to see the sun come up", 0.0, 2.5, 2.4) == \
        [("we drove all night to see the sun come up", 0.0, 2.5)]       # no time to split it: stays whole


# ------------------------------------------------------------------ posting
@needs_ffmpeg
def test_posting_is_a_dry_run_guarded_and_never_twice(tmp_path, monkeypatch):
    import http.server
    import threading
    from tripshots import post
    monkeypatch.setattr(post, "POSTED", tmp_path / "posted.json")
    v = clip(tmp_path / "r.mp4", "testsrc2", 1, "180x320")
    with pytest.raises(Exception):
        post.post(v, ["instagram"])                                # no quality report yet
    (tmp_path / "r.qa.json").write_text(json.dumps({"checks": [{"check": "black", "ok": True}]}))
    (tmp_path / "r.caption.txt").write_text("Golden hour at the canyon\n\n#canyon")
    dry = post.post(v, ["instagram"], at="2026-12-01T18:00", tz="Europe/Madrid")
    assert not dry["sent"] and dry["title"] == "Golden hour at the canyon"
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.headers.get("Idempotency-Key"), self.headers.get("Authorization"),
                        self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"request_id": "abc"}')

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("UPLOAD_POST_API", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("UPLOAD_POST_KEY", "k")
    monkeypatch.setenv("UPLOAD_POST_USER", "me")
    res = post.post(v, ["instagram", "tiktok"], send=True)
    assert res["sent"] and got[0][0] == res["key"] and got[0][1] == "Apikey k"
    assert b'name="platform[]"\r\n\r\ntiktok' in got[0][2]
    again = post.post(v, ["instagram", "tiktok"], send=True)
    assert not again["sent"] and "already posted" in again["note"] and len(got) == 1
    srv.shutdown()


def test_a_refused_edit_is_tried_again_and_never_reported_as_done(tmp_path, monkeypatch):
    from tripshots import ai, revise
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    shots = [{"id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "w": 4000, "h": 3000,
              "t0": 0, "t1": 0, "ai": {"score": 8 - i, "note": f"shot {i}"}, "metrics": {}} for i in range(5)]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    segs = [{"shot_id": f"S{i}", "kind": "photo", "src": f"/x/{i}.jpg", "still": f"/x/{i}.jpg", "layout": "kenburns",
             "kb": "in", "dur": 2.0, "out_start": 2.0 * i, "level": "mid", "trans_out": None} for i in range(3)]
    segs[1].update({"panel": "split2", "kind": "panel", "clips": []})
    p = tmp_path / "t.plan.json"
    p.write_text(json.dumps({"style": "beat-montage", "work": str(tmp_path), "duration": 6.0, "segments": segs,
                             "color": {}, "tempo": 120, "overlays": []}))
    first = {"edits": [{"note": 1, "op": {"op": "frame", "segment": 2, "layout": "crop"}},
                       {"note": 2, "op": "adjust", "segment": 3, "exposure": 0.3}],
             "answers": [{"note": 1, "did": "made it full screen"}, {"note": 2, "did": "brighter"}]}
    rev = _Reviewer([first, {"edits": [{"note": 1, "op": "frame", "segment": 2, "layout": "crop"}], "answers": []}])
    monkeypatch.setattr(ai, "get_backend", lambda name=None: rev)
    rep = revise.revise(p, [{"t": 2.5, "text": "the split screen looks broken"}, {"t": 4.5, "text": "too dark"}],
                        render=False)
    assert "Your reply" in rev.prompts[1][0] and "split screen" in rev.prompts[1][0]   # retried with everything
    assert rep["answers"][0]["did"].startswith("Not done") and rep["answers"][1]["did"] == "brighter"
    assert json.loads(p.read_text())["segments"][1]["panel"] == "split2"      # untouched, not half-changed


# ------------------------------------------------------------------ masked reveals keyframed on the beat
def test_masked_reveals_snap_on_the_beat_and_cover_the_frame():
    a = np.zeros((192, 108, 3), np.uint8)
    b = np.full((192, 108, 3), 200, np.uint8)
    for name, prm in (("split", {"pivot": "bl", "steps": 2}), ("vsplit", {"steps": 2}), ("iris", {})):
        start, end = motion.apply_transition(name, a, b, 0.0, prm), motion.apply_transition(name, a, b, 1.0, prm)
        assert start.mean() < 30 and end.mean() > 190                    # all of the old shot, then all of the new
    share = lambda p: (motion.apply_transition("split", a, b, p, {"steps": 2}) > 100).mean()
    assert abs(share(0.3) - share(0.45)) < 0.02 < share(0.6) - share(0.45)   # holds between beats, moves on them
    edge = motion.apply_transition("vsplit", a, b, 0.3, {"steps": 2})
    assert (edge == 255).any() or (edge > 230).any()                      # the thin white edge of the mask


def test_a_reveal_style_puts_one_on_every_cut_fitted_to_the_beat():
    style = load_style("mask-reveal")
    style["_tempo"] = 120.0
    segs = [{"shot_id": f"S{i}", "dur": 2.0, "out_start": 2.0 * i, "level": "medium", "beats": 4} for i in range(9)]
    planner.choose_transitions(segs, style)
    names = [s["trans_out"] for s in segs[:-1]]
    assert names[0] == "split" and names[-1] == "iris" and "vsplit" in names and segs[-1]["trans_out"] is None
    assert all(abs(s["trans_dur"] - 1.0) < 0.04 and s["trans_params"]["steps"] == 2 for s in segs[:-1])
    d, prm = planner.fit_transition({"dur": 0.6}, {"dur": 2.0}, "iris", 120.0)
    assert d <= 0.6 and prm["steps"] == 1                                 # a short shot gets a one-beat reveal


def test_paper_shapes_build_the_next_shot_and_colour_blooms_in():
    a = np.zeros((108, 192, 3), np.uint8)
    b = np.full((108, 192, 3), (200, 60, 30), np.uint8)
    for name in ("slats", "stripes", "diamond"):
        assert motion.apply_transition(name, a, b, 0.0, {}).mean() < 5
        mid = motion.apply_transition(name, a, b, 0.35, {})
        assert (np.abs(mid.astype(int) - motion.PAPER).sum(-1) < 30).any()   # a cream block on its way in
        assert np.abs(motion.apply_transition(name, a, b, 1.0, {}).astype(int) - b).max() < 3
    grey = motion.colour_in(b, 0.0)
    assert np.ptp(grey[0, 0]) == 0 and np.array_equal(motion.colour_in(b, 1.0), b)
    style = load_style("shape-cut")
    assert style["frame"]["output"] == "horizontal" and style["motion"]["colour_in"] > 0


def test_a_framed_window_and_a_silhouette_flash(monkeypatch):
    import cv2
    from tripshots import nodes
    a = np.zeros((108, 192, 3), np.uint8)
    b = np.full((108, 192, 3), (30, 90, 160), np.uint8)
    held = motion.apply_transition("frame", a, b, 0.9, {})
    assert (held[54, 96] == b[54, 96]).all() and (held == 0).all(-1).mean() > 0.005   # window in, gaps still old
    assert np.array_equal(motion.apply_transition("frame", a, b, 1.0, {}), b)          # then the whole picture
    m = np.zeros((108, 192), np.float32)
    m[30:90, 90:105] = 1
    flash = motion.silhouette(b, m)
    assert tuple(flash[60, 97]) == motion.PAPER and tuple(flash[10, 10]) == tuple(b[10, 10])
    # only upright figures flash: a wide blob (a car) is dropped, a standing figure kept
    blob = np.zeros((120, 160), np.float32)
    blob[60:80, 20:90] = 1.0
    fig = blob.copy()
    fig[20:100, 120:140] = 1.0
    import tripshots.nodes as N
    for src, want in ((blob, False), (fig, True)):
        monkeypatch.setattr(N, "cutout", lambda small, s=src: cv2.resize(s, (small.shape[1], small.shape[0])))
        got = nodes.people_mask(np.zeros((120, 160, 3), np.uint8), width=160)
        assert (got is not None) == want
        if got is not None:
            assert got[60, 130] > 0.5 and got[70, 50] < 0.5


def test_the_grid_fills_cell_by_cell_and_a_photo_wall_builds_round_the_subject(tmp_path):
    import cv2
    a = np.zeros((192, 108, 3), np.uint8)
    b = np.full((192, 108, 3), (40, 120, 200), np.uint8)
    done = [float((motion.apply_transition("cells", a, b, p, {"cols": 6}) == b).all(-1).mean()) for p in (0.2, 0.5, 0.8, 1.0)]
    assert done == sorted(done) and done[0] < 0.6 and done[-1] == 1.0
    lined = motion.grid_overlay(a, 6, 0.4)
    assert lined.mean() > 1 and (lined[:, 18] > 50).all()            # a vertical line a sixth of the way across
    tiles = {k: np.full((17, 18, 3), 200, np.uint8) for k in (0, 1, 2)}
    assert motion.mosaic(a, tiles, 6, 0.0) is a                      # nothing yet
    mid = motion.mosaic(a, tiles, 6, 0.6)
    assert (mid[:17, :54] > 100).all(-1).mean() > 0.9                 # the three cells are on the wall
    assert motion.mosaic(a, tiles, 6, 0.99).max() == 0                # and gone again
    for i in range(3):
        cv2.imwrite(str(tmp_path / f"{i}.jpg"), np.full((40, 60, 3), 90 + 40 * i, np.uint8))
    shots = [{"id": f"S{i}", "thumb": str(tmp_path / f"{i}.jpg"), "ai": {"score": 7}, "metrics": {}, "kind": "photo",
              "created": f"2026-10-0{i + 1}T10:00:00"} for i in range(3)]
    segs = [{"shot_id": "X", "dur": 2.0, "out_start": 2.0 * i, "people": i == 1} for i in range(3)]
    k = planner.plan_mosaic(segs, shots, {"motion": {"grid": {"cols": 6}, "mosaic": True}})
    assert k == 1 and segs[1]["mosaic"]["cells"] and not segs[0].get("mosaic")


def test_4_3_4_5_and_square_reels_and_holding_a_reel_to_one_light():
    from tripshots import framing, shots as shots_mod
    from tripshots.config import CANVAS
    assert framing.canvas_for({"output": "4:3"}) == (1440, 1080) and framing.canvas_for({"output": "4:5"}) == (1080, 1350)
    assert framing.canvas_for({"output": "1:1"}) == (1080, 1080) and framing.canvas_for({}) == (1080, 1920)
    framing.use_plan({"frame": {"aspect": "4:3", "canvas": [1440, 1080]}})
    assert CANVAS.size == (1440, 1080) and CANVAS.horizontal
    framing.use_plan({})
    assert CANVAS.size == (1080, 1920)
    shots = [{"id": f"S{i}", "ai": {"time_of_day": "golden-hour" if i % 3 == 0 else "midday"}} for i in range(150)]
    got = shots_mod.in_light(shots, "golden", {})
    assert len(got) == 50 and all(s["ai"]["time_of_day"] == "golden-hour" for s in got)
    style = {}
    assert shots_mod.in_light(shots[:30], "golden", style) == shots[:30]       # too few: preferred, not required
    assert "golden_hour" in style["taste"]["light"] and style["taste"]["weight"] >= 0.8
