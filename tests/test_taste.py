"""Learned taste: shot choice by the references' light, a widescreen letterbox, a full-strength look."""
import subprocess

import numpy as np
import pytest
from PIL import Image

from tripshots import framing, planner
from tripshots.config import load_style
from tripshots.diversity import look


@pytest.fixture(autouse=True)
def _reset_frame():
    yield
    framing.set_frame("9:16")


def _img(path, sky, ground):
    im = Image.new("RGB", (640, 360), sky)
    im.paste(Image.new("RGB", (640, 200), ground), (0, 160))
    im.save(path)
    return str(path)


def test_frame_shapes():
    assert framing.band_height(framing.set_frame("16:9")) == 608
    assert framing.band_height(framing.set_frame("2.39:1")) == 452
    assert framing.set_frame("9:16") == pytest.approx(1080 / 1920)
    framing.set_frame("16:9")
    assert framing.crop_fraction(3840, 2160) == pytest.approx(1.0)          # a 16:9 clip fills the band
    assert framing.decide_layout({"w": 1080, "h": 1920}, framing.make_box(0.3, 0.3, 0.7, 0.7), "auto")[0] == "crop"


def test_taste_prefers_the_references_light(tmp_path):
    golden = _img(tmp_path / "g.jpg", (235, 170, 90), (90, 70, 30))
    blue = _img(tmp_path / "b.jpg", (80, 150, 240), (60, 120, 60))
    ref = look(np.asarray(Image.open(golden)))
    style = load_style("beat-montage")
    style["taste"] = {"look": [float(x) for x in ref], "weight": 1.0, "light": ["golden_hour"], "people": ""}
    shots = [{"id": "G", "thumb": golden, "ai": {"time_of_day": "golden hour"}, "w": 1920, "h": 1080},
             {"id": "B", "thumb": blue, "ai": {"time_of_day": "midday"}, "w": 1920, "h": 1080}]
    t = planner.taste_scores(shots, style)
    assert t["G"] > t["B"] + 2


def test_full_match_moves_further_toward_the_look():
    from tripshots.grade import build_transform
    src = {"Lq": [5, 20, 35, 55, 70, 85, 95], "chroma": 30.0, "wb_ab": [0, 0]}
    lk = {"Lq": [2, 10, 20, 32, 45, 60, 75], "chroma": 14.0, "black": 2, "white": 92, "sh_ab": [0, 0],
          "mid_ab": [3, 8], "hi_ab": [2, 10], "hue": []}
    x = np.array([[0.6, 0.6, 0.6], [0.3, 0.5, 0.8]], np.float32)
    gentle, full = build_transform(src, lk, 0.9, {})(x), build_transform(src, lk, 0.9, {"match": "full"})(x)
    assert full.mean() < gentle.mean()                       # darker, like the moody reference


def test_letterbox_video_segment(tmp_path):
    from tripshots.render import render_video_seg
    src = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=2", "-pix_fmt",
                    "yuv420p", str(src)], check=True)
    out = tmp_path / "o.mp4"
    render_video_seg({"src": str(src), "in": 0.0, "src_w": 1280, "src_h": 720, "layout": "crop", "subject_x": 0.5,
                      "_band": 608}, 1.0, {}, out)
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt",
                        "gray", "-"], capture_output=True)
    fr = np.frombuffer(p.stdout, np.uint8).reshape(1920, 1080)
    assert fr[:600].max() < 20 and fr[1300:].max() < 20 and fr[700:1200].mean() > 40   # bars and a picture
