import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest
from conftest import clip, ff, needs_ffmpeg

from tripshots import ai, analysis


def _scene(seed=0, w=640, h=480):
    """A photo-like picture: shapes with hard edges and texture."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 90, np.uint8)
    for _ in range(25):
        c = tuple(int(x) for x in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(20, 200)), y + int(rng.integers(20, 200))), c, -1)
    return img


def test_sharpness_follows_focus_not_content():
    sharp = _scene()
    t_sharp = analysis.technical(sharp)
    t_blur = analysis.technical(cv2.GaussianBlur(sharp, (0, 0), 3))
    assert t_sharp["sharpness_label"] == "sharp" and t_blur["sharpness_label"] == "blurry"
    assert t_sharp["sharpness"] > 0.8 > 0.3 > t_blur["sharpness"]
    # the same picture with much less contrast is still in focus
    low = (sharp.astype(np.float32) * 0.3 + 120).astype(np.uint8)
    assert analysis.technical(low)["sharpness_label"] == "sharp"


def test_exposure_colour_and_palette():
    dark = analysis.technical((_scene() * 0.15).astype(np.uint8))
    assert dark["exposure_label"] == "dark"
    red_blue = np.zeros((300, 400, 3), np.uint8)
    red_blue[:, :300] = (220, 30, 30)
    red_blue[:, 300:] = (20, 40, 200)
    t = analysis.technical(red_blue)
    top = t["palette"][0]
    assert top["share"] > 0.6 and int(top["hex"][1:3], 16) > 180      # mostly red
    assert any(int(p["hex"][5:7], 16) > 150 for p in t["palette"][1:])  # and some blue
    assert t["temperature_label"] in ("warm", "neutral")


def test_near_duplicates():
    a = _scene(1)
    again = cv2.imdecode(cv2.imencode(".jpg", cv2.resize(a, (500, 375)), [cv2.IMWRITE_JPEG_QUALITY, 60])[1], 1)
    other = _scene(2)
    h = {k: analysis.technical(v)["dhash"] for k, v in (("a", a), ("again", again), ("other", other))}
    groups = analysis.similar_groups(list(h.items()))
    assert groups.get("a") == groups.get("again") and "other" not in groups


def test_ai_fields_are_normalised():
    v = ai._norm_score({"id": "S001", "caption": "Lake", "tags": ["Lake", "lake", " Mountain "], "scene": "Moon base",
                        "people": {"count": "3"}, "aesthetic": 14, "issues": ["blurry", "made-up"],
                        "subjects": [{"label": "Peak", "box": [0.2, 0.1, 0.6, 0.5]}], "landmark": "null"})
    assert v["tags"] == ["lake", "mountain"] and v["scene"] == "other" and v["people"]["count"] == 3
    assert v["aesthetic"] == 10 and v["issues"] == ["blurry"] and v["landmark"] is None
    assert v["subject_box"] == [0.2, 0.1, 0.6, 0.5] and abs(v["subject_x"] - 0.4) < 1e-9 and v["v"] == ai.AI_VERSION


class FakeAI(ai.Backend):
    name = "fake"

    def __init__(self):
        self.calls = 0

    def ask(self, prompt, images=None, max_tokens=4000):
        self.calls += 1
        ids = re.findall(r"^(S\d+):", prompt, re.M)
        return json.dumps([{"id": i, "caption": f"shot {i}", "description": "d", "tags": ["test"], "scene": "other",
                            "aesthetic": 6, "score": 6} for i in ids])


@needs_ffmpeg
def test_analyze_writes_valid_records(tmp_path, monkeypatch):
    jsonschema = pytest.importorskip("jsonschema")
    foot = tmp_path / "foot"
    foot.mkdir()
    clip(foot / "VID_20250712_120000.mp4", "testsrc2", dur=3)
    ff("-f", "lavfi", "-i", "smptehdbars=s=1600x1200", "-frames:v", "1", foot / "IMG_20250712_130000.jpg")
    fake = FakeAI()
    monkeypatch.setattr(ai, "get_backend", lambda name=None: fake)
    res = analysis.analyze([foot], faces=False, places=False, out_dir=tmp_path / "out")
    recs = list(analysis.load(res["output"]))
    schema = json.loads(analysis.SCHEMA_FILE.read_text())
    for r in recs:
        jsonschema.validate(r, schema)
    assert {r["kind"] for r in recs} == {"photo", "video"} and res["described_by_ai"] == res["shots"]
    photo = next(r for r in recs if r["kind"] == "photo")
    assert photo["captured"]["day"] == "2025-07-12" and photo["media"]["orientation"] == "landscape"
    assert photo["shots"][0]["ai"]["caption"].startswith("shot ")
    summary = json.loads((Path(res["output"]) / "summary.json").read_text())
    assert summary["schema"] == analysis.SCHEMA_ID and summary["files"] == 2
    # second run: nothing new is sent to the AI; --cached does no new work at all
    n = fake.calls
    analysis.analyze([foot], faces=False, places=False, out_dir=tmp_path / "out")
    assert fake.calls == n
    res2 = analysis.analyze([foot], faces=False, places=False, cached=True, out_dir=tmp_path / "out2")
    assert res2["files"] == 2 and fake.calls == n


def test_older_verdicts_are_reasked_by_analyze_only():
    from tripshots import library as lib
    shot = {"id": "S001", "sig": "abc", "t0": 0.0, "kind": "photo", "w": 10, "h": 10, "thumb": "x",
            "metrics": {"bright": 0.5}}
    lib.put_scores({lib.shot_key(shot): {"score": 7, "tags": ["old"]}}, "fake")  # a v1 verdict
    fake = FakeAI()
    import tripshots.text as text
    orig = text.contact_sheets
    text.contact_sheets = lambda shots, d, **k: [(Path("sheet.jpg"), [s["id"] for s in shots])]
    try:
        assert ai.score_shots([shot], fake, Path("."))["S001"]["tags"] == ["old"] and fake.calls == 0
        got = ai.score_shots([shot], fake, Path("."), min_version=ai.AI_VERSION)
        assert got["S001"]["caption"] == "shot S001" and fake.calls == 1
    finally:
        text.contact_sheets = orig


def test_query_matches_whole_words(tmp_path):
    def rec(name, caption):
        return {"id": name, "path": name, "kind": "photo", "captured": {"day": "2025-01-01"}, "people": {"names": []},
                "location": None, "media": {"orientation": "landscape", "duration": None},
                "shots": [{"id": name, "t0": 0, "ai": {"caption": caption, "description": "", "tags": [],
                           "landmark": None, "scene": "other", "aesthetic": 7}, "technical": {"sharpness_label": "sharp"},
                           "faces": [], "best_moment": None, "similar_group": None}]}
    (tmp_path / "media.jsonl").write_text("\n".join(json.dumps(r) for r in (
        rec("a", "A cat on a wall"), rec("b", "Stars scattered over the desert"), rec("c", "Two cats asleep"))))
    assert [r["id"] for r in analysis.query(tmp_path, text="cat")] == ["a", "c"]
