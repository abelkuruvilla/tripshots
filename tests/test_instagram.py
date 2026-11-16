"""Posting craft: caption checks, the voice file, hook rules, "vs usual" and the carousel."""
import json

import numpy as np
from PIL import Image

from tripshots import carousel, results, social
from tripshots.ai import _hook_rules


def test_caption_checks_catch_what_holds_a_post_back():
    s = {"caption": "#travel Big Sur in 3 days — save this!\nFollow for more and send it to a friend",
         "hashtags": ["bigsur", "fyp", "viral"], "keywords": ["big sur road trip", "bixby bridge", "monterey"]}
    got = " | ".join(social.checks(s))
    for bit in ("opens on a hashtag", "first 125 characters", "asks", "generic hashtags", "#fyp", "search keywords",
                "em dashes"):
        assert bit in got, bit
    ok = {"caption": "Big Sur in 3 days: Bixby Bridge at sunrise, McWay Falls at noon.\nThe Big Sur road trip "
                     "I'd do again.\nSend this to who you'd drive it with.",
          "hashtags": ["bigsur", "pacificcoasthighway"], "keywords": ["big sur road trip", "bixby bridge"]}
    assert social.checks(ok) == []


def test_clean_text_keeps_the_joiners_scripts_need():
    t = "മൂന്നാർ‌ലെ — the hills​ of Munnar… 5–10 km"
    out = social.clean_text(t)
    assert "‌" in out and "​" not in out and "—" not in out
    assert out.endswith(", the hills of Munnar... 5-10 km")


def test_voice_file_gives_only_what_was_filled_in(tmp_path):
    p = tmp_path / "voice.md"
    p.write_text("# voice.md\n\nCopy this.\n\n## Who I am\n\n- **Name:** Nadodi\n- **Handle:**\n"
                 "- **Who I am talking to:** (be specific)\n\n## Off limits\n\n- **Topics I do not post about:** "
                 "politics\n\n## My positions\n\n1. Slow travel beats checklists\n2.\n")
    v = social.voice_notes(p)
    assert "Who I am: Name: Nadodi" in v and "Off limits: Topics I do not post about: politics" in v
    assert "Slow travel beats checklists" in v and "Handle" not in v and "talking to" not in v
    assert social.voice_notes(tmp_path / "none.md") == ""


def test_hook_rules_mark_down_greetings_and_reward_a_name_up_front():
    assert _hook_rules("Bixby Bridge before sunrise", "montage") > _hook_rules("Hey guys welcome to our trip", "montage")
    assert _hook_rules("Six hundred km of coast", "list") > _hook_rules("A long drive down the coast", "list")
    assert _hook_rules("In this video: our road trip", "montage") < 5
    assert _hook_rules("Big Sur at dawn 🔥", "montage") < _hook_rules("Big Sur at dawn", "montage")


def test_vs_usual_is_views_over_the_median_of_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "STORE", tmp_path / "results.json")
    for i, v in enumerate([1000, 1200, 800, 9000]):
        results.add(tmp_path / f"r{i}.mp4", {"views": v, "avg_watch": 5, "sends": 3})
    m = results.multiples()
    assert m[str((tmp_path / "r3.mp4").resolve())] == 9.0
    assert results.preferences()["outliers"] == ["r3"]
    assert results.multiples(results.load()[:3]) == {}       # too few others to say what is usual


