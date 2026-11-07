"""One real reel, no AI: ingest -> shots -> plan -> render -> exports."""
import json
import subprocess
from pathlib import Path

import pytest
from conftest import needs_ffmpeg

from tripshots.pipeline import make


@needs_ffmpeg
@pytest.mark.slow
def test_make_renders_a_vertical_reel(footage, song, tmp_path):
    out = tmp_path / "trip.mp4"
    r = make([footage], str(song), "beat-montage", out, 8.0, "none", None, None, True, False,
             source_opts={"watch": "off"}, sound={"sfx": "off", "ambience": "off"}, route_map="off")
    assert out.exists() and r["edl"].endswith(".edl")
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                     capture_output=True, text=True).stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    plan = json.loads(out.with_suffix(".plan.json").read_text())
    assert abs(sum(s["dur"] for s in plan["segments"]) - plan["duration"]) < 1e-3


@needs_ffmpeg
@pytest.mark.slow
def test_edits_package(footage, song, tmp_path):
    from tripshots import edits
    out = tmp_path / "trip.mp4"
    r = make([footage], str(song), "beat-montage", out, 8.0, "none", "Day one", None, True, True,
             source_opts={"watch": "off"}, sound={"sfx": "off", "ambience": "off"}, route_map="off")
    res = edits.package(Path(r["plan"]), stage=False)
    m = json.loads(Path(res["manifest"]).read_text())
    plan = json.loads(Path(r["plan"]).read_text())
    assert len(m["clips"]) == len(plan["segments"])
    assert [t["text"] for t in m["texts"] if t["type"] == "hook"] == ["Day one"]
    assert m["music"]["song_start"] == round(plan["music"]["start"], 3)
    frames = [int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
                                  "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0",
                                  str(Path(res["package"]) / c["file"])], capture_output=True, text=True).stdout)
              for c in m["clips"]]
    assert sum(frames) == round(plan["duration"] * 30)      # clips butt together frame-exactly
