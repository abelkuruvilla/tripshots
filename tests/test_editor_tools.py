"""Editor tools after Instagram Edits: trim from either end, hold a frame, play a clip backwards, and the quick
motion preview (render --draft)."""
import json

import numpy as np
import pytest
from conftest import ff, needs_ffmpeg

from tripshots import planedit
from tripshots.util import ReelError


def _video_plan(tmp_path, n=3):
    shots = [{"id": f"V{i}", "kind": "video", "src": f"/x/{i}.mp4", "w": 1920, "h": 1080, "t0": 0.0, "t1": 10.0,
              "ai": {"score": 7, "note": f"clip {i}"}, "metrics": {}} for i in range(n)]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    segs, t = [], 0.0
    for i in range(n):
        segs.append({"shot_id": f"V{i}", "kind": "video", "src": f"/x/{i}.mp4", "in": 2.0, "speed": 1.0,
                     "layout": "crop", "dur": 2.0, "out_start": t, "level": "mid", "trans_out": None})
        t += 2.0
    plan = {"style": "beat-montage", "work": str(tmp_path), "duration": t, "segments": segs, "color": {},
            "overlays": [{"type": "text", "text": "Later", "start": 4.5, "duration": 1.0}], "tempo": 120}
    p = tmp_path / "v.plan.json"
    p.write_text(json.dumps(plan))
    return p


@pytest.fixture
def quiet(monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)


def _segs(p):
    return json.loads(p.read_text())["segments"]


def test_trimming_the_start_keeps_the_end_of_the_clip_and_moves_later_text(tmp_path, quiet):
    p = _video_plan(tmp_path)
    planedit.apply(p, [{"op": "trim", "segment": 2, "side": "left", "by": 0.5}])
    s = _segs(p)[1]
    assert s["dur"] == 1.5 and s["in"] == 2.5          # what played at the slot's end still does
    assert s["in"] + s["dur"] == 4.0
    plan = json.loads(p.read_text())
    assert plan["duration"] == 5.5 and plan["overlays"][0]["start"] == 4.0
    # lengthening from the start can't reach before the clip begins
    planedit.apply(p, [{"op": "trim", "segment": 2, "side": "left", "by": -9}])
    s = _segs(p)[1]
    assert s["in"] == 0.0 and abs(s["dur"] - 4.0) < 1e-6
    planedit.apply(p, [{"op": "trim", "segment": 1, "side": "right", "by": 0.5}])
    assert _segs(p)[0]["dur"] == 1.5 and _segs(p)[0]["in"] == 2.0


def test_a_held_frame_is_cut_in_at_the_playhead(tmp_path, quiet):
    p = _video_plan(tmp_path)
    planedit.apply(p, [{"op": "freeze", "segment": 2, "at": 0.8, "dur": 1.0}])
    segs = _segs(p)
    assert len(segs) == 5
    a, f, b = segs[1], segs[2], segs[3]
    assert a["dur"] == pytest.approx(0.8) and f["dur"] == 1.0 and b["dur"] == pytest.approx(1.2)
    assert f["freeze"] and f["in"] == pytest.approx(2.8) and b["in"] == pytest.approx(2.8)
    assert json.loads(p.read_text())["overlays"][0]["start"] == pytest.approx(5.5)
    # moving or lengthening the hold never changes which frame it holds
    planedit.apply(p, [{"op": "move", "from": 3, "to": 1}, {"op": "duration", "segment": 1, "dur": 2.5}])
    assert _segs(p)[0]["freeze"] and _segs(p)[0]["in"] == pytest.approx(2.8)


def test_backwards_clips_split_and_freeze_on_the_frame_you_see(tmp_path, quiet):
    p = _video_plan(tmp_path)
    planedit.apply(p, [{"op": "reverse", "segment": 1}])
    assert _segs(p)[0]["reverse"]
    planedit.apply(p, [{"op": "split", "segment": 1, "at": 0.5}])
    a, b = _segs(p)[:2]
    # backwards, the window 2.0-4.0 plays 4.0 -> 2.0: the first piece shows 4.0-3.5, the second 3.5-2.0
    assert a["in"] == pytest.approx(3.5) and a["dur"] == pytest.approx(0.5)
    assert b["in"] == pytest.approx(2.0) and b["dur"] == pytest.approx(1.5)
    planedit.apply(p, [{"op": "freeze", "segment": 2, "at": 0.5, "dur": 0.5}])
    assert _segs(p)[2]["freeze"] and _segs(p)[2]["in"] == pytest.approx(3.0)   # 3.5 - 0.5
    planedit.apply(p, [{"op": "reverse", "segment": 1, "on": False}])
    assert not _segs(p)[0].get("reverse")
    with pytest.raises(ReelError):
        planedit.apply(p, [{"op": "reverse", "segment": 3}])     # a held frame has no direction


@needs_ffmpeg
def test_held_and_backwards_clips_render(tmp_path):
    from tripshots.render import render_video_seg
    src = tmp_path / "count.mp4"
    # brightness rises over the clip, so forwards gets lighter and backwards darker
    ff("-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=3,geq=lum='min(255,N*3)':cb=128:cr=128",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", src)
    base = {"kind": "video", "src": str(src), "in": 0.5, "speed": 1.0, "layout": "fill", "src_w": 320, "src_h": 180}

    def lum(e, name):
        out = tmp_path / name
        render_video_seg(e, 1.0, {}, out, size=(180, 320))
        import cv2
        cap = cv2.VideoCapture(str(out))
        vals = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            vals.append(float(fr.mean()))
        return np.array(vals)

    fwd, back, held = lum(base, "f.mp4"), lum({**base, "reverse": True}, "r.mp4"), lum({**base, "freeze": True}, "z.mp4")
    assert len(fwd) == len(back) == len(held) == 30
    assert fwd[-1] > fwd[0] + 20 and back[0] > back[-1] + 20
    assert abs(back[0] - fwd[-1]) < 12 and np.ptp(held) < 3


def test_the_draft_leaves_out_sound_motion_text_and_checks():
    from tripshots.pipeline import draft_plan
    plan = draft_plan({"segments": [], "sound": {"sfx": "on", "level_db": 2}, "frame": {}})
    assert plan["sound"] == {"sfx": "off", "ambience": "off", "level_db": 2}
    assert plan["text"]["motion"] == "off" and plan["qa"] == "off" and plan["frame"] == {}
