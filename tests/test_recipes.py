"""Recipes: each reference reel's own cut, picture shape and text, kept in the learned style and followed by
the rhythm, the casting of the opening hold, the text and the critic."""
import numpy as np
import pytest

from tripshots import critic, learn, recipes, story, typo
from tripshots.config import DEFAULT_STYLE, load_style

HOLD = [9.25, 0.6, 1.267, 0.767, 0.567, 0.767, 0.733, 2.3, 0.6, 0.683, 1.05, 0.783, 1.367]   # a hold, then a burst
FLASH = [0.2] * 10 + [0.5, 0.55, 0.5, 0.5, 0.55, 0.5, 0.5, 0.45, 0.5, 0.5, 0.5]             # flashes, then steady
EVEN = [1.57] * 14
LYRICS = {"kind": "lyrics", "per_word": True, "look": "caps", "color": "pale yellow", "position": "center",
          "size": "large", "lines": [{"text": "WHEN I GET OLDER", "from": 0.2, "to": 1.6, "role": "lyric"}]}
SUNG = [{"text": "When I get older", "start": 0.0, "end": 1.5}, {"text": "I will be stronger", "start": 1.5, "end": 3.1},
        {"text": "They'll call me freedom", "start": 3.1, "end": 4.6},
        {"text": "Just like a waving flag", "start": 4.6, "end": 7.5},
        {"text": "When I get older", "start": 9.1, "end": 10.7}]


def _measure(lens, tempo=112.0, aspect=0.5625):
    return {"shot_lens": lens, "duration": round(sum(lens), 2), "tempo": tempo, "aspect": aspect}


def _grid(bl=60 / 112, n=60, drop=None):
    beats = [round(i * bl, 4) for i in range(n)]
    g = {"beats_all": beats, "energy_all": [0.3 if drop is None or b < drop else 0.9 for b in beats], "beat_len": bl,
         "beats": beats, "thresholds": (0.35, 0.7), "music_start": 0.0}
    if drop is not None:
        g["drops"] = [drop]
    return g


def _style(*recs):
    st = load_style("beat-montage")
    st["recipes"] = list(recs)
    return st


def _hold_recipe(own=True, exact=False):
    card = {"format": "montage", "open": "person", "text": LYRICS}
    if exact:  # its words as reftext copied them off the reference: one per sung word, before the turn
        card["_exact"] = {"events": [{"t0": 0.4 + 0.5 * i, "t1": 0.85 + 0.5 * i, "text": w, "box": [0.4, 0.45, 0.6, 0.53],
                                      "size": 0.08, "lines": 1, "color": [252, 236, 160]}
                                     for i, w in enumerate(("WHEN", "I", "GET", "OLDER"))],
                          "font": {"font": "gf:Oswald:700", "score": 0.8}}
    r = recipes.build(_measure(HOLD, aspect=1.78), card, "https://www.instagram.com/reel/AAA/", 1)
    return {**r, "_own": own}


def _shot(i, kind="video", src=None, t0=0.0, t1=4.0, score=7, people=0, motion=None):
    return {"id": f"S{i:03d}", "kind": kind, "src": src or f"/x/{i}.{'mp4' if kind == 'video' else 'jpg'}",
            "sig": f"g{i}", "t0": t0, "t1": t1, "w": 1920, "h": 1080, "fps": 30, "thumb": "",
            "metrics": {"pan": 0.0, "activity": 0.3},
            "ai": {"score": score, "mood": "calm", "scene": "landscape", "motion": motion,
                   "people": {"count": people, "activity": "walking away" if people else ""}}}


# ----------------------------------------------------------------- what a reference is
def test_structure_reads_the_shape_of_a_cut():
    assert recipes.structure(HOLD) == ("hold_burst", 9.25)
    name, turn = recipes.structure(FLASH)
    assert name == "flash_intro" and abs(turn - 2.0) < 1e-6
    assert recipes.structure(EVEN) == ("steady", 0.0)
    assert recipes.structure([0.5, 0.3, 0.9, 0.4, 1.2, 0.3, 0.6, 0.25])[0] == "montage"
    assert recipes.structure([4.0, 5.0])[0] == "steady"            # too few shots to call a shape
    assert [recipes.frame_name(a) for a in (2.39, 1.78, 1.33, 1.0, 0.5625, None)] == \
        ["2.39:1", "16:9", "4:3", "1:1", "9:16", "9:16"]


def test_build_keeps_what_the_reference_does():
    r = _hold_recipe()
    assert r["id"] == "r1" and r["structure"] == "hold_burst" and r["turn"] == 9.25 and r["frame"] == "16:9"
    assert r["open"] == "person" and r["text"]["kind"] == "lyrics" and r["text"]["per_word"]
    assert "holds its first shot 9.2s" in recipes.describe(r) and "one at a time" in recipes.describe(r)
    # nonsense from the AI falls back to something safe; a tease without its words is no text at all
    odd = recipes.build(_measure(EVEN), {"format": "opera", "open": "sideways",
                                         "text": {"kind": "tease", "look": "neon", "lines": []}}, "x.mp4", 2)
    assert odd["format"] == "montage" and "open" not in odd and odd["text"]["kind"] == "none"
    assert odd["text"]["look"] == "sans" and odd["structure"] == "steady"
    # sung lines under an even edit are subtitles, not a word-by-word hold
    sub = recipes.build(_measure(EVEN), {"text": {"kind": "lyrics", "lines": []}}, "y.mp4", 3)
    assert sub["text"]["kind"] == "subtitles"
    assert recipes.build(_measure(EVEN), None, "z.mp4", 4)["text"]["kind"] == "none"      # no AI: timing only
    assert "recipes" in DEFAULT_STYLE and DEFAULT_STYLE["story"]["recipe"] == "auto"      # learn keeps the key


def test_choose_takes_the_recipe_of_the_song_it_came_with():
    a = recipes.build(_measure(HOLD), {"text": LYRICS}, "https://www.instagram.com/reel/AAA/?igsh=x", 1)
    b = recipes.build(_measure(EVEN, tempo=154.0), {}, "https://www.instagram.com/reel/BBB/", 2)
    st = _style(a, b)
    mus = {"tempo": 112.0, "duration": 21.0}
    own = recipes.choose(st, "https://www.instagram.com/reel/BBB/", mus)
    assert own["id"] == "r2" and own["_own"]
    assert recipes.choose(st, None, mus, want="off") is None and recipes.choose(st, None, None) is None
    assert recipes.choose(st, None, mus, want="2")["id"] == "r2" and recipes.choose(st, None, mus, want="r1")["id"] == "r1"
    assert not recipes.choose(st, None, mus, want=1)["_own"]
    with pytest.raises(Exception):
        recipes.choose(st, None, mus, want="r9")
    # another song: the recipe that fits it (tempo, length, whether it has words to show)
    assert recipes.choose(st, "/music/song.mp3", {"tempo": 154.0, "duration": 30.0})["id"] == "r2"
    assert recipes.choose(st, "/music/song.mp3", {"tempo": 112.0, "duration": 30.0}, {"lines": SUNG})["id"] == "r1"
    assert recipes.choose(_style(), None, mus) is None
    assert abs(recipes.tempo_scale(112, 112) - 1) < 1e-9 and abs(recipes.tempo_scale(112, 56) - 1) < 1e-9
    assert abs(recipes.length_for({**a, "_own": False}, {"tempo": 140.0}) - a["duration"] * 0.8) < 0.01


