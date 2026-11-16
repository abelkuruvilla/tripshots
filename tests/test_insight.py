"""The extra shot details: measured on this computer (insight.py), asked of the AI once (ai.enrich_shots), and
used (quality, hooks, shot size, search)."""
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from conftest import ff, needs_ffmpeg

from tripshots import ai, insight
from tripshots import library as lib


def test_room_for_titles_and_crop_fit():
    img = np.full((640, 360, 3), (90, 140, 200), np.uint8)       # calm sky above
    rng = np.random.default_rng(0)
    img[400:] = rng.integers(0, 255, (240, 360, 3), np.uint8)     # busy rocks below
    room = insight.text_room(img)
    assert room["calmest"] in ("upper", "center") and room["lower"] > room["upper"] + 0.3
    wide = {"w": 1920, "h": 1080, "ai": {"subjects": [{"label": "a", "box": [0.45, 0.2, 0.55, 0.8]}]}}
    spread = {"w": 1920, "h": 1080, "ai": {"subjects": [{"label": "a", "box": [0.1, 0.2, 0.3, 0.8]},
                                                         {"label": "b", "box": [0.7, 0.2, 0.9, 0.8]}]}}
    assert insight.fit(wide) == {"9:16": True, "4:5": True, "1:1": True}
    assert insight.fit(spread)["9:16"] is False and insight.fit({"w": 1080, "h": 1920, "ai": {}})["9:16"] is True


def test_words_drawn_on_the_picture_are_found():
    from tripshots.reftext import detector
    if detector() is None:
        pytest.skip("no text detector")
    img = np.full((640, 360, 3), (60, 120, 90), np.uint8)
    clean = insight.ocr(img)
    cv2.putText(img, "DAY 3 ROAD TRIP", (20, 560), cv2.FONT_HERSHEY_DUPLEX, 1.1, (255, 255, 255), 3)
    cv2.putText(img, "follow for more", (40, 600), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 2)
    drawn = insight.ocr(img)
    assert clean["burned_in"] == 0 and drawn["lines"] >= 1 and drawn["burned_in"] >= 0.5


@needs_ffmpeg
def test_motion_at_the_start_loops_and_sound(tmp_path):
    moving = tmp_path / "moving.mp4"
    still = tmp_path / "still.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=330:d=2", "-shortest",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", moving)
    ff("-f", "lavfi", "-i", "color=c=0x406080:s=320x180:r=30:d=2", "-f", "lavfi", "-i", "anoisesrc=d=2:c=pink:a=0.3",
       "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", still)
    mv = {"kind": "video", "src": str(moving), "t0": 0.0, "t1": 2.0}
    st = {"kind": "video", "src": str(still), "t0": 0.0, "t1": 2.0}
    assert insight.open_motion(mv) > insight.open_motion(st) and insight.open_motion(st) < 0.05
    assert insight.loop_match(st) > 0.95
    tone, noise = insight.audio(mv), insight.audio(st)
    assert tone["music"] > 0.5 and noise["music"] < 0.2 and noise["speech"] < 0.2
    if shutil.which("say"):   # macOS: a spoken sentence
        aiff = tmp_path / "s.aiff"
        import subprocess
        subprocess.run(["say", "-o", str(aiff), "We drove up the coast and stopped at every viewpoint we could find "
                        "before the fog came back in."], check=True)
        talk = tmp_path / "talk.mp4"
        ff("-i", aiff, "-f", "lavfi", "-i", "color=black:s=64x64:d=6", "-shortest", "-c:v", "libx264", "-c:a", "aac", talk)
        sp = insight.audio({"kind": "video", "src": str(talk), "t0": 0, "t1": 5})
        assert sp["speech"] > 0.5 and sp["music"] < 0.3


def _shot(tmp_path, sid="S001", kind="photo"):
    thumb = tmp_path / f"{sid}.jpg"
    cv2.imwrite(str(thumb), np.full((270, 480, 3), 120, np.uint8))
    return {"id": sid, "sig": f"sig{sid}", "t0": 0.0, "t1": 0.0, "kind": kind, "w": 1920, "h": 1080,
            "src": str(thumb), "thumb": str(thumb), "dur": 0, "metrics": {"bright": 0.5}, "ai": {"score": 7}}


