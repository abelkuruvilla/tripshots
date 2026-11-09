"""Motion text pages, the leak transition, quality checks, director's notes and companion skills."""
import json

import numpy as np
from conftest import ff, needs_ffmpeg

from tripshots import companions, critic, hfx, qa
from tripshots.motion import apply_transition
from tripshots.typo import PRESETS, build_hook, build_location, legible


def _bg():
    return np.full((1920, 1080, 3), 90, np.uint8)


def test_layout_is_kept_and_every_motion_builds_a_page():
    el = build_hook("Golden hour on the coast", 0, 2.4, legible("hook", dict(PRESETS["editorial"]["hook"])), _bg(), [])
    assert el.lines and all({"text", "x", "y", "font", "size"} <= set(l) for l in el.lines)
    assert " ".join(l["text"] for l in el.lines) == "Golden hour on the coast"
    for m in hfx.MOTIONS:
        page, fonts = hfx.text_page(el, m, "hook")
        assert 'window.__timelines["root"]' in page and f'MOTION = "{m}"' in page
        assert fonts == ["PlayfairDisplay-Italic.ttf"] and "cdn." not in page   # offline: local fonts and gsap
        assert f"top:{el.lines[0]['y']:.1f}px" in page                         # words land where typo.py put them
    loc = build_location("Big Sur", "California", "36.27° N", 0, 2.4, dict(PRESETS["editorial"]["location"]), _bg())
    assert [l["role"] for l in loc.lines] == ["main", "sub", "mono"]


def test_motion_choice(monkeypatch):
    monkeypatch.setitem(hfx._status, "ok", True)
    assert hfx.motion_for("hook", {"preset": "minimal"}) == "focus"
    assert hfx.motion_for("location", {"preset": "editorial"}) == "cinema"
    assert hfx.motion_for("hook", {"preset": "bold", "motion": "write"}) == "write"
    assert hfx.motion_for("hook", {"preset": "bold"}, {"motion": "off"}) is None
    assert hfx.motion_for("caption", {"preset": "bold"}) is None          # captions stay with typo.py
    monkeypatch.setitem(hfx._status, "ok", False)
    assert hfx.motion_for("hook", {"preset": "bold", "motion": "rise"}) is None   # no runtime: classic text


def test_leak_transition_is_warm_and_brightest_at_the_cut():
    a = np.full((320, 180, 3), (110, 80, 40), np.uint8)
    b = np.full((320, 180, 3), (40, 80, 60), np.uint8)
    mid, early = apply_transition("leak", a, b, 0.5), apply_transition("leak", a, b, 0.05)
    assert mid.mean() > early.mean() + 10
    assert mid[..., 2].mean() > mid[..., 0].mean()                     # BGR: more red than blue
    assert np.abs(apply_transition("leak", a, b, 0.0).astype(int) - a).mean() < 25


@needs_ffmpeg
def test_qa_finds_black_short_text_and_unsafe_titles(tmp_path):
    v = tmp_path / "r.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=4", "-f", "lavfi", "-i", "color=black:s=1080x1920:r=30:d=1",
       "-f", "lavfi", "-i", "sine=f=440:d=5", "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]", "-map", "[v]",
       "-map", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "5", v)
    texts = [{"kind": "hook", "text": "one two three four five six", "start": 0, "duration": 1.0,
              "box": [100, 300, 900, 500], "size": 96},
             {"kind": "label", "text": "Down low", "start": 2, "duration": 2, "box": [100, 1600, 600, 1700], "size": 70}]
    rep = qa.check(v, {"segments": [], "music": {"path": "x"}}, texts)
    bad = {c["check"] for c in rep["checks"] if not c["ok"]}
    assert {"black", "text_time", "text_safe"} <= bad and "format" not in bad and "length" not in bad
    assert json.loads((tmp_path / "r.qa.json").read_text())["total"] == rep["total"]
    assert (tmp_path / "r.qa.jpg").exists()


def test_director_notes_and_style_direction():
    d = critic.direction("Hold shots; one warm look.")
    assert "first second" in d and d.rstrip().endswith("Style: Hold shots; one warm look.")
    from tripshots.config import load_style
    assert load_style("cinematic")["direction"]


def test_companion_skills_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(companions, "DIRS", [tmp_path])
    (tmp_path / "hyperframes").mkdir()
    (tmp_path / "hyperframes" / "SKILL.md").write_text("---\nname: hyperframes\n---\n")
    st = {s["name"]: s for s in companions.status()}
    assert set(st) == {"hyperframes", "remotion", "one-take", "lemo-opuscar"}
    assert st["hyperframes"]["installed"] and not st["remotion"]["installed"]
    assert st["one-take"]["install"] == "npx skills add KaranO-Dev/one-take-skill"