def test_apply_sets_the_style_up_for_one_recipe():
    st = _style()
    st["loop"] = True
    r = _hold_recipe()
    recipes.apply(st, r, {"tempo": 112.0})
    assert st["duration"]["target"] == r["duration"] and st["frame"]["aspect"] == "16:9"
    assert st["text"]["hook"]["mode"] == "off" and st["story"]["hook_text"] == "off"      # lyrics: no invented hook
    assert st["text"]["location"]["mode"] == "off" and st["loop"] is False and st["_recipe"] is r
    assert st["attention"]["open"]["shot"] == "person"
    assert st["panels"]["use"] == 0.0  # the style's averaged split screens aren't in this one example's cut
    tease = recipes.build(_measure(FLASH), {"format": "pov", "text": {
        "kind": "tease", "lines": [{"text": "this is", "from": 0, "to": 2, "role": "tease"},
                                   {"text": "the faroe islands", "from": 2, "to": 7, "role": "payoff"}]}}, "t.mp4", 1)
    st = _style()
    st["text"]["hook"]["mode"] = "off"
    recipes.apply(st, tease, None, keep=("format",))
    assert st["text"]["hook"]["mode"] == "ai" and st["story"].get("format") != "pov"      # asked-for format stays
    assert recipes.reference_lines(tease) == {"tease": "this is", "payoff": "the faroe islands"}
    subs = recipes.build(_measure(EVEN), {"text": {"kind": "subtitles"}}, "s.mp4", 1)
    st = _style()
    recipes.apply(st, subs, None)
    assert st["story"]["captions"] == "original" and st["text"]["hook"]["mode"] == "off"


# ------------------------------------------------------------------------ rhythm
def test_rhythm_follows_the_recipe_on_the_beat():
    g = _grid(drop=round(17 * 60 / 112, 4))         # the song drops on beat 17 (9.1 s)
    st = _style()
    r = _hold_recipe(own=False)                     # the recipe on a song of the same tempo, not its own sound
    recipes.apply(st, r, {"tempo": 112.0})
    out = story.rhythm(g, st, st["duration"]["target"])
    segs = out["segments"]
    assert abs(segs[0]["dur"] - 17 * 60 / 112) < 0.05                                     # the hold ends on the drop
    assert [s["role"] for s in segs[:2]] == ["hook", "peak"] and segs[-1]["role"] == "ending"
    assert abs(len(segs) - len(HOLD)) <= 1 and max(s["dur"] for s in segs[1:]) < 3.0
    assert abs(sum(s["dur"] for s in segs) - out["duration"]) < 1e-3 and 19.5 < out["duration"] < 21.5
    half = g["beat_len"] / 4
    assert all(min(abs(s["out_start"] - b) % half for b in g["beats_all"][:1]) < 0.035
               or half - (s["out_start"] % half) < 0.035 for s in segs)                   # cuts on the quarter-beat grid
    # on the reference's own sound every cut sits where the reference had it, beat tracker or not
    st0 = _style()
    r0 = _hold_recipe()
    recipes.apply(st0, r0, {"tempo": 112.0})
    assert not st0.get("_music_exact")              # no sound file here: nothing to line up with
    own = story.rhythm(g, st0, st0["duration"]["target"])["segments"]
    want = np.cumsum(HOLD)
    assert len(own) == len(HOLD)
    assert all(abs(s["out_start"] + s["dur"] - w) <= 1 / 30 + 1e-6 for s, w in zip(own, want))
    assert all(abs(s["dur"] * 30 - round(s["dur"] * 30)) < 0.01 for s in own)             # whole frames
    # the same recipe on a faster song keeps each shot's length in beats
    fast = _grid(bl=60 / 140)
    st2 = _style()
    r2 = _hold_recipe(own=False)
    recipes.apply(st2, r2, {"tempo": 140.0})
    segs2 = story.rhythm(fast, st2, st2["duration"]["target"])["segments"]
    assert abs(segs2[0]["dur"] / (60 / 140) - 17) <= 1.01 and segs2[0]["role"] == "hook"
    # flashes first, then steady shots; nothing under 0.2 s
    st3 = _style()
    fl = {**recipes.build(_measure(FLASH), {}, "f.mp4", 1), "_own": True}
    recipes.apply(st3, fl, {"tempo": 112.0})
    segs3 = story.rhythm(_grid(), st3, st3["duration"]["target"])["segments"]
    peak = next(i for i, s in enumerate(segs3) if s["role"] == "peak")
    assert peak >= 3 and max(s["dur"] for s in segs3[:peak]) <= 0.3 and min(s["dur"] for s in segs3) >= 0.19
    assert segs3[peak]["dur"] > segs3[0]["dur"]
    # an even reference stays even
    st4 = _style()
    ev = {**recipes.build(_measure(EVEN, tempo=154.0), {}, "e.mp4", 1), "_own": True}
    recipes.apply(st4, ev, {"tempo": 154.0})
    ds = [s["dur"] for s in story.rhythm(_grid(bl=60 / 154, n=80), st4, st4["duration"]["target"])["segments"]]
    assert max(ds) - min(ds) < 0.45 and abs(len(ds) - len(EVEN)) <= 1


def test_own_sound_cuts_move_onto_the_hit_they_were_made_on(tmp_path):
    import soundfile as sf
    sr = 22050
    y = 0.002 * np.random.default_rng(1).standard_normal(int(sr * 6.0)).astype("float32")
    for hit in (2.06, 3.5):                                              # two loud hits
        i = int(hit * sr)
        y[i:i + 2000] += 0.8 * np.exp(-np.arange(2000) / 300.0) * np.sin(np.arange(2000) * 0.3)
    wav = tmp_path / "own.wav"
    sf.write(wav, y, sr)
    r = {"shots": [2.0, 1.0, 1.5, 1.5], "_own": True}                    # cuts measured at 2.0, 3.0, 4.5, 6.0
    cuts = recipes.own_cuts(r, wav)
    assert abs(cuts[0] - 2.06) < 0.035                                   # two frames early: onto the hit
    assert abs(cuts[1] - 3.0) < 0.02 and abs(cuts[2] - 4.5) < 0.02       # no hit near: left alone
    assert cuts[-1] == 6.0
    assert recipes.own_cuts(r, tmp_path / "missing.wav") == [2.0, 3.0, 4.5, 6.0]
    st = _style()
    recipes.apply(st, r, {"tempo": 112.0, "path": str(wav)})
    assert st["_music_exact"] and r["_cuts"] == cuts