def test_carousel_from_a_reel(tmp_path):
    segs = []
    for i, col in enumerate([(200, 80, 40), (40, 120, 200), (60, 160, 70), (220, 200, 60), (120, 60, 160)]):
        f = tmp_path / f"p{i}.jpg"
        Image.fromarray(np.full((900, 1600, 3), col, np.uint8)).save(f)
        segs.append({"kind": "photo", "src": str(f), "shot_id": f"S{i}", "dur": 1.0, "layout": "kenburns"})
    segs.append(dict(segs[2]))                                          # a shot used twice is one slide
    plan = tmp_path / "trip.plan.json"
    plan.write_text(json.dumps({"segments": segs, "work": str(tmp_path), "overlays": [
        {"type": "hook", "text": "Three days on the coast", "start": 0, "duration": 1},
        {"type": "location", "text": "Big Sur, California", "start": 1, "duration": 1},
        {"type": "location", "text": "Monterey, California", "start": 3, "duration": 1}]}))
    res = carousel.make(plan, n=8, handle="nadodi_tales")
    files = [s["file"] for s in res["slides"]]
    assert len(files) == 6 and res["slides"][-1]["kind"] == "route" and res["slides"][-1]["places"][:2] == [
        "Big Sur", "Monterey"]
    assert res["cover_text"] == "Three days on the coast" and res["checks"] == []
    with Image.open(files[0]) as im:
        assert im.size == (1080, 1350)
        a = np.asarray(im.convert("RGB")).astype(int)
    assert abs(a[300, 540] - [200, 80, 40]).sum() < 60                 # the picture, coloured as the reel
    assert a[int(1350 * 0.62):int(1350 * 0.8)].max() > 240              # the cover's white title
    assert json.loads((tmp_path / "trip.carousel" / "carousel.json").read_text())["slides"]
    assert carousel.checks("one two three four five six seven", 4) == [
        "the cover title is 7 words: six or fewer read at thumbnail size",
        "4 slides: under 5 the swipe rarely starts (the reel may have too few distinct shots)"]


def test_a_carousel_is_edited_slide_by_slide(tmp_path):
    import json
    from PIL import Image
    from tripshots import carousel
    shots, segs = [], []
    for i in range(6):
        f = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (1600, 1200), (40 * i, 120, 200 - 30 * i)).save(f)
        shots.append({"id": f"S{i}", "kind": "photo", "src": str(f), "still": str(f), "thumb": str(f), "w": 1600,
                      "h": 1200, "t0": 0, "t1": 0, "ai": {"score": 9 - i}})
        if i < 5:
            segs.append({"kind": "photo", "src": str(f), "still": str(f), "shot_id": f"S{i}", "dur": 1.0,
                         "layout": "kenburns"})
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    plan = tmp_path / "trip.plan.json"
    plan.write_text(json.dumps({"segments": segs, "overlays": [{"type": "hook", "text": "Five stops"}],
                                "color": {}, "work": str(tmp_path)}))
    res = carousel.make(plan, n=5, route=False)
    assert [s["kind"] for s in res["slides"]] == ["cover", "shot", "shot", "shot", "shot"]
    cache = tmp_path / "trip.carousel" / ".cache"
    before = {f.name: f.stat().st_mtime_ns for f in cache.glob("*.jpg")}
    res = carousel.edit(plan, [{"op": "layout", "slide": 3, "layout": "trio"}, {"op": "handle", "text": "@nadodi_tales"},
                               {"op": "add", "shot_id": "S5", "at": 2}, {"op": "crop", "slide": 1, "zoom": 1.5, "x": 0.3}])
    assert len(res["slides"]) == 6 and res["slides"][1]["shots"] == ["S5"] and res["handle"] == "nadodi_tales"
    trio = res["slides"][3]
    assert trio["layout"] == "trio" and len(set(trio["shots"])) == 3
    with Image.open(trio["file"]) as im:
        px = im.convert("RGB").load()
        assert px[540, 812] != px[540, 1340] or px[100, 1100] != px[1000, 1100]   # three different pictures
    res = carousel.edit(plan, [{"op": "move", "from": 6, "to": 1}, {"op": "remove", "slide": 2}])
    assert res["slides"][0]["kind"] == "cover" and res["slides"][0]["shots"] == ["S4"] and len(res["slides"]) == 5
    assert len(list((tmp_path / "trip.carousel").glob("[0-9][0-9].jpg"))) == 5
    import pytest
    from tripshots.util import ReelError
    with pytest.raises(ReelError):
        carousel.edit(plan, [{"op": "swap", "slide": 2, "shot_id": "nope"}])
    with pytest.raises(ReelError):
        carousel.edit(plan, [{"op": "route", "on": True}])     # no places known
