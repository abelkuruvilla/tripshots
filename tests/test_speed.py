"""Speed effects: ramp curves, how much footage they use, the planner's choices, plan edits, and a real render."""
import json
import subprocess

import pytest

from tripshots import planedit, planner, retime
from tripshots.config import load_style

from test_planner import _shots


@pytest.mark.parametrize("kind", retime.KINDS)
def test_curves_are_smooth_and_bounded(kind):
    k = retime.keys(kind)
    sp = [retime.speed_at(k, i / 200) for i in range(201)]
    assert all(retime.SPEED_MIN * 0.99 <= s <= retime.SPEED_MAX for s in sp)
    assert max(abs(a - b) for a, b in zip(sp, sp[1:])) < 0.2   # eased: no jumps between frames


def test_hit_lands_on_the_beat():
    seg = {"ramp": "slam", "ramp_hit": 1.2, "dur": 2.0, "out_start": 10.0}
    assert retime.hit_time(seg) == pytest.approx(11.2)
    k = retime.seg_keys(seg)
    assert retime.speed_at(k, 0.3) == pytest.approx(1.0)      # real time before it
    assert retime.speed_at(k, 0.62) < 0.45                    # slow motion right after it
    # with transition overlap around the shot the hit stays on the same moment
    k2 = retime.seg_keys(seg, length=2.2, lead=0.1)
    assert retime.speed_at(k2, (0.1 + 1.25) / 2.2) < 0.45


def test_source_seconds():
    assert retime.source_seconds({"dur": 2.0, "speed": 0.5}) == pytest.approx(1.0)
    assert retime.source_seconds({"dur": 2.0, "speed": 2}) == pytest.approx(4.0)
    assert retime.source_seconds({"dur": 2.0, "ramp": "rush"}) > 2.5       # speeds up: uses more footage
    assert retime.source_seconds({"dur": 2.0, "ramp": "slam"}) < 1.5       # mostly slow motion: uses less
    pts = {"dur": 2.0, "ramp": "custom", "ramp_points": [[0, 1], [0.5, 0.25], [1, 0.25]]}
    assert retime.source_seconds(pts) < 1.6 and retime.hit_time({**pts, "out_start": 0}) is not None


def test_needs_retime():
    assert retime.needs_retime({"ramp": "velocity"}, 30)
    assert retime.needs_retime({"speed": 0.5}, 30)                  # made-up in-between frames
    assert not retime.needs_retime({"speed": 0.5}, 60)              # real slow motion from 60 fps
    assert not retime.needs_retime({"speed": 0.5, "smooth": "off"}, 30)
    assert not retime.needs_retime({"speed": 2.0}, 30)              # ffmpeg + motion blur


def test_planner_speed_effects():
    style = load_style("beat-montage")
    style["velocity"]["use"] = 1.0
    style["speed"].update({"ramps": ["slam"], "fast": 0.0, "drop": "off"})
    shots = _shots()
    for s in shots:
        s["metrics"].update({"pan": 0.01, "activity": 0.03})
        s["t1"] = s["dur"] = 12.0
    plan = planner.build_plan(shots, None, style, target=12)
    ramps = [s for s in plan["segments"] if s.get("ramp")]
    assert ramps and all(s["ramp"] == "slam" for s in ramps)
    by_id = {s["id"]: s for s in shots}
    for s in ramps:  # enough footage for the whole curve
        assert s["in"] + retime.source_seconds(s) <= by_id[s["shot_id"]]["t1"] + 1e-6
    style["velocity"]["use"] = 0.0
    style["speed"]["fast"] = 1.0
    plan = planner.build_plan(shots, None, style, target=12)
    fast = [s for s in plan["segments"] if s.get("level") != "calm" and s.get("kind") == "video"]
    assert fast and all(s["speed"] >= 1.3 for s in fast)


def _video_plan(tmp_path):
    shots = [{"id": f"V{i}", "kind": "video", "src": f"/x/{i}.mp4", "w": 1920, "h": 1080, "fps": 30, "t0": 0.0,
              "t1": 3.0 if i == 2 else 10.0, "ai": {"score": 8}, "metrics": {"pan": 0.01},
              "samples": {"t": [0, 2, 4], "sharp": [1, 1, 1], "jitter": [0, 0, 0]}} for i in range(3)]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    segs = [{"shot_id": f"V{i}", "kind": "video", "src": f"/x/{i}.mp4", "in": 0.0, "speed": 1.0, "layout": "crop",
             "src_w": 1920, "src_h": 1080, "dur": 2.0, "out_start": 2.0 * i, "level": "medium", "trans_out": None}
            for i in range(3)]
    p = tmp_path / "v.plan.json"
    p.write_text(json.dumps({"style": "beat-montage", "work": str(tmp_path), "duration": 6.0, "segments": segs,
                             "overlays": [], "color": {}, "tempo": 120}))
    return p


def test_plan_edits(tmp_path, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    p = _video_plan(tmp_path)
    res = planedit.apply(p, [{"op": "ramp", "segment": 1, "ramp": "bullet", "hit": 0.8},
                             {"op": "speed", "segment": 2, "speed": 2},
                             {"op": "speed", "segment": 3, "speed": 3}])
    segs = json.loads(p.read_text())["segments"]
    assert segs[0]["ramp"] == "bullet" and segs[0]["ramp_hit"] == 0.8
    assert segs[1]["speed"] == 2 and not segs[1].get("ramp")
    assert segs[2]["speed"] == pytest.approx(1.5)                 # 3 s of footage: 1.5x is the most for 2 s
    assert "too short" in res["changes"][2]
    planedit.apply(p, [{"op": "exchange", "a": 1, "b": 2}, {"op": "ramp", "segment": 2, "ramp": None}])
    segs = json.loads(p.read_text())["segments"]
    assert segs[1]["shot_id"] == "V0" and not segs[1].get("ramp") and segs[1]["speed"] == 1.0
    with pytest.raises(Exception):
        planedit.apply(p, [{"op": "ramp", "segment": 3, "ramp": "rush"}])   # V2 is too short for a rush


def test_retimed_render(tmp_path):
    from tripshots import render
    src = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-pix_fmt",
                    "yuv420p", str(src)], check=True)
    for extra in ({"ramp": "velocity"}, {"speed": 0.5}):
        e = {"kind": "video", "src": str(src), "in": 0.2, "src_w": 640, "src_h": 360, "layout": "crop",
             "fps": 30, "dur": 1.0, "out_start": 0.0, "speed": 1.0, **extra}
        out = tmp_path / "o.mp4"
        render.render_retimed_seg(e, 1.0, {}, out)
        n = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
        assert int(n.stdout.strip()) == 30


def test_drop_rush_and_impact():
    shots = _shots(3)
    by_id = {s["id"]: s for s in shots}
    segs = [{"shot_id": f"S00{i}", "kind": "video", "dur": 1.0, "out_start": float(i), "level": "intense",
             "speed": 1.0, "in": 0.0} for i in range(3)]
    style = {"speed": {"drop": "both", "fast": 0}, "velocity": {"use": 0}}
    planner.apply_speed(segs, by_id, {"beats": [], "drops": [1.0]}, style)
    assert segs[0]["ramp"] == "rush" and segs[1]["ramp"] == "impact" and not segs[2].get("ramp")