def test_a_hold_reel_does_not_loop():
    st = _style()
    st["loop"] = True
    recipes.apply(st, _hold_recipe(), {"tempo": 112.0})
    assert st["loop"] is False and st["story"]["loop"] is False
    st2 = _style()
    st2["loop"] = True
    st2["story"]["loop"] = True
    recipes.apply(st2, _hold_recipe(), {"tempo": 112.0}, keep=("loop",))  # asked for: the story's loop stays
    assert st2["story"]["loop"] is True


# -------------------------------------------------------------------- the hold
def test_the_hold_is_one_continuous_moving_clip():
    long_clip = [_shot(i, src="/x/long.mp4", t0=4.0 * i, t1=4.0 * (i + 1), score=7.5, people=1, motion="drone")
                 for i in range(3)]                                 # 12 s stored as three back-to-back chunks
    short = _shot(10, score=9.5, t1=3.0)
    photo = _shot(11, kind="photo", score=9.8)
    other = [_shot(20 + i, score=7) for i in range(6)]
    shots = long_clip + [short, photo] + other
    spans = story.clip_spans(shots)
    assert spans["S000"] == (0.0, 12.0) and spans["S010"] == (0.0, 3.0) and "S011" not in spans
    st = load_style("beat-montage")
    cands = story.hold_candidates(shots, 9.0, st, "person")
    assert cands and cands[0][0]["id"] == "S000"                    # the best-looking shot can't hold 9 s; a photo never
    assert all(c[0]["kind"] == "video" and c[0]["src"] != short["src"] for c in cands)
    assert len({c[0]["src"] for c in cands}) == len(cands)
    segs = [{"role": "hook", "out_start": 0.0, "dur": 9.0}] + \
           [{"role": r, "out_start": 9.0 + i, "dur": 1.0} for i, r in enumerate(("peak", "release", "release", "ending"))]
    got = story.cast(shots, segs, st, hold=cands)
    assert got[0]["id"] == "S000" and not {"S001", "S002"} & {s["id"] for s in got[1:]}   # the hold uses those chunks
    assert story.hold_score(long_clip[0]) > story.hold_score(_shot(30, score=7.5))        # someone walking, a drone
    grey = [_shot(40 + i, src="/x/fog.mp4", t0=4.0 * i, t1=4.0 * (i + 1), score=8.0, people=1, motion="drone")
            for i in range(3)]                                      # a better-scored hold of grey surf
    for x in shots + grey:
        x.setdefault("metrics", {})["color"] = 3.0 if x in grey else 30.0
    assert story.hold_candidates(shots + grey, 9.0, st, "person")[0][0]["id"] == "S000"


def test_the_view_the_opening_held_is_not_shown_again():
    def view(i, when, tags, **kw):
        s = _shot(i, **kw)
        s["created"] = when
        s["ai"].update(scene="forest", tags=tags)
        return s
    road = ["redwoods", "forest", "road", "sunlight"]
    held = view(0, "2026-10-23T12:27:00", road, t1=12.0, score=7.5, people=1, motion="drone")
    again = view(1, "2026-10-23T16:38:00", ["road", "redwoods", "trailer", "forest"], score=9.0)  # the road, hours on
    later = view(2, "2026-10-27T10:00:00", road, score=7)           # the same kind of place on another day
    creek = view(3, "2026-10-23T15:00:00", ["creek", "ferns", "forest"], score=7)   # that day, another view
    assert story.same_view(held, again) and not story.same_view(held, later) and not story.same_view(held, creek)
    assert not story.same_view(held, _shot(9))                      # nothing known about when: not called a repeat
    st = load_style("beat-montage")
    segs = [{"role": "hook", "out_start": 0.0, "dur": 9.0}] + \
           [{"role": r, "out_start": 9.0 + i, "dur": 1.0} for i, r in enumerate(("peak", "release", "release", "ending"))]
    shots = [held, again, later, creek] + [_shot(20 + i, score=7) for i in range(4)]
    got = story.cast(shots, segs, st, hold=[(held, 9.0)])
    assert got[0]["id"] == "S000" and "S001" not in {s["id"] for s in got}       # the best shot left, yet a repeat
    few = story.cast([held, again, later, creek], segs, st, hold=[(held, 9.0)])
    assert "S001" in {s["id"] for s in few}                         # with nothing else to show, it still fills a slot


def test_one_kind_of_view_does_not_keep_coming_back():
    def rig(i, tags, score):
        s = _shot(i, score=score, motion="drone")
        s["ai"].update(scene="aerial", tags=tags)
        return s
    rigs = [rig(0, ["truck", "camper", "trailer", "road trip", "mountains", "drone"], 8.4),
            rig(1, ["drone", "pickup truck", "teardrop trailer", "mountain road", "granite"], 8.3),
            rig(2, ["aerial", "drone", "pickup truck", "camper trailer", "cliff", "ocean"], 8.2),
            rig(3, ["drone", "truck", "trailer", "desert road", "mesa"], 8.2)]
    assert story.alike(rigs[0], rigs[1]) and story.alike(rigs[1], rigs[2]) and not story.alike(rigs[0], _shot(9))
    lake = rig(4, ["drone", "lake", "island", "pines"], 8.0)        # from the drone too, of something else
    assert not story.alike(rigs[0], lake)
    others = [_shot(20 + i, score=7.4) for i in range(8)]
    segs = [{"role": r, "out_start": float(i), "dur": 1.0}
            for i, r in enumerate(("hook", "release", "release", "peak", "release", "release", "ending"))]
    got = story.cast(rigs + [lake] + others, segs, load_style("beat-montage"))
    assert sum(s["id"] in {"S000", "S001", "S002", "S003"} for s in got) <= 2     # the four best shots, one motif
    assert len({s["id"] for s in got}) == len(got)


def test_one_landmark_is_shown_once():
    domes = [_shot(i, score=8.4 - 0.1 * i) for i in range(3)]
    for d, name in zip(domes, ("Half Dome, Yosemite", "Half Dome", "Half Dome")):
        d["ai"]["landmark"] = name
    others = [_shot(20 + i, score=7.4) for i in range(8)]
    segs = [{"role": r, "out_start": float(i), "dur": 1.0}
            for i, r in enumerate(("hook", "release", "release", "peak", "release", "release", "ending"))]
    got = story.cast(domes + others, segs, load_style("beat-montage"))
    assert sum(s["id"] in {"S000", "S001", "S002"} for s in got) == 1


def test_a_grey_shot_does_not_close_a_colourful_reel():
    shots = [_shot(i, score=7.6) for i in range(10)]
    for s in shots:
        s["metrics"]["color"] = 30.0
    fog = shots[0]          # someone at a foggy shore: a closer by every other measure
    fog["ai"].update(role="closer", people={"count": 1, "activity": "standing"})
    shots[2]["ai"].update(score=9.0, people={"count": 1, "activity": "walking"})       # the opening
    shots[3]["ai"].update(score=9.0)                                                   # the turn
    segs = [{"role": r, "out_start": float(i), "dur": 1.0} for i, r in enumerate(("hook", "peak", "release", "ending"))]
    style = load_style("beat-montage")
    assert story.cast(shots, segs, style)[-1]["id"] == "S000"
    fog["metrics"]["color"] = 3.0
    shots[1]["ai"].update(role="closer")
    assert story.cast(shots, segs, style)[-1]["id"] == "S001"
    fog["ai"].update(score=9.5, role="opener", people={"count": 1, "activity": "walking"})  # the best opener, grey
    assert story.cast(shots, segs, style)[0]["id"] != "S000"


