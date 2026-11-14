"""Horizontal reels: a wide picture gets a 1920x1080 file instead of black bars in an upright one."""
import json
import subprocess

import numpy as np
import pytest
from conftest import needs_ffmpeg
from test_planner import _shots

from tripshots import framing, planner, typo
from tripshots.config import CANVAS, load_style


def test_which_reels_come_out_horizontal():
    assert framing.output_for({"aspect": "16:9"}) and framing.output_for({"aspect": "2.39:1"})
    assert not framing.output_for({"aspect": "9:16"}) and not framing.output_for(None)
    assert not framing.output_for({"aspect": "16:9", "output": "vertical"})        # asked for: bars stay
    assert framing.output_for({"aspect": "9:16", "output": "horizontal"})


def test_canvas_moves_the_layout_with_it():
    up = dict(typo.SAFE)
    assert framing.set_canvas(True) == (1920, 1080) and CANVAS.horizontal
    assert typo.SAFE["right"] > 1080 and typo.SAFE["bottom"] < 1080
    assert all(0 < a < b <= 1080 for a, b in typo.BANDS.values())
    assert typo.scaled({"size": 100, "sub_size": 40, "weight": "bold"}) == {"size": 140, "sub_size": 56,
                                                                              "weight": "bold"}
    assert framing.set_frame("2.39:1") == pytest.approx(16 / 9)       # the picture fills the frame: no bars
    assert framing.band_height() == 1080
    assert framing.crop_fraction(1920, 1080) == pytest.approx(1.0)
    framing.set_canvas(False)
    assert typo.SAFE == up and typo.scaled({"size": 100}) == {"size": 100}


def test_wide_style_plans_a_horizontal_reel():
    style = load_style("beat-montage")
    style["frame"] = {"aspect": "2.39:1"}
    plan = planner.build_plan(_shots(), None, style, target=12)
    assert plan["frame"]["canvas"] == [1920, 1080] and "band" not in plan["frame"]
    assert all(s["layout"] != "blur_fill" and not s.get("panel") for s in plan["segments"])
    framing.set_canvas(False)
    framing.use_plan(plan)
    assert CANVAS.size == (1920, 1080)
    framing.use_plan({"segments": []})
    assert CANVAS.size == (1080, 1920)


def test_vertical_on_request_keeps_the_band():
    style = load_style("beat-montage")
    style["frame"] = {"aspect": "16:9", "output": "vertical"}
    plan = planner.build_plan(_shots(), None, style, target=12)
    assert plan["frame"]["canvas"] == [1080, 1920] and plan["frame"]["band"] == 608


def test_no_bars_unless_asked_for():
    style = load_style("beat-montage")
    style["frame"] = {"aspect": "1:1"}                    # a square reference: the picture fills the upright frame
    plan = planner.build_plan(_shots(), None, style, target=12)
    assert "frame" not in plan and CANVAS.size == (1080, 1920)
    style = load_style("beat-montage")
    style["frame"] = {"aspect": "4:3"}                    # a wide one: a horizontal file
    assert planner.build_plan(_shots(), None, style, target=12)["frame"]["canvas"] == [1920, 1080]


def test_landscape_footage_that_cannot_be_cropped_goes_horizontal():
    by_id = {s["id"]: s for s in _shots(6)}
    segs = [{"shot_id": k, "layout": "blur_fill"} for k in list(by_id)[:4]] + [{"shot_id": "S004", "layout": "crop"}]
    assert framing.better_horizontal({"segments": segs}, by_id, {"aspect": "9:16", "output": "auto"})
    assert not framing.better_horizontal({"segments": segs}, by_id, {"aspect": "9:16", "output": "vertical"})
    for s in segs[:3]:
        s["layout"] = "crop"                      # most shots crop well: an upright reel is fine
    assert not framing.better_horizontal({"segments": segs}, by_id, {"aspect": "9:16"})
    by_id["S004"]["w"], by_id["S004"]["h"] = 1080, 1920
    segs = [{**s, "layout": "blur_fill"} for s in segs]
    assert not framing.better_horizontal({"segments": segs}, by_id, {})          # one upright clip: stay upright


def _gray(path, w, h):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt",
                        "gray", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(h, w)


