"""Flat log footage made normal (camlog.py): the makers' curves, the LUT, detection and the plan edit."""
import json

import numpy as np
import pytest
from conftest import ff, needs_ffmpeg

from tripshots import camlog

# 18 % grey as each camera records it (from the makers' documents)
GREY = {"slog3": 420 / 1023, "vlog": 0.4233, "flog": 0.4600, "flog2": 0.3910, "clog3": 0.3433,
        "apple_log": 0.4883, "dlog": 0.4040}


@pytest.mark.parametrize("prof", sorted(camlog.PROFILES))
def test_each_cameras_grey_lands_on_a_normal_mid_grey(prof):
    lin = float(camlog.PROFILES[prof][1](np.array(GREY[prof])))
    assert lin == pytest.approx(0.18, abs=0.02)
    out = camlog.convert(np.full((1, 3), GREY[prof]), prof)[0]
    assert 0.36 < out.mean() < 0.47 and np.ptp(out) < 0.02        # neutral stays neutral
    ramp = camlog.convert(np.repeat(np.linspace(0, 1, 64)[:, None], 3, 1), prof)[:, 1]
    assert np.all(np.diff(ramp) >= -1e-6) and ramp[-1] > 0.9         # brighter stays brighter, whites reach white


def test_the_lut_file(tmp_path, monkeypatch):
    monkeypatch.setattr(camlog, "CACHE", tmp_path)
    f = camlog.cube("dlog")
    lines = f.read_text().splitlines()
    assert lines[1] == "LUT_3D_SIZE 33" and len(lines) == 2 + 33 ** 3
    assert camlog.chain({"log": "dlog"}) == [f"lut3d=file='{f}'"] and camlog.chain({"log": "nope"}) == []


def test_only_a_log_camera_with_flat_pictures_is_converted(tmp_path, monkeypatch):
    import cv2
    flat = np.full((90, 160, 3), 110, np.uint8)
    flat[:, :80] = 150
    vivid = np.zeros((90, 160, 3), np.uint8)
    vivid[:, :80] = (230, 60, 30)
    assert camlog.looks_flat(flat) and not camlog.looks_flat(vivid)
    for name, img in (("flat", flat), ("vivid", vivid)):
        cv2.imwrite(str(tmp_path / f"{name}.jpg"), img)
    makes = {"/a.mov": "dji", "/b.mov": "", "/c.mov": "apple"}
    monkeypatch.setattr(camlog, "camera", lambda src: makes[src])
    shot = lambda src, t: {"kind": "video", "src": src, "thumb": str(tmp_path / f"{t}.jpg")}
    assert camlog.detect(shot("/a.mov", "flat")) == "dlog"
    assert camlog.detect(shot("/b.mov", "flat")) is None            # an unknown camera: never guessed
    assert camlog.detect(shot("/c.mov", "vivid")) is None           # an iPhone clip that isn't log
    assert camlog.detect({**shot("/c.mov", "flat"), "hdr": True}) is None
    by_id = {"V1": shot("/a.mov", "flat"), "V2": shot("/c.mov", "vivid")}
    plan = {"segments": [{"shot_id": "V1", "kind": "video"}, {"shot_id": "V2", "kind": "video"},
                         {"shot_id": "V1", "kind": "video", "log": None}]}
    found = camlog.mark(plan, by_id)
    assert plan["segments"][0]["log"] == "dlog" and "log" not in plan["segments"][1]
    assert plan["segments"][2]["log"] is None and len(found) == 1     # set by hand to "as filmed": stays


def test_the_log_edit(tmp_path, monkeypatch):
    import tripshots.text as T
    from tripshots import planedit
    from tripshots.util import ReelError
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    (tmp_path / "shots_scored.json").write_text(json.dumps([{"id": "V0", "kind": "video", "src": "/x.mov", "t0": 0,
                                                              "t1": 9, "w": 1920, "h": 1080, "ai": {}, "metrics": {}}]))
    plan = {"style": "beat-montage", "work": str(tmp_path), "duration": 2, "color": {}, "overlays": [], "tempo": 120,
            "segments": [{"shot_id": "V0", "kind": "video", "src": "/x.mov", "in": 1.0, "dur": 2.0, "out_start": 0}]}
    p = tmp_path / "l.plan.json"
    p.write_text(json.dumps(plan))
    planedit.apply(p, [{"op": "log", "segment": 1, "profile": "slog3"}])
    assert json.loads(p.read_text())["segments"][0]["log"] == "slog3"
    planedit.apply(p, [{"op": "log", "segment": "all", "profile": None}])
    assert json.loads(p.read_text())["segments"][0]["log"] is None
    with pytest.raises(ReelError):
        planedit.apply(p, [{"op": "log", "segment": 1, "profile": "hlog"}])


@needs_ffmpeg
def test_a_flat_clip_renders_with_contrast(tmp_path):
    import cv2
    from tripshots.render import render_video_seg
    src = tmp_path / "flat.mp4"
    ff("-f", "lavfi", "-i", "color=c=0x606060:s=320x180:r=30:d=1,drawbox=x=0:y=0:w=160:h=180:color=0x9a9a9a:t=fill",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", src)
    e = {"kind": "video", "src": str(src), "in": 0.0, "speed": 1.0, "layout": "fill", "src_w": 320, "src_h": 180}

    def spread(seg, name):
        out = tmp_path / name
        render_video_seg(seg, 0.5, {}, out, size=(320, 180))
        ok, fr = cv2.VideoCapture(str(out)).read()
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        return float(g[:, :140].mean()) - float(g[:, 180:].mean())
    assert spread({**e, "log": "slog3"}, "l.mp4") > spread(e, "n.mp4") * 1.3