def test_the_ai_auditions_the_opening_hold(tmp_path):
    from PIL import Image

    class Backend:
        asked = 0

        def ask(self, prompt, images, max_tokens=300):
            Backend.asked += 1
            assert "9 seconds" in prompt and Image.open(images[0]).size[0] > 400   # one sheet, rows A..C
            return 'Sure. {"pick": "C", "second": "A", "why": "the person stays in frame"}'

    cands = [(_shot(i, src=str(tmp_path / f"{i}.mp4"), t1=12.0), 9.0 - i) for i in range(3)]
    out = recipes.audition(cands, 9.2, tmp_path, Backend(), _hold_recipe())
    assert [s["id"] for s, _ in out] == ["S002", "S000", "S001"]
    again = recipes.audition(cands, 9.2, tmp_path, Backend(), _hold_recipe())
    assert [s["id"] for s, _ in again] == ["S002", "S000", "S001"] and Backend.asked == 1   # cached
    assert recipes.audition(cands, 9.2, tmp_path, None) == cands                             # no AI: the numbers decide

    class Broken:
        def ask(self, *a, **k):
            raise RuntimeError("offline")

    other = [(_shot(i + 5, src=str(tmp_path / f"{i}.mp4"), t1=12.0), 5.0) for i in range(2)]
    assert recipes.audition(other, 9.2, tmp_path, Broken()) == other


# ------------------------------------------------------------------------ text
def test_lyrics_appear_word_by_word_until_the_turn():
    ws = recipes.lyric_words(SUNG, 9.1)
    assert [w["text"] for w in ws][:4] == ["When", "I", "get", "older"] and len(ws) == 17      # the 9.1 s line is the burst
    assert all(abs(w["start"] * 30 - round(w["start"] * 30)) < 0.01 and w["duration"] >= 0.099 for w in ws)
    assert all(a["start"] + a["duration"] <= b["start"] + 1e-6 for a, b in zip(ws, ws[1:]))    # one word at a time
    starts = {w["text"]: w["start"] for w in ws}
    assert abs(starts["stronger"] - 2.5) < 0.6 and ws[-1]["start"] + ws[-1]["duration"] <= 9.1
    assert ws[-1]["start"] < 7.0                                    # a trailing line doesn't slow its words down
    lines = recipes.lyric_words(SUNG, 9.1, per_word=False)
    assert [ln["text"] for ln in lines] == ["When I get older", "I will be stronger", "They'll call me freedom",
                                            "Just like a waving flag"]
    assert recipes.lyric_words([], 9.0) == []


def _plan(recipe, durs, roles=None):
    t, segs = 0.0, []
    for i, d in enumerate(durs):
        segs.append({"shot_id": f"S{i:03d}", "out_start": round(t, 4), "dur": d, "speed": 1.0,
                     "role": (roles or {}).get(i, "release")})
        t += d
    return {"duration": round(t, 4), "segments": segs, "overlays": [], "music": {"start": 0.0},
            "recipe": recipes.brief(recipe)}


def test_text_overlays_do_what_the_reference_text_does():
    r = _hold_recipe()
    plan = _plan(r, [9.1, 0.6, 1.2, 0.8, 0.6, 0.8, 0.7, 2.3, 0.6, 0.7], {0: "hook", 1: "peak"})
    assert recipes.turn_time(plan) == 9.1 and plan["recipe"]["hold"] == 9.25 and plan["recipe"]["lens"][0] == 9.25
    assert recipes.text_overlays(plan, r, {"lines": SUNG}, {}) == []    # a transcript is never put on screen
    rx = _hold_recipe(exact=True)
    ov = recipes.text_overlays(plan, rx, {"lines": SUNG}, {})
    assert [o["text"] for o in ov] == ["WHEN", "I", "GET", "OLDER"] and {o["recipe"] for o in ov} == {"lyric"}
    s = ov[0]["style"]
    assert s["font"] == "gf:Oswald:700" and s["uppercase"] and s["anim"] == "cut" and s["y"] == 0.49
    assert s["color"][0] > 240 and s["color"][2] < 200 and 40 < s["size"] < 60 and ov[0]["start"] == 0.4  # by width
    # lyrics we can't copy: no line of our own over someone else's song
    silent = {**r, "text": {**r["text"], "lines": []}}
    assert recipes.text_overlays(plan, silent, None, {"hook": "eleven days out west"}) == []
    # tease, then the payoff from the turn on
    tease = {**recipes.build(_measure(FLASH), {"text": {"kind": "tease", "look": "sans", "size": "small", "lines": [
        {"text": "this is", "from": 0, "to": 2, "role": "tease"}]}}, "t.mp4", 1), "_own": True}
    p2 = _plan(tease, [0.2] * 10 + [0.5] * 11, {0: "hook", 10: "peak"})
    ov = recipes.text_overlays(p2, tease, None, {"hook": "x", "tease": "this is", "payoff": "the west coast"})
    assert [(o["type"], o["recipe"], o["text"]) for o in ov] == [("hook", "tease", "this is"),
                                                                 ("label", "payoff", "the west coast")]
    assert abs(ov[1]["start"] - 2.0) < 1e-6 and ov[0]["style"]["anim"] == "fade" and "color" not in ov[0]["style"]
    assert recipes.text_overlays(p2, tease, None, {"tease": "this is"}, hook="mine")[0]["text"] == "mine"
    title = {**recipes.build(_measure(EVEN), {"text": {"kind": "title", "look": "script", "color": "yellow", "lines": [
        {"text": "The urge to capture.", "from": 0, "to": 21}]}}, "u.mp4", 1), "_own": True}
    p3 = _plan(title, [1.5] * 8)
    ov = recipes.text_overlays(p3, title, None, {"hook": "The urge to wander."})
    assert len(ov) == 1 and ov[0]["recipe"] == "title" and ov[0]["duration"] > 11 and ov[0]["style"]["font"] == "caveat"
    # a title the reference shows for a while is ours for the same share of the reel, in and out on a cut;
    # the words are the title the copywriter modelled on the reference's, not the hook
    brief = {**title, "text": {**title["text"], "lines": [{"text": "USA 2026", "from": 5.5, "to": 11.0, "role": "title"}]}}
    ov = recipes.text_overlays(p3, brief, None, {"hook": "The west I'd replay", "title": "West Coast 2026"})
    assert ov[0]["text"] == "West Coast 2026" and (ov[0]["start"], ov[0]["duration"]) == (3.0, 3.0)
    assert recipes.text_overlays(p3, {**title, "text": {"kind": "none"}}, None, {"hook": "x"}) == []
    assert recipes.color_of("black") is None and recipes.color_of("white") is None
    assert recipes.color_of("#ffe98a") == (255, 233, 138)


