"""Reading a reference's own words: grouping lines into pieces of text, merging repeats, fonts, exact recipe text."""
import numpy as np

from tripshots import fontlib, recipes, reftext


def _track(f0, f1, box):
    return {"f0": f0, "f1": f1, "box": box, "pol": 1}


def test_lines_up_together_are_one_piece_of_text_and_a_sign_is_not_part_of_it():
    trs = [_track(0, 11, (100, 400, 300, 430)), _track(0, 11, (110, 440, 290, 470)),   # two lines of one subtitle
           _track(0, 11, (20, 100, 400, 300)),                                         # a big sign behind
           _track(12, 20, (100, 400, 260, 430)),                                       # the next line
           _track(0, 99, (900, 20, 1000, 40))]                                         # a watermark, up throughout
    evs = reftext.events(trs, 100)
    assert len(evs) == 3
    first = next(e for e in evs if e["f0"] == 0 and e["box"][1] >= 400)
    assert first["box"] == (100, 400, 300, 470)


def test_the_same_words_read_twice_are_one_line_with_the_tighter_box():
    a = {"t0": 0.0, "t1": 1.2, "text": "lately", "box": [0, 0, 0.5, 0.4], "size": 0.2, "color": [0, 0, 0], "pol": -1,
         "crop": 0}
    b = {**a, "t0": 0.1, "t1": 1.2, "box": [0.4, 0.4, 0.5, 0.45], "size": 0.04, "crop": 1}
    got = reftext.merge([a, b])
    assert len(got) == 1 and got[0]["size"] == 0.04 and got[0]["t1"] == 1.2


def test_recipe_text_keeps_whole_lines_one_at_a_time():
    ex = {"events": [
        {"t0": 0.0, "t1": 2.0, "text": "this is", "box": [0.4, 0.5, 0.6, 0.55], "size": 0.03, "lines": 1},
        {"t0": 1.8, "t1": 4.0, "text": "the west", "box": [0.4, 0.5, 0.6, 0.55], "size": 0.03, "lines": 1},
        {"t0": 2.0, "t1": 2.4, "text": "the w", "partial": True, "box": [0.4, 0.5, 0.5, 0.55], "size": 0.03}],
        "font": {"font": "gf:Tinos:400", "score": 0.7}}
    got = recipes.exact_text(ex)
    assert [(e["text"], e["to"]) for e in got["exact"]] == [("this is", 1.8), ("the west", 4.0)]
    assert got["font"] == "gf:Tinos:400" and got["exact"][0]["y"] == 0.525
    assert "font" not in recipes.exact_text({**ex, "font": {"font": "gf:Tinos:400", "score": 0.2}})


def test_library_font_names():
    assert fontlib.parse("gf:Playfair Display:700") == ("Playfair Display", 700)
    assert fontlib.parse("anton") is None
    assert ("Tinos", 400) in fontlib.candidates("latin")
    assert all("malayalam" in fontlib.CATALOG[f][2] for f, _ in fontlib.candidates("malayalam"))


def test_ink_colour_reads_the_letters_not_the_ground():
    img = np.full((60, 200, 3), (40, 90, 30), np.uint8)       # foliage-ish ground (BGR)
    img[20:40, 30:170:12] = 255                               # white strokes
    img[20:40, 31:170:12] = 255
    img[20:40, 32:170:12] = 255
    assert reftext.ink_colour(img) == [255, 255, 255]


def test_a_kept_tease_does_not_copy_the_references_place():
    plan = {"duration": 8.0, "music": {"start": 0.0}, "overlays": [],
            "segments": [{"shot_id": f"S{i}", "out_start": i * 1.0, "dur": 1.0, "role": "hook" if i == 0 else "build"}
                         for i in range(8)]}
    rec = {"_own": True, "duration": 8.0, "shots": [1.0] * 8, "text": {
        "kind": "tease", "font": "gf:Outfit:800", "lines": [{"text": "this is", "from": 0, "to": 4, "role": "tease"},
                                                             {"text": "the faroe islands", "from": 4, "to": 8, "role": "payoff"}],
        "exact": [{"text": "this is", "from": 0.0, "to": 3.9, "x": 0.5, "y": 0.5, "size": 0.02, "lines": 1},
                  {"text": "the faroe islands", "from": 3.9, "to": 7.7, "x": 0.5, "y": 0.5, "size": 0.02, "lines": 1}]}}
    got = recipes.text_overlays(plan, rec, None, {"tease": "this is", "payoff": "the american west"})
    assert "the faroe islands" not in [o["text"] for o in got] and "the american west" in [o["text"] for o in got]
    same = recipes.text_overlays(plan, rec, None, {"tease": "this is", "payoff": "the faroe islands"})
    assert [o["text"] for o in same] == ["this is", "the faroe islands"]          # all of its words kept: copied
