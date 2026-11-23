"""The first seconds: the opening line on screen from frame one, an opening shot that stops the thumb, the
first-second QA checks, and skip rates in the results."""
import json

import pytest

from tripshots import qa, results, story


def _plan(overlays, recipe_text=None, first_kind="photo"):
    p = {"segments": [{"kind": first_kind, "out_start": 0.0, "dur": 1.2, "people": True},
                      {"kind": "video", "out_start": 1.2, "dur": 1.0}], "overlays": overlays}
    if recipe_text:
        p["recipe"] = {"id": "r1", "text": recipe_text}
    return p


def test_the_hook_is_on_screen_from_the_first_frame_without_an_entrance():
    plan = _plan([{"type": "hook", "text": "A moose walked through camp.", "start": 0.2, "duration": 2.4}])
    assert story.open_on_words(plan)
    h = plan["overlays"][0]
    assert h["start"] == 0.0 and h["duration"] == pytest.approx(2.6)   # ends where it ended
    assert h["style"]["anim"] == "cut"


def test_a_recipe_tease_keeps_its_lettering_but_grows_and_loses_the_fade():
    st = {"font": "gf:Inter:800", "size": 63, "anim": "fade", "color": [255, 202, 149]}
    plan = _plan([{"type": "caption", "text": "What's in my camera?", "start": 0.0, "duration": 2.5,
                   "style": dict(st), "recipe": "lyric"}], recipe_text="tease")
    assert story.open_on_words(plan)
    got = plan["overlays"][0]["style"]
    assert got["font"] == "gf:Inter:800" and got["color"] == [255, 202, 149]
    assert got["size"] == story.OPEN_MIN_SIZE and got["anim"] == "cut"


def test_sung_words_and_later_lines_are_left_alone():
    sung = _plan([{"type": "caption", "text": "lately", "start": 0.2, "duration": 0.6,
                   "style": {"anim": "fade"}, "recipe": "lyric"}], recipe_text="lyrics")
    assert story.open_on_words(sung) is None and sung["overlays"][0]["start"] == 0.2
    late = _plan([{"type": "hook", "text": "Later", "start": 1.5, "duration": 2.0}])
    assert story.open_on_words(late) is None
    off = _plan([{"type": "hook", "text": "Hi", "start": 0.2, "duration": 2.0}])
    assert story.open_on_words(off, {"open_text": "off"}) is None


def test_the_opening_shot_prefers_a_moving_clip_an_animal_and_light():
    clip = {"kind": "video", "ai": {"tags": ["moose", "campground"]}, "metrics": {"bright": 0.4}}
    photo = {"kind": "photo", "ai": {"tags": ["mountain"]}, "metrics": {"bright": 0.4}}
    dark = {"kind": "video", "ai": {"tags": ["forest"]}, "metrics": {"bright": 0.1}}
    assert story.first_frame_pull(clip) > story.first_frame_pull(dark) > story.first_frame_pull(photo)


def test_qa_wants_words_from_the_first_frame(tmp_path, monkeypatch):
    texts = [{"kind": "hook", "text": "Day two was this", "start": 0.4, "duration": 2.5,
              "box": [200, 400, 880, 520], "size": 100}]
    monkeypatch.setattr(qa, "picture_checks", lambda v, p: [])
    monkeypatch.setattr(qa, "contact_sheet", lambda *a, **k: tmp_path / "s.jpg")
    monkeypatch.setattr(qa, "ffprobe", lambda v: {"streams": [], "format": {"duration": "10"}})
    rep = qa.check(tmp_path / "r.mp4", {"segments": []}, texts)
    got = {c["check"]: c for c in rep["checks"]}
    assert not got["open_words"]["ok"]
    texts[0]["start"] = 0.0
    rep = qa.check(tmp_path / "r.mp4", {"segments": []}, texts)
    assert {c["check"]: c for c in rep["checks"]}["open_words"]["ok"]
    texts[0]["anim"] = "fade"
    rep = qa.check(tmp_path / "r.mp4", {"segments": []}, texts)
    assert not {c["check"]: c for c in rep["checks"]}["open_words"]["ok"]


def test_skip_rates_are_recorded_and_reported_per_kind_of_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "STORE", tmp_path / "results.json")
    for name, kind, at, skip in (("a", "photo", 0.4, 73.1), ("b", "video", 0.0, 53.3), ("c", "photo", 0.2, 0.786)):
        plan = _plan([{"type": "hook", "text": "x", "start": at, "duration": 2.0}], first_kind=kind)
        plan["duration"] = 15.0
        (tmp_path / f"{name}.plan.json").write_text(json.dumps(plan))
        results.add(tmp_path / f"{name}.mp4", {"views": 1000, "avg_watch": 5.0, "sends": 4,
                                               "skip_rate": results.as_share(skip)})
    rows = results.load()
    assert rows[0]["metrics"]["skip_rate"] == pytest.approx(0.731)
    assert rows[1]["features"]["open"] == {"kind": "video", "people": True, "words_at_0": True}
    pref = results.preferences()
    assert pref["skip_by_open"]["photo, person"] == pytest.approx((0.731 + 0.786) / 2, abs=1e-3)
    assert pref["skip_by_open"]["video, person, words at 0"] == pytest.approx(0.533)
    # holding past 3 s counts in the score: the same watch time and sends, fewer skips, a better score
    assert rows[1]["score"] > rows[0]["score"]


def test_a_reveal_reel_still_opens_on_a_clip_rather_than_a_photo():
    clip = {"id": "a", "kind": "video", "ai": {"score": 7, "tags": ["arch"]}, "metrics": {"bright": 0.4}}
    photo = {"id": "b", "kind": "photo", "ai": {"score": 7, "tags": ["arch"]}, "metrics": {"bright": 0.4}}
    ctx = {"tease": True}
    assert story.role_score(clip, "hook", ctx) > story.role_score(photo, "hook", ctx)