def test_a_styled_word_is_drawn_in_its_colour_and_cuts_in():
    cfg = {"font": "anton", "size": 150, "uppercase": True, "anim": "cut", "position": "center",
           "color": [255, 238, 150], "exit": 0.04, "line_gap": 1.05}
    el = typo.build_hook("older", 0.0, 0.5, cfg, np.zeros((1920, 1080, 3), np.uint8), [])
    assert el.exit == 0.04
    frame = el.draw(np.zeros((1920, 1080, 3), np.uint8), 0.2)
    ys, xs = np.nonzero(frame.max(axis=2) > 200)
    assert len(ys) > 500 and 700 < ys.mean() < 1250
    lit = frame[ys, xs].astype(float).mean(axis=0)
    assert lit[0] > 200 and lit[1] > 190 and lit[2] < lit[0] - 40                          # yellow, not white
    early = el.draw(np.zeros_like(frame), 0.02)
    assert (early.max(axis=2) > 200).sum() > 0.6 * len(ys)                                 # no fade-in: it is there


def _lit_rows(frame):
    ys = np.nonzero(frame.max(axis=2) > 200)[0]
    return int(ys.min()), int(ys.max())


def test_narrow_lettering_gets_a_condensed_face():
    t = recipes._text({"kind": "lyrics", "look": "sans", "width": "Narrow", "color": "Pale  Yellow", "per_word": True,
                       "lines": [{"text": "OLDER", "from": 0, "to": 1}]}, 10.0)
    assert t["width"] == "narrow" and t["color"] == "pale yellow" and t["upper"]
    st = recipes.text_style({"text": t}, per_word=True)
    assert st["font"] == "bebas" and st["uppercase"] and st["anim"] == "cut"
    assert st["color"][0] > 240 and st["color"][2] < st["color"][0] - 30                  # a light yellow, not white
    assert recipes.text_style({"text": {**t, "width": "normal"}})["font"] == "montserrat-bold"
    assert recipes.text_style({"text": {**t, "look": "caps"}})["font"] == "anton"
    assert recipes._text({"kind": "title", "width": "huge", "lines": [{"text": "x"}]}, 5.0)["width"] == "normal"
    assert recipes.text_style({"text": {**t, "look": "script"}})["font"] == "caveat"       # no condensed script


def test_text_on_the_picture_keeps_off_the_subject():
    # (subject top, subject bottom, picture top, picture bottom)
    assert typo.clear_rows(900, 100, None) == 900
    assert typo.clear_rows(700, 100, (900, 1100, 656, 1264)) == 700                        # already clear
    assert typo.clear_rows(950, 100, (900, 1100, 656, 1264)) == 900 - 18 - 100             # the nearer free side
    assert typo.clear_rows(1050, 100, (900, 1100, 656, 1264)) == 1100 + 18
    assert typo.clear_rows(950, 100, (700, 1240, 656, 1264)) == 950                        # no room: stays put
    cfg = {"font": "bebas", "size": 112, "uppercase": True, "anim": "cut", "position": "center", "line_gap": 1.05}
    black = np.zeros((1920, 1080, 3), np.uint8)
    y0, y1 = _lit_rows(typo.build_hook("stronger", 0.0, 0.5, cfg, black, []).draw(black.copy(), 0.2))
    subj = (y0 - 10, y1 + 60, 656, 1264)                                                   # someone right there
    m0, m1 = _lit_rows(typo.build_hook("stronger", 0.0, 0.5, cfg, black, [], avoid=subj).draw(black.copy(), 0.2))
    assert m1 < subj[0] and m0 > 656 and abs((m1 - m0) - (y1 - y0)) <= 2                   # moved above, in the picture


def test_a_line_held_across_shots_stays_in_the_safe_part_of_the_screen():
    from tripshots.render import TextTrack
    st = {"font": "montserrat-bold", "size": 56, "uppercase": False, "anim": "fade", "position": "upper"}
    peak = {"out_start": 0.0, "dur": 1.0, "subject_out": {"y0": 0.22, "y1": 0.6}}        # a summit under the words
    black = np.zeros((1920, 1080, 3), np.uint8)

    def rows(duration):
        tt = TextTrack({"overlays": [{"type": "label", "text": "The gallery", "start": 0.0, "duration": duration,
                                      "style": dict(st)}]}, [])
        return _lit_rows(tt.draw(black.copy(), 0.6, peak))
    held, one = rows(8.0), rows(1.0)
    a, b = typo.BANDS["upper"]
    assert a <= held[0] and held[1] <= b                    # up for many shots: where its style says, not by the first
    assert one[1] < 0.22 * 1920 and one[0] >= typo.SAFE["top"] - 20      # on that shot alone: above it, still in view
    low = {"out_start": 0.0, "dur": 1.0, "subject_out": {"y0": 0.12, "y1": 0.6}}         # no room above in view
    tt = TextTrack({"overlays": [{"type": "label", "text": "The gallery", "start": 0.0, "duration": 1.0,
                                  "style": dict(st)}]}, [])
    assert _lit_rows(tt.draw(black.copy(), 0.6, low))[0] >= typo.SAFE["top"] - 20
    # at plan time such a line moves to the third most of its shots leave free
    segs = [{"out_start": float(i), "dur": 1.0, "people": 1, "subject_out": {"y0": 0.18, "y1": 0.4}} for i in range(4)]
    plan = {"segments": segs, "duration": 4.0}
    assert recipes.held_position(plan, 0.0, 4.0, dict(st))["position"] != "upper"
    assert recipes.held_position(plan, 0.0, 1.0, dict(st))["position"] == "upper"         # one shot: the renderer's job
    free = [{**s, "subject_out": {"y0": 0.5, "y1": 0.9}} for s in segs]
    assert recipes.held_position({"segments": free, "duration": 4.0}, 0.0, 4.0, dict(st))["position"] == "upper"


def test_a_held_line_is_not_written_across_the_back_of_a_head():
    from tripshots.render import TextTrack
    st = {"font": "montserrat-bold", "size": 56, "uppercase": False, "anim": "fade", "position": "upper"}
    # somebody seen from behind fills the first shot (the view counts for nothing, the head does); views after it
    back = {"out_start": 0.0, "dur": 1.2, "people": True, "subject_out": {"y0": 0.17, "y1": 1.0}}
    views = [{"out_start": 1.2 + 0.5 * i, "dur": 0.5, "subject_out": {"y0": 0.55, "y1": 0.8}} for i in range(6)]
    plan = {"segments": [back] + views, "duration": 4.2}
    got = recipes.held_position(plan, 0.0, 4.1, dict(st))
    head = (0.17, 0.17 + 0.18 * 0.83)
    assert got["position"] == "upper" and got.get("y") is not None
    tt = TextTrack({"overlays": [{"type": "label", "text": "The road west", "start": 0.0, "duration": 4.1,
                                  "style": got}]}, [])
    rows = _lit_rows(tt.draw(np.zeros((1920, 1080, 3), np.uint8), 0.6, back))
    assert rows[1] < head[0] * 1920 or rows[0] > head[1] * 1920            # above or below the head, not on it
    assert typo.SAFE["top"] <= rows[0] and rows[1] <= typo.BANDS["upper"][1]
    # nobody's head in the way: the line stays in the middle of its third
    assert "y" not in recipes.held_position({"segments": views, "duration": 4.2}, 1.2, 4.1, dict(st))


