from tripshots import planner
from tripshots.config import load_style


def _shots(n=8):
    out = []
    for i in range(n):
        out.append({"id": f"S{i:03d}", "kind": "video", "src": f"/x/clip{i}.mp4", "sig": f"sig{i}", "t0": 0.0,
                    "t1": 6.0, "dur": 6.0, "w": 1920, "h": 1080, "fps": 30, "name": f"clip{i}.mp4",
                    "created": f"2026-05-01T12:{i:02d}:00", "ai": {"score": 7 - i * 0.1, "tags": ["beach"]},
                    "metrics": {"sharp": 100, "motion": 0.1}, "samples": {"t": [0, 1, 2, 3, 4, 5],
                    "sharp": [100] * 6, "jitter": [0.01] * 6}})
    return out


def test_plan_tiles_timeline_on_frames():
    style = load_style("beat-montage")
    plan = planner.build_plan(_shots(), None, style, target=12)
    t = 0.0
    for s in plan["segments"]:
        assert abs(s["out_start"] - t) < 1e-3
        assert abs(s["dur"] * 30 - round(s["dur"] * 30)) < 1e-3  # whole frames at 30 fps
        t += s["dur"]
    assert abs(t - plan["duration"]) < 1e-3


def test_incam_cut_lands_mid_swing():
    shots = _shots(4)
    shots[0]["incam"] = [{"start": 4.0, "end": 4.3, "type": "whip_pan", "src": "local"}]
    by_id = {s["id"]: s for s in shots}
    segs = [{"shot_id": "S000", "kind": "video", "dur": 2.0, "speed": 1, "out_start": 0.0, "trans_out": "zoom_in"},
            {"shot_id": "S001", "kind": "video", "dur": 2.0, "speed": 1, "out_start": 2.0, "in": 0.5}]
    assert planner.use_incam(segs, by_id, {"transitions": {}}) == 1
    assert segs[0]["trans_out"] is None
    assert abs(segs[0]["in"] + segs[0]["dur"] - 4.15) < 1e-6  # the cut is the middle of the swing