def test_measured_once_and_kept(tmp_path, monkeypatch):
    calls = []
    real = insight.measure
    monkeypatch.setattr(insight, "measure", lambda s, deep=True: calls.append(s["id"]) or real(s, deep))
    shots = [_shot(tmp_path, f"S00{i}") for i in range(3)]
    assert insight.attach(shots, quiet=True) == 3 and all("text_room" in s["insight"] for s in shots)
    again = [_shot(tmp_path, f"S00{i}") for i in range(3)]
    assert insight.attach(again, quiet=True) == 0 and len(calls) == 3 and again[0]["insight"]["fit"]


class FakeAI(ai.Backend):
    name = "fake"

    def __init__(self):
        self.calls = 0

    def ask(self, prompt, images=None, max_tokens=4000):
        import re
        self.calls += 1
        ids = re.findall(r"^(S\d+):", prompt, re.M)
        return json.dumps([{"id": i, "vibes": {"epic": 0.9, "made-up": 1, "serene": 0.3}, "shot_size": "detail",
                            "angle": "aerial", "face": {"looking": True, "eyes_open": False}, "first_frame": 9}
                           for i in ids])


def test_details_are_asked_once_merged_and_used(tmp_path, monkeypatch):
    import tripshots.text as text
    monkeypatch.setattr(text, "contact_sheets", lambda shots, d, **k: [(Path("sheet.jpg"), [s["id"] for s in shots])])
    s = _shot(tmp_path, "S010")
    lib.put_scores({lib.shot_key(s): {"v": 2, "score": 7, "caption": "a lake"}}, "fake")
    fake = FakeAI()
    assert ai.enrich_shots([s], fake, tmp_path) == 1 and fake.calls == 1
    assert s["ai"]["vibes"] == {"epic": 0.9, "serene": 0.3} and s["ai"]["shot_size"] == "detail"
    stored = lib.get_scores([lib.shot_key(s)])[lib.shot_key(s)]
    assert stored["caption"] == "a lake" and stored["x"] == ai.ENRICH_VERSION and stored["angle"] == "aerial"
    fresh = _shot(tmp_path, "S010")
    assert ai.enrich_shots([fresh], fake, tmp_path) == 0 and fake.calls == 1 and fresh["ai"]["angle"] == "aerial"
    # used: a detail shot is "close"; eyes shut while looking at the camera costs; words drawn on the picture cost more
    from tripshots import story
    from tripshots.planner import _quality
    assert story.size(fresh) == "close" and _quality(fresh) == 6.0
    fresh["insight"] = {"ocr": {"burned_in": 0.9}}
    assert _quality(fresh) < 4


def test_an_opening_that_moves_comes_first():
    from tripshots.planner import opening_bonus
    a = {"kind": "video", "ai": {"first_frame": 9}, "insight": {"open_motion": 0.4}}
    b = {"kind": "video", "ai": {"first_frame": 4}, "insight": {"open_motion": 0.0}}
    assert opening_bonus(a) > opening_bonus(b) + 1


def test_finding_footage_by_what_the_ai_saw(tmp_path, monkeypatch):
    from tripshots import catalog
    recs = [{"path": "/f/IMG_1.jpg", "sig": "aaa", "kind": "photo", "created": "2026-01-01T10:00:00"},
            {"path": "/f/IMG_2.jpg", "sig": "bbb", "kind": "photo", "created": "2026-01-01T11:00:00"}]
    monkeypatch.setattr(catalog, "records", lambda *a, **k: [dict(r) for r in recs])
    monkeypatch.setattr(catalog, "SEL_DIR", tmp_path / "sel")
    lib.put_scores({"aaa@0.000": {"caption": "A bison grazing in a meadow", "tags": ["bison", "meadow"]},
                    "bbb@0.000": {"caption": "A lake at dawn", "tags": ["lake"]}}, "fake")
    res = catalog.find(folders=["/f"], text="bisons")
    assert res["count"] == 1