def test_words_that_replace_each_other_stay_on_one_line():
    from tripshots.render import TextTrack
    st = {"font": "bebas", "size": 112, "uppercase": True, "anim": "cut", "position": "center", "line_gap": 1.05,
          "exit": 0.04}
    words = [("when", 0.1, 0.2), ("i", 0.1 + 0.2, 0.4), ("get", 0.7, 0.5)]                 # 0.1 + 0.2 > 0.3 in floats
    plan = {"frame": {"aspect": "16:9", "ar": 1.7778, "band": 608},
            "overlays": [{"type": "caption", "text": w, "start": a, "duration": d, "style": dict(st)}
                         for w, a, d in words]}
    seg = {"out_start": 0.0, "dur": 2.0, "subject_out": {"y0": 0.52, "y1": 0.66}}
    tt = TextTrack(plan, [])
    black = np.zeros((1920, 1080, 3), np.uint8)
    rows = [_lit_rows(tt.draw(black.copy(), a + 0.05, seg)) for _, a, _ in words]
    assert max(r[1] for r in rows) - min(r[1] for r in rows) <= 2                          # one baseline
    top, band = (1920 - 608) // 2, 608
    assert all(r[0] > top and r[1] < top + band for r in rows)                             # on the picture, not a bar
    assert all(r[1] < top + 0.52 * band or r[0] > top + 0.66 * band for r in rows)         # and off the person


# --------------------------------------------------------------------- learning
def test_the_cover_is_not_one_word_of_a_sentence():
    from tripshots.render import cover_time
    plan = {"segments": [{"dur": 9.0}, {"dur": 1.0}], "overlays": []}
    assert cover_time(plan) == pytest.approx(4.5)
    # a lyric sung word by word over the first six seconds: the still comes from the clean part of the shot
    plan["overlays"] = [{"type": "caption", "recipe": "lyric", "text": w, "start": i * 0.5, "duration": 0.5}
                        for i, w in enumerate("when i get older i will be stronger they'll call me".split())]
    assert 5.7 < cover_time(plan) < 9.0  # the last word ends at 5.5
    # a title belongs on the cover, once it has arrived
    plan["overlays"] = [{"type": "hook", "text": "the long way west", "start": 0.2, "duration": 2.4}]
    assert 0.8 <= cover_time(plan) <= 2.3
    # words all the way through: the middle, as before
    plan["overlays"] = [{"type": "caption", "text": "x", "start": 0.0, "duration": 9.0}]
    assert cover_time(plan) == pytest.approx(4.5)


def test_content_box_finds_baked_in_bars(tmp_path):
    import cv2
    rng = np.random.default_rng(3)

    def frame(h, w, top, bottom, left=0, right=0):
        im = np.zeros((h, w, 3), np.uint8)
        im[top:h - bottom, left:w - right] = rng.integers(60, 230, (h - top - bottom, w - left - right, 3))
        out = tmp_path / f"f{len(list(tmp_path.iterdir())):03d}.png"
        cv2.imwrite(str(out), im)
        return out

    wide = [frame(640, 360, 218, 218) for _ in range(8)]            # a 16:9 picture in a 9:16 file
    box = learn.content_box(wide)
    assert box and abs(box[1] - 218 / 640) < 0.02 and abs(box[3] - (640 - 218) / 640) < 0.02 and box[0] == 0 and box[2] == 1
    assert abs((box[2] - box[0]) * 360 / ((box[3] - box[1]) * 640) - 1.76) < 0.1
    assert learn.content_box([frame(640, 360, 0, 0) for _ in range(8)]) is None            # full-frame: no bars
    night = [frame(640, 360, 218, 218) for _ in range(7)] + [frame(640, 360, 320, 320)]
    assert learn.content_box(night) is not None                    # one black shot doesn't hide the bars
    assert learn.content_box([frame(640, 360, 20, 20) for _ in range(8)]) is None          # a sliver is not a letterbox
    assert learn.content_box([]) is None


# ----------------------------------------------------------------------- critic
def test_critic_checks_the_plan_against_its_reference():
    r = _hold_recipe()
    plan = _plan(r, [9.1, 0.6, 1.2, 0.8, 0.6, 0.8, 0.7, 2.3, 0.6, 0.7], {0: "hook", 1: "peak"})
    by = {f"S{i:03d}": _shot(i) for i in range(10)}
    rows = {k: (ok, fix) for k, ok, _w, _why, fix in recipes.checks(plan, by)}
    assert rows["opening_hold"] == (True, None) and rows["reference_text"][0] is False    # no words yet
    plan["overlays"] = recipes.text_overlays(plan, _hold_recipe(exact=True), {"lines": SUNG}, {})
    assert all(ok for _k, ok, *_ in recipes.checks(plan, by))
    by["S000"] = _shot(0, kind="photo")                             # a photo can't be a 9 s opening
    rows = {k: (ok, fix) for k, ok, _w, _why, fix in recipes.checks(plan, by)}
    assert rows["opening_hold"] == (False, "hold_shot")
    assert recipes.checks({"segments": plan["segments"]}, by) == []                        # no recipe: nothing to compare
    # the critic's own score: a lyric reel isn't marked down for having no hook line, a photo opening is
    for i, sg in enumerate(plan["segments"]):
        sg.update({"kind": "video", "src": f"/x/{i}.mp4"})
    cs = {c["check"]: c for c in critic.checks(plan, by, list(by.values()))}
    assert "hook_text" not in cs and cs["rhythm"]["ok"] and cs["ending"]["ok"] and not cs["opening_hold"]["ok"]
    by["S000"] = _shot(0)
    good = critic.checks(plan, by, list(by.values()))
    assert critic.score(good) > critic.score(list(cs.values())) + 10


# ------------------------------------------------------- learning when the AI runs out
class _LimitedAI:
    """Answers `ok` questions, then says its usage limit is reached (as Claude Code does)."""
    name = "fake"

    def __init__(self, ok: int):
        self.ok, self.asked = ok, 0

    def ask(self, prompt, images=None, max_tokens=4000):
        from tripshots import ai
        self.asked += 1
        if self.asked > self.ok:
            raise ai.AILimitError("the AI's usage limit is reached")
        if "```" in prompt or "yaml" in prompt.lower():
            return "```yaml\ntext:\n  preset: editorial\ndirection: slow, wide, quiet\n```"
        return '{"format": "montage", "open": "wide", "footage": "video", "text": {"kind": "title", "lines": [{"text": "WEST", "from": 0, "to": 5}]}}'