@needs_ffmpeg
def test_horizontal_segments_fill_the_frame(tmp_path):
    from tripshots.render import render_video_seg
    framing.set_canvas(True)
    framing.set_frame("16:9")
    src = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=2", "-pix_fmt",
                    "yuv420p", str(src)], check=True)
    out = tmp_path / "o.mp4"
    render_video_seg({"src": str(src), "in": 0.0, "src_w": 1280, "src_h": 720, "layout": "crop", "subject_x": 0.5},
                     1.0, {}, out)
    fr = _gray(out, 1920, 1080)
    assert fr[:40].mean() > 25 and fr[-40:].mean() > 25 and fr[:, :40].mean() > 25      # picture to every edge
    # an upright clip in the wide frame: the window sits on the subject, not on the middle
    tall = tmp_path / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=720x1280:r=30:d=2", "-vf",
                    "drawbox=x=0:y=0:w=720:h=320:color=white:t=fill", "-pix_fmt", "yuv420p", str(tall)], check=True)
    seg = {"src": str(tall), "in": 0.0, "src_w": 720, "src_h": 1280, "layout": "crop", "subject_x": 0.5}
    render_video_seg({**seg, "subject": {"cx": 0.5, "cy": 0.1}}, 1.0, {}, out)
    top = _gray(out, 1920, 1080).mean()
    render_video_seg({**seg, "subject": {"cx": 0.5, "cy": 0.9}}, 1.0, {}, tmp_path / "o2.mp4")
    assert top > 100 and _gray(tmp_path / "o2.mp4", 1920, 1080).mean() < 20


@needs_ffmpeg
@pytest.mark.slow
def test_make_renders_a_horizontal_reel(footage, song, tmp_path):
    from tripshots.pipeline import make
    out = tmp_path / "wide.mp4"
    r = make([footage], str(song), "beat-montage", out, 8.0, "none", "Day one", None, True, False,
             source_opts={"watch": "off"}, sound={"sfx": "off", "ambience": "off"}, route_map="off",
             extras={"orientation": "horizontal"})
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                     capture_output=True, text=True).stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1920, 1080)
    plan = json.loads(out.with_suffix(".plan.json").read_text())
    assert plan["frame"]["canvas"] == [1920, 1080]
    qa = json.loads(out.with_suffix(".qa.json").read_text())
    bad = [c["check"] for c in qa["checks"] if not c["ok"] and c["check"] in ("format", "text_safe", "text_size")]
    assert not bad, bad
    boxes = json.loads(out.with_suffix(".text.json").read_text())
    assert boxes and all(b["box"][2] <= 1920 and b["box"][3] <= 1080 for b in boxes)
    fr = _gray(out, 1920, 1080)
    assert fr[:30].mean() > 8 or fr[-30:].mean() > 8          # no black bars
    assert CANVAS.size == (1920, 1080)


def test_a_wide_view_in_an_upright_reel_is_never_a_strip():
    from tripshots.planner import _shot_fields
    shot = {"id": "S1", "kind": "video", "src": "/x.mp4", "t0": 0, "t1": 10, "w": 3840, "h": 2160, "fps": 30,
            "metrics": {"pan": 0.0, "activity": 0.0}, "samples": {"t": [0, 5], "sharp": [1, 1], "jitter": [0, 0]},
            "ai": {"subject_box": [0.0, 0.2, 1.0, 0.9],
                   "subjects": [{"label": "waves on a beach", "box": [0.0, 0.2, 1.0, 0.9]},
                                {"label": "person walking", "box": [0.62, 0.5, 0.68, 0.62]}]}}
    style = load_style("beat-montage")
    e, _ = _shot_fields(shot, 1.5, "calm", style, 0)
    assert e["layout"] == "crop" and abs(e["subject_x"] - 0.65) < 1e-6 and "wide" not in e   # held on the person
    shot["ai"]["subjects"].pop()
    e, _ = _shot_fields(shot, 1.5, "calm", style, 0)
    assert e["layout"] == "pan" and e["wide"] and (e["pan_from"], e["pan_to"]) == (0.0, 1.0)  # a drift, no bars
    by_id = {s["id"]: s for s in _shots(6)}
    segs = [{**e, "shot_id": k} for k in list(by_id)[:4]] + [{"shot_id": "S004", "layout": "crop"}]
    assert framing.better_horizontal({"segments": segs}, by_id, {"aspect": "9:16"})     # mostly such shots: wide
    style["layout"]["landscape"] = "blur_fill"                                          # asked for: kept
    assert _shot_fields(shot, 1.5, "calm", style, 0)[0]["layout"] == "blur_fill"