def _learn_with(monkeypatch, tmp_path, backend, n=3):
    monkeypatch.setattr(learn, "HOME", tmp_path)
    monkeypatch.setattr(learn, "USER_STYLES", tmp_path / "styles")
    files = []
    for i in range(n):
        f = tmp_path / f"ref{i}.mp4"
        f.write_bytes(b"x")
        files.append(str(f))
    monkeypatch.setattr(learn, "measure", lambda p, work: {
        "file": str(p), "duration": 12.0, "shot_lens": list(EVEN), "shot_len_median": 1.5, "cuts": len(EVEN) - 1,
        "aspect": 0.5625, "frames": [], "early_frames": [], "timed": [{"t": 0.5, "frame": "x.jpg"}]})
    monkeypatch.setattr(learn, "timed_sheets", lambda timed, out: [tmp_path / "sheet.jpg"])
    monkeypatch.setattr(learn, "sheet", lambda frames, out, **k: tmp_path / "sheet.jpg")
    monkeypatch.setattr(learn.ai_mod, "get_backend", lambda name=None: backend)
    import yaml
    return yaml.safe_load(learn.learn(files, "trip", None, None).read_text())


def test_learn_marks_what_the_ai_could_not_read(monkeypatch, tmp_path):
    ai_ = _LimitedAI(ok=2)                      # two references read, then the limit
    st = _learn_with(monkeypatch, tmp_path, ai_)
    kinds = [(r["text"]["kind"], bool(r.get("unread"))) for r in st["recipes"]]
    assert kinds == [("title", False), ("title", False), ("none", True)]
    assert ai_.asked == 3                       # it stopped asking: no style question after the refusal
    assert "not read yet" in recipes.describe(st["recipes"][2]) and "one line" in recipes.describe(st["recipes"][0])
    assert "text" not in st                     # nothing described yet, timing only
    # run again once the AI answers: only the unread reference and the description are asked for
    ai2 = _LimitedAI(ok=99)
    st = _learn_with(monkeypatch, tmp_path, ai2)
    assert ai2.asked == 2 and not any(r.get("unread") for r in st["recipes"])
    assert st["text"]["preset"] == "editorial" and st["direction"] == "slow, wide, quiet"
    # a later run with no AI answers at all keeps that description instead of going back to timing only
    st = _learn_with(monkeypatch, tmp_path, _LimitedAI(ok=0))
    assert st["text"]["preset"] == "editorial" and not any(r.get("unread") for r in st["recipes"])


def test_auto_prefers_a_recipe_that_was_read():
    a = recipes.build(_measure(EVEN), None, "a.mp4", 1, unread=True)
    b = recipes.build(_measure(EVEN), {"text": {"kind": "none"}}, "b.mp4", 2)
    assert a["unread"] and "unread" not in b
    assert recipes.choose(_style(a, b), "/music/song.mp3", {"tempo": 112.0, "duration": 30.0})["id"] == "r2"


# ------------------------------------------------------------------ a name on every shot
POSTCARDS = {"kind": "labels", "look": "caps", "size": "medium", "position": "center", "color": "multicolor postcard",
             "lines": [{"text": f"Greetings From... {n}", "from": 1.5 * i, "to": 1.5 * i + 1.5, "role": "label"}
                       for i, n in enumerate(["COLORADO", "ARIZONA", "UTAH", "NEVADA"])]}
FACTS = [{"region": "California", "place": "Yosemite National Park, California", "landmark": "Half Dome"},
         {"region": "California", "place": "Yosemite National Park, California", "near": True},
         {"region": "Oregon", "place": "Cannon Beach, Oregon"}, {}, {"region": "Washington"}]


def _postcards():
    return {**recipes.build(_measure(EVEN), {"format": "list", "text": POSTCARDS}, "g.mp4", 7), "_own": True}


def test_a_labels_recipe_names_each_shot_like_its_reference():
    r = _postcards()
    assert recipes.label_lead(r) == "Greetings From..."
    assert recipes.reference_lines(r)["label"][:2] == ["Greetings From... COLORADO", "Greetings From... ARIZONA"]
    st = _style()
    st["text"]["labels"]["mode"] = "ai"
    recipes.apply(st, r, None)
    assert st["text"]["labels"]["mode"] == "off" and st["text"]["location"]["mode"] == "off"   # the recipe's own only
    # without a copywriter: the region. With one: its names, except a place the shot's facts don't have
    assert recipes.label_names(FACTS) == ["California", "California", "Oregon", "", "Washington"]
    names = recipes.label_names(FACTS, ["Yosemite", "Yosemite", "Cannon Beach", "Big Sur", "Olympic"])
    assert names == ["Yosemite", "Yosemite", "Cannon Beach", "", "Washington"]
    assert recipes.label_names(FACTS, ["Day one", "Still here", "Cold", "No signal", "Worth it"])[3] == "No signal"
    # one kind of name through the reel: when several shots only have their state, every shot gets its state
    trip = [{"region": "California", "place": "Yosemite National Park, California"}, {"region": "Wyoming"},
            {"region": "Oregon", "place": "Cannon Beach, Oregon"}, {"region": "Utah"}, {"region": "Montana"}]
    mixed = ["Yosemite", "Teton County", "Cannon Beach", "Utah", "Montana"]
    assert recipes.label_names(trip, mixed) == ["California", "Wyoming", "Oregon", "Utah", "Montana"]
    one = [{"region": "California", "place": p} for p in ("Yosemite National Park", "Big Sur", "Lake Tahoe")]
    assert recipes.label_names(one + [{"region": "California"}], ["Yosemite", "Big Sur", "Lake Tahoe", "Fresno"]) == [
        "Yosemite", "Big Sur", "Lake Tahoe", "California"]      # a trip inside one state keeps its place names
    plan = _plan(r, [1.5, 1.5, 1.5, 1.5, 1.5])
    ov = recipes.text_overlays(plan, r, None, {"labels": ["Yosemite", "Yosemite", "Cannon Beach", "", "Washington"]},
                               facts=FACTS)
    assert [(o["text"], o["start"], o["duration"]) for o in ov] == [
        ("Yosemite", 0.1, 2.9), ("Cannon Beach", 3.0, 1.5), ("Washington", 6.0, 1.45)]
    assert all(o["type"] == "label" and o["recipe"] == "label" and o["lead"] == "Greetings From..." for o in ov)
    assert ov[0]["shots"] == ["S000", "S001"] and ov[0]["style"]["fixed"] and ov[0]["style"]["fill"] == "picture"
    assert "color" not in ov[0]["style"] and ov[0]["style"]["anim"] == "cut"
    plan["overlays"] = ov
    assert not recipes.labels_stale(plan)
    assert [row[1] for row in recipes.checks(plan, {}) if row[0] == "reference_text"] == [True]
    plan["segments"][2]["shot_id"] = "S099"                       # the critic swapped a named shot
    assert recipes.labels_stale(plan)
    assert [row[1] for row in recipes.checks({**plan, "overlays": []}, {}) if row[0] == "reference_text"] == [False]


def test_after_the_critic_the_better_shot_still_gets_the_longer_slot():
    """The critic put the best view in a 0.2 s flash while a lesser one lingered 1.2 s: they trade places."""
    shots = [_shot(0, score=8.0), _shot(1, score=9.0, kind="photo"), _shot(2, score=8.2), _shot(3, score=8.9),
             _shot(4, score=9.5, t1=0.5)]
    by_id = {s["id"]: s for s in shots}

    def seg(i, dur, role="release", **kw):
        return {"shot_id": f"S{i:03d}", "kind": shots[i]["kind"], "dur": dur, "out_start": 0.0, "role": role,
                "in": 0.0, "speed": 1.0, **kw}
    plan = {"segments": [seg(0, 2.0, "hook"), seg(1, 0.2), seg(2, 1.2), seg(3, 0.4, "ending"), seg(4, 0.2)]}
    plan["segments"][1]["match"] = "motion"         # a cut the camera's motion carries stays as it is
    assert critic.long_slots(plan, by_id) == []
    critic._swap(plan["segments"], 1, 2, by_id)     # ...until one of its shots is changed by hand
    critic._swap(plan["segments"], 1, 2, by_id)
    assert not any(s.get("match") for s in plan["segments"])
    done = critic.long_slots(plan, by_id)
    assert [s["shot_id"] for s in plan["segments"]] == ["S000", "S002", "S001", "S003", "S004"]
    assert [s["dur"] for s in plan["segments"]] == [2.0, 0.2, 1.2, 0.4, 0.2] and len(done) == 1
    assert plan["segments"][2]["kind"] == "photo" and plan["segments"][1]["kind"] == "video"
    assert critic.long_slots(plan, by_id) == []     # (half a second of footage doesn't fill 1.2 s; the ending stays)


def test_the_critic_leaves_a_line_built_like_the_reference():
    plan = {"segments": [{"shot_id": "S000", "out_start": 0.0, "dur": 2.0}], "duration": 2.0, "overlays": [
        {"type": "hook", "text": "West Coast 2026", "start": 0.1, "duration": 1.8, "recipe": "title"}]}
    ops = [{"op": "text", "type": "hook", "text": "You won't believe this coast"}]
    critic.apply_ops(plan, {}, load_style("beat-montage"), ops)
    assert plan["overlays"][0]["text"] == "West Coast 2026"
    plan["overlays"][0].pop("recipe")
    critic.apply_ops(plan, {}, load_style("beat-montage"), ops)
    assert plan["overlays"][0]["text"] == "You won't believe this coast"


def test_a_postcard_name_keeps_its_place_and_its_lead_line():
    cfg = recipes.text_style(_postcards(), label=True)
    blank = np.zeros((1920, 1080, 3), np.uint8)
    a = typo.build_hook("Utah", 0.0, 1.5, cfg, blank, [], lead="Greetings From...")
    b = typo.build_hook("Yosemite National Park", 0.0, 1.5, cfg, blank, [], lead="Greetings From...")
    assert [ln.get("role") for ln in a.lines][0] == "lead" and a.lines[0]["text"] == "Greetings From..."
    assert abs(a.box[1] - b.box[1]) <= 2                          # the lead line doesn't jump from name to name
    wa, wb = a.box[2] - a.box[0], b.box[2] - b.box[0]
    assert wa > 0.4 * 1080 and wb <= 1080 - 60                    # a short name is set wide, a long one still fits
    frame = a.draw(blank.copy(), 0.5)
    ys, xs = np.nonzero(frame.max(axis=2) > 150)
    cols = {tuple(int(v) // 64 for v in frame[y, x]) for y, x in zip(ys[::7], xs[::7])}
    assert len(cols) >= 3                                         # a colour per letter, not one


def test_a_name_that_stays_put_sits_where_the_shots_leave_room():
    def seg(y0, y1, people=False):
        return {"shot_id": "S", "out_start": 0.0, "dur": 1.5, "people": people, "subject_out": {"y0": y0, "y1": y1}}
    names = ["Utah"] * 4
    mid = [seg(0.45, 0.8, True), seg(0.5, 0.7), seg(0.42, 0.9, True), seg(0.66, 0.9)]
    assert recipes.label_position(mid, names, "center") == "upper"     # people and subjects in the middle: go up
    assert recipes.label_position([seg(0.7, 0.95)] * 4, names, "center") == "center"   # the reference's place is free
    assert recipes.label_position([seg(0.1, 0.9, True)] * 4, names, "center") == "center"  # nowhere is free: stay
    assert recipes.label_position(mid, [""] * 4, "center") == "center"  # shots without a name don't vote
    plan = _plan(_postcards(), [1.5, 1.5, 1.5, 1.5])
    for s, m in zip(plan["segments"], mid):
        s.update(people=m["people"], subject_out=m["subject_out"])
    ov = recipes.label_overlays(plan, _postcards(), names)
    assert ov and all(o["style"]["position"] == "upper" for o in ov)
    assert ov[0]["style"]["lead_size"] >= 0.5 * ov[0]["style"]["size"]


def test_a_recipe_reel_never_shows_transcribed_words():
    from tripshots import recipes
    caps = [{"type": "caption", "text": "misheard", "start": 1.0, "duration": 2.0}]
    for kind in ("subtitles", "lyrics", "tease", "none"):
        assert recipes.subtitled({"_own": True, "text": {"kind": kind}}, caps) == []
    plan = {"duration": 10.0, "music": {"start": 0.0}, "segments": [{"out_start": 0.0, "dur": 10.0}]}
    rec = {"_own": True, "duration": 10.0, "text": {"kind": "lyrics", "lines": [{"text": "guess", "from": 0, "to": 2}]}}
    assert recipes.text_overlays(plan, rec, {"lines": [{"text": "wrong words", "start": 0, "end": 2}]}, {}) == []
    rec["text"]["exact"] = [{"text": "lately", "from": 0.4, "to": 1.2, "x": 0.5, "y": 0.4, "size": 0.03,
                             "lines": 1, "color": [250, 250, 250]}]
    assert recipes.text_overlays(plan, rec, None, {}) == []          # no face like its lettering: no words
    rec["text"]["font"] = "gf:Tinos:400"
    got = recipes.text_overlays(plan, rec, None, {})
    assert [o["text"] for o in got] == ["lately"] and got[0]["start"] == 0.4 and got[0]["style"]["y"] == 0.4
    assert got[0]["style"]["font"] == "gf:Tinos:400"
    assert recipes.text_overlays(plan, {**rec, "_own": False}, None, {}) == []   # another sound: not its words


def test_an_unanswered_tease_trails_off_with_dots():
    from tripshots import recipes
    assert recipes.trail_off("Just us, the rig and") == "Just us, the rig and..."
    assert recipes.trail_off("Some autumns you keep forever") == "Some autumns you keep forever"
    assert recipes.trail_off("this is the") == "this is the..."


def test_a_lyric_pause_is_not_shown_as_a_word():
    from tripshots import recipes
    got = recipes.lyric_words([{"text": "on my mind …", "start": 0.0, "end": 2.0},
                               {"text": "… on my mind", "start": 2.2, "end": 4.0}], 5.0)
    assert [w["text"] for w in got] == ["on", "my", "mind", "on", "my", "mind"]
