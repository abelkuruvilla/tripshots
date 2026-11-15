"""Recipes: what one reference reel does, kept whole.

A style learned from several reels used to keep only their averages: seven different ideas became one even
montage with a two-second hook. But what makes a reel catching is its particular trick: a nine-second shot of
someone walking away while the lyrics appear one word at a time, then the drop and a burst of half-second
shots; ten flashes under "this is" and then the place's name; one line that stays for the whole reel. So
`learn` also keeps one recipe per reference (style key `recipes`), and `make` follows one of them:

  structure   hold_burst (a long opening shot, then fast cuts), flash_intro (a burst of flashes, then steady
              shots), steady, montage; `turn` is where it changes
  shots       the reference's own shot lengths, laid on this song's beats
  frame       the picture shape (a landscape picture with bars, or full screen)
  text        what the words do: lyrics (the song's own words, one at a time), tease (a line through the
              opening, then the payoff line), title (one line for the whole reel), labels, subtitles, none

`choose` picks the recipe (the reference whose sound you use, else the one that fits the song best), `apply`
sets the style up for it, `slots` gives story.rhythm the shot lengths, `text_overlays` writes the words.
"""
from __future__ import annotations

import math
import re
import statistics

from .config import OUT_FPS

STRUCTURES = ("hold_burst", "flash_intro", "steady", "montage")
TEXT_KINDS = ("lyrics", "tease", "title", "labels", "subtitles", "none")
OPENS = ("person", "wide", "detail", "action")
HOLD_MIN = 2.5  # an opening shot at least this long is a hold: one continuous clip, never a photo


# ------------------------------------------------------------- from a reference
def structure(lens: list[float]) -> tuple[str, float]:
    """(structure, turn in seconds) from a reel's shot lengths."""
    lens = [float(x) for x in lens or [] if x and x > 0]
    if len(lens) < 3:
        return "steady", 0.0
    total = sum(lens)
    if lens[0] >= HOLD_MIN and lens[0] >= 2.5 * statistics.median(lens[1:]) and lens[0] <= 0.75 * total:
        return "hold_burst", round(lens[0], 3)
    t, run = 0.0, 0
    for i, d in enumerate(lens):
        if d <= 0.3:
            run += 1
        else:
            if run >= 3 and t <= 0.4 * total and i < len(lens) - 1 \
                    and statistics.median(lens[i - run:i]) <= 0.6 * statistics.median(lens[i:]):
                return "flash_intro", round(t, 3)
            run = 0
        t += d
    s = sorted(lens)
    p10, p90 = s[int(0.1 * (len(s) - 1))], s[int(round(0.9 * (len(s) - 1)))]
    if statistics.median(lens) >= 1.0 and p90 <= 1.6 * max(p10, 0.01):
        return "steady", 0.0
    return "montage", 0.0


def frame_name(aspect: float | None) -> str:
    """The picture shape of a reference (its content, without baked-in bars) as a frame.aspect value."""
    a = float(aspect or 0)
    if a > 2.1:
        return "2.39:1"
    if a > 1.55:
        return "16:9"
    if a > 1.2:
        return "4:3"
    if a > 0.9:
        return "1:1"
    return "9:16"


def _text(card_text, duration: float) -> dict:
    t = card_text if isinstance(card_text, dict) else {}
    kind = str(t.get("kind") or "none").lower()
    kind = kind if kind in TEXT_KINDS else "none"
    lines = []
    for ln in t.get("lines") or []:
        if not isinstance(ln, dict) or not str(ln.get("text") or "").strip():
            continue
        try:
            a = min(max(float(ln.get("from") or 0.0), 0.0), duration)
            b = min(max(float(ln.get("to") or duration), a), duration)
        except (TypeError, ValueError):
            a, b = 0.0, duration
        role = str(ln.get("role") or "").lower()
        lines.append({"text": " ".join(str(ln["text"]).split())[:120], "from": round(a, 2), "to": round(b, 2),
                      "role": role if role in ("tease", "payoff", "title", "label", "lyric") else "title"})
    if kind != "none" and not lines and kind not in ("labels", "subtitles", "lyrics"):
        kind = "none"

    def one(key, allowed, default):
        v = str(t.get(key) or "").lower()
        return v if v in allowed else default

    cased = "".join(c for ln in lines for c in ln["text"] if c.isalpha() and c.lower() != c.upper())
    return {"kind": kind, "lines": lines[:12], "position": one("position", ("upper", "center", "lower"), "center"),
            "look": one("look", ("caps", "script", "sans", "serif", "mono"), "sans"),
            "upper": len(cased) >= 3 and cased == cased.upper(),   # set in capitals, whatever the typeface
            "size": one("size", ("small", "medium", "large"), "medium"),
            "width": one("width", ("narrow", "normal", "wide"), "normal"),
            "color": " ".join(str(t.get("color") or "white").split())[:24].lower(),
            "per_word": bool(t.get("per_word"))}


def build(measure: dict, card: dict | None, source: str, idx: int, unread: bool = False) -> dict:
    """A recipe from one reference's measurements (learn.measure) and what the AI read off its frames.

    unread: the AI could not look at this reference (yet): the cut is measured, but what its text does is not
    known, which is not the same as a reference without text."""
    unread = bool(unread) and not isinstance(card, dict)
    card = card if isinstance(card, dict) else {}
    lens = [round(float(x), 3) for x in measure.get("shot_lens") or [] if x and x > 0]
    dur = float(measure.get("duration") or sum(lens) or 0.0)
    name, turn = structure(lens)
    from .formats import FORMATS
    fmt = str(card.get("format") or "montage").lower()
    opn = str(card.get("open") or "").lower()
    rec = {"id": f"r{idx}", "source": source, "duration": round(dur, 2),
           "tempo": round(float(measure["tempo"]), 1) if measure.get("tempo") else None,
           "shots": lens, "structure": name, "turn": turn, "frame": frame_name(measure.get("aspect")),
           "format": fmt if fmt in FORMATS else "montage", "open": opn if opn in OPENS else None,
           "people": str(card.get("people") or "").lower() or None, "text": _text(card.get("text"), dur),
           "why": " ".join(str(card.get("why") or "").split())[:240], "unread": True if unread else None}
    if rec["text"]["kind"] == "lyrics" and name != "hold_burst" and not rec["text"]["per_word"]:
        rec["text"]["kind"] = "subtitles"  # lyric lines under an even edit are subtitles
    ex = card.get("_exact")
    if isinstance(ex, dict):
        rec["text"].update(exact_text(ex))
    return {k: v for k, v in rec.items() if v is not None}


FONT_MIN = 0.4  # how alike the matched face must be to the reference's letters to be used (reftext.likeness)


def exact_text(ex: dict) -> dict:
    """The reference's own words as reftext read them, for the recipe: `exact` [{text, from, to, x, y, size,
    color}] (x, y: the middle of the words in the picture, 0..1; size: line height / picture height) and
    `font`, the library face most like its lettering. Text that was only partly readable is left out: words
    on screen are copied exactly or not at all."""
    evs = []
    for e in ex.get("events") or []:
        if e.get("partial") or not str(e.get("text") or "").strip():
            continue
        b = e.get("box") or [0, 0, 1, 1]
        evs.append({"text": str(e["text"]).strip(), "from": float(e["t0"]), "to": float(e["t1"]),
                    "x": round((b[0] + b[2]) / 2, 3), "y": round((b[1] + b[3]) / 2, 3),
                    "size": round(float(e.get("size") or 0.04), 4), "lines": int(e.get("lines") or 1),
                    "color": e.get("color")})
    evs.sort(key=lambda e: e["from"])
    one: list[dict] = []
    for e in evs:  # one line at a time: the same words read twice are one; a new line ends the one before
        if one and e["from"] < one[-1]["to"]:
            if e["text"] == one[-1]["text"] or e["text"] in one[-1]["text"]:
                one[-1]["to"] = max(one[-1]["to"], e["to"])
                continue
            one[-1]["to"] = e["from"]
        one.append(e)
    evs = [e for e in one if e["to"] - e["from"] >= 0.15]
    f = ex.get("font") or {}
    out = {"exact": evs}
    if f.get("font") and float(f.get("score") or 0) >= FONT_MIN:
        out["font"] = f["font"]
    return out


def describe(r: dict) -> str:
    t = r.get("text") or {}
    shape = {"hold_burst": f"holds its first shot {r.get('turn', 0):.1f}s, then fast cuts",
             "flash_intro": f"flashes for {r.get('turn', 0):.1f}s, then steady shots",
             "steady": "even shots", "montage": "a montage of uneven shots"}.get(r.get("structure"), "montage")
    words = {"lyrics": "the song's words one at a time", "tease": "a tease line, then the payoff line",
             "title": "one line for the whole reel", "labels": "a title per shot", "subtitles": "subtitles",
             "none": "no text"}.get(t.get("kind"), "no text")
    if r.get("unread"):
        words = "text not read yet"
    return f"{r.get('duration', 0):.0f}s, {shape}, {r.get('frame', '9:16')}, {words}"


# --------------------------------------------------------------------- choosing
def _same_source(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    from .fetch import canonical, is_url
    return (canonical(a) if is_url(a) else str(a)) == (canonical(b) if is_url(b) else str(b))


def tempo_scale(ref_tempo: float, tempo: float) -> float:
    """Seconds here per reference second when shots keep their length in beats (half and double time are
    folded, so a shot stays about as long as it was)."""
    r = float(ref_tempo) / max(float(tempo), 1e-6)
    while r > 1.42:
        r /= 2
    while r < 0.71:
        r *= 2
    return r


def length_for(recipe: dict, music: dict | None) -> float:
    """How long the reel runs with this recipe on this music."""
    dur = float(recipe.get("duration") or sum(recipe.get("shots") or [0]))
    if recipe.get("_own") or not music or not recipe.get("tempo") or not music.get("tempo"):
        return dur
    return dur * tempo_scale(recipe["tempo"], music["tempo"])


def choose(style: dict, music_url: str | None = None, music: dict | None = None, words: dict | None = None,
           want="auto") -> dict | None:
    """The recipe for this reel, or None for the style's averaged rhythm.

    want: auto | off | a number (1 = the first reference) | an id (r3)."""
    recs = [r for r in style.get("recipes") or [] if isinstance(r, dict) and r.get("shots")]
    w = str("off" if want is False or want is None else want).strip().lower()
    if not recs or not music or w in ("off", "none", "no", "false"):
        return None
    if w not in ("auto", "on", "true", ""):
        m = re.fullmatch(r"r?(\d+)", w)
        pick = next((r for r in recs if str(r.get("id")) == w), None)
        if pick is None and m and 1 <= int(m.group(1)) <= len(recs):
            pick = recs[int(m.group(1)) - 1]
        if pick is None:
            from .util import ReelError
            raise ReelError(f"no recipe '{want}' in this style (it has {', '.join(str(r.get('id')) for r in recs)})")
        return {**pick, "_own": _same_source(pick.get("source"), music_url)}
    own = next((r for r in recs if _same_source(r.get("source"), music_url)), None)
    if own:
        return {**own, "_own": True}
    has_words = bool(words and words.get("lines"))
    avail = float(music.get("duration") or 0.0)

    def misfit(r: dict) -> float:
        m = 0.0
        if r.get("tempo") and music.get("tempo"):
            x = float(music["tempo"]) / float(r["tempo"])
            m += abs(math.log2(x) - round(math.log2(x)))        # same tempo, or half/double time
        need = length_for(r, music)
        if avail and need > avail:
            m += min(1.0, (need - avail) / need) * 2
        kind = (r.get("text") or {}).get("kind")
        if kind in ("lyrics", "subtitles") and not has_words:
            m += 0.6                                            # its text needs words this song doesn't have
        if kind == "lyrics" and has_words:
            m -= 0.3
        if r.get("unread"):
            m += 0.5                                            # only its cut is known: a read one fits better
        return m

    return dict(min(recs, key=misfit))


def apply(style: dict, recipe: dict, music: dict | None = None, keep: tuple = ()) -> None:
    """Set the style up for one recipe (length, picture shape, format, opening shot, text mode).
    `keep` names what the user asked for on the command line (format, captions): those stay."""
    dur = length_for(recipe, music)
    d = style.setdefault("duration", {})
    d["target"] = round(dur, 2)
    d["min"] = min(float(d.get("min", dur)), dur)
    d["max"] = max(float(d.get("max", dur)), dur)
    if recipe.get("frame"):
        style["frame"] = {**(style.get("frame") or {}), "aspect": recipe["frame"]}
    if not recipe.get("panels"):
        # a style's split screens are an average over all its examples; one example's cut has none of its own
        style["panels"] = {**(style.get("panels") or {}), "use": 0.0}
    st = style.setdefault("story", {})
    if recipe.get("format") and "format" not in keep:
        st["format"] = recipe["format"]
    if recipe.get("open"):
        style.setdefault("attention", {}).setdefault("open", {})["shot"] = recipe["open"]
    kind = (recipe.get("text") or {}).get("kind", "none")
    text = style.setdefault("text", {})
    if kind in ("none", "lyrics", "subtitles", "labels"):
        text.setdefault("hook", {})["mode"] = "off"   # the reference has no hook line: don't invent one
        st["hook_text"] = "off"
    elif str(text.setdefault("hook", {}).get("mode", "off")).lower() in ("off", "false"):
        text["hook"]["mode"] = "ai"                   # a tease or a title: the copywriter writes ours
    if kind == "subtitles" and "captions" not in keep and str(st.get("captions", "auto")) == "auto":
        st["captions"] = "original"
    # the recipe's own words are the reel's words (a labels recipe names each shot itself: label_overlays)
    text.setdefault("location", {})["mode"] = "off"
    text.setdefault("labels", {})["mode"] = "off"
    # a reel that turns (a hold then a burst, flashes then the view) ends on its last shot: no dissolve back
    style["loop"] = bool(style.get("loop")) and recipe.get("structure") not in ("hold_burst", "flash_intro")
    if "loop" not in keep:
        st["loop"] = style["loop"]
    if recipe.get("_own") and (music or {}).get("path"):
        recipe["_cuts"] = own_cuts(recipe, music["path"])
        style["_music_exact"] = True   # the sound from its first sample, as the reference has it
    style["_recipe"] = recipe


# ----------------------------------------------------------------------- rhythm
def own_cuts(recipe: dict, sound) -> list[float]:
    """The reference's cut times (seconds into its sound) for a reel made on that same sound. Shot detection
    is a frame or two off, so each cut moves onto the hit it was plainly made on when one is that close;
    otherwise it stays where the reference had it."""
    cuts, t = [], 0.0
    for d in recipe.get("shots") or []:
        t += float(d)
        cuts.append(round(t, 4))
    if len(cuts) < 2:
        return cuts
    try:
        from pathlib import Path

        import numpy as np

        from .music import _refine, load_audio
        y, sr = load_audio(Path(sound))
        fixed = _refine(y, sr, np.array(cuts[:-1]), win=0.085)
        return [round(float(c), 4) for c in fixed] + cuts[-1:]
    except Exception:
        return cuts


def slots(recipe: dict, grid: dict, clock, limit: float | None = None) -> list[tuple[float, str]]:
    """The recipe's shots on this song: [(beats, role)] for story._to_segments.

    With the reference's own sound every cut sits exactly where it sat in the reference (`own_cuts`: its
    editor cut by ear, on hits a beat tracker doesn't always find, so the beat grid is not allowed to move
    them); with another song each shot keeps its length in beats and the turn (the end of the hold, the end
    of the flashes) lands on a whole beat, on the drop when there is one nearby."""
    lens = [float(x) for x in recipe["shots"]]
    bl = float(grid["beat_len"])
    cuts, t = [], 0.0
    for d in lens:
        t += d
        cuts.append(t)
    ref_bl = 60.0 / float(recipe["tempo"]) if recipe.get("tempo") else bl
    exact = bool(recipe.get("_own"))
    if exact:
        off = float(grid.get("music_start") or 0.0)
        if len(recipe.get("_cuts") or []) == len(cuts):
            cuts = [float(c) for c in recipe["_cuts"]]
        xs = [clock.x_at(max(0.0, c - off)) for c in cuts]
    else:
        k = tempo_scale(60.0 / ref_bl, 60.0 / bl)
        xs = [c * k / bl for c in cuts]
        ref_bl = bl / k
    q = 0.5 if statistics.median(lens) / ref_bl >= 0.75 else 0.25
    step = q * max(1, math.ceil(0.2 / (bl * q) - 1e-6))       # no shot under 0.2 s
    if exact:
        step = 0.19 / bl
    name, turn = recipe.get("structure"), float(recipe.get("turn") or 0.0)
    k_turn = None
    if name in ("hold_burst", "flash_intro") and turn > 0:
        k_turn = min(range(len(cuts)), key=lambda i: abs(cuts[i] - turn))
    out, prev, x_turn, shift = [], 0.0, None, 0.0
    for i, x in enumerate(xs):
        if exact:
            if i == k_turn:
                x_turn = x
        elif i == k_turn:
            was = x
            x = float(round(x))
            near = [clock.x_at(dt) for dt in grid.get("drops") or []]
            near = [n for n in near if abs(n - x) <= (0.6 if recipe.get("_own") else 2.0)]
            if near:
                x = float(round(min(near, key=lambda n: abs(n - x))))
            x = max(x, 1.0)
            if not out:
                prev = 0.0
            elif x < prev + step:      # the flashes ran past the turn: pull them back
                out = [o for o in out if o <= x - step]
                prev = out[-1] if out else 0.0
            x_turn, shift = x, x - was     # the shots after the turn keep their lengths: they move with it
        else:
            x = round((x + shift) / q) * q
        if x < prev + step:
            if i == len(xs) - 1 and out:
                continue
            x = prev + step
        out.append(x)
        prev = x
    if limit is not None and exact:     # the reference's own end, unless the sound runs out first
        kept = [x for x in out if x <= limit + 1e-6]
        if len(kept) < len(out):
            if kept and limit - kept[-1] < step:
                kept[-1] = float(limit)
            else:
                kept.append(float(limit))
        out = kept
    elif limit is not None:
        out = [x for x in out if x < limit - step + 1e-6]
        if not out or limit - out[-1] > 1e-6:
            if len(out) < len(xs):
                out.append(float(limit))
    if not out:
        return []
    starts = [0.0] + out[:-1]
    n = len(out)
    roles = ["build"] * n
    if name == "hold_burst" and n >= 2:
        roles = ["release"] * n
        roles[1] = "peak"
    elif name == "flash_intro" and x_turn is not None:
        k_peak = next((i for i, s in enumerate(starts) if s >= x_turn - 1e-6), None)
        if k_peak is None:
            k_peak = max(range(n), key=lambda i: out[i] - starts[i])
        for i in range(n):
            roles[i] = "build" if i < k_peak else "release"
        roles[k_peak] = "peak"
    elif n >= 3:
        total = out[-1]
        drops = [clock.x_at(dt) for dt in grid.get("drops") or []]
        mid = [dx for dx in drops if 0.3 * total <= dx <= 0.75 * total]
        at = mid[0] if mid else 0.55 * total
        k_peak = min(range(1, n - 1), key=lambda i: abs(starts[i] - at))
        for i in range(n):
            roles[i] = "build" if i < k_peak else "release"
        roles[k_peak] = "peak"
        if k_peak > 1 and n >= 5:
            roles[1] = "setup"
    roles[0] = "hook"
    if n >= 3 and roles[-1] != "peak":
        roles[-1] = "ending"
    return [(round(out[i] - starts[i], 4), roles[i]) for i in range(n)]


def turn_time(plan: dict) -> float | None:
    """Where the plan changes gear (the end of the hold, the end of the flashes), in seconds."""
    r = plan.get("recipe") or {}
    if r.get("structure") not in ("hold_burst", "flash_intro"):
        return None
    segs = plan.get("segments") or []
    if r.get("structure") == "hold_burst" and len(segs) > 1:
        return float(segs[1]["out_start"])
    return next((float(s["out_start"]) for s in segs if s.get("role") == "peak"), None)


AUDITION_PROMPT = """You are casting the OPENING SHOT of a short travel reel. It is held for {need:.0f} seconds without a cut{words}, so it decides whether people stop scrolling and whether they stay.

Each row of the image is one candidate clip, labelled with a letter. Left to right are four moments across the {need:.0f} seconds it would be on screen{crop}.
{like}
Pick the row that:
- stops a scroller on its very FIRST tile (beautiful light and colour, a clear subject, depth);
- keeps changing through to the last tile (the camera travels or reveals something, a person moves), and never turns dull, shaky, tilted, blown out or empty;
- leaves the middle of the picture readable{words2}.
A lone person small in a big landscape beats an empty view; a close, awkward or cluttered frame loses.

Reply with JSON only: {{"pick": "<letter>", "second": "<letter>", "why": "<one short sentence>"}}"""


def audition(cands: list[tuple[dict, float]], need: float, work, backend, recipe: dict | None = None,
             spans: dict | None = None, aspect=None, top: int = 5) -> list[tuple[dict, float]]:
    """Let the AI see the best opening-hold candidates over their whole length and pick: the numbers
    (story.hold_score) only know each chunk's verdict, not how the shot looks at second 0 and second 9.
    Returns the candidates with the pick (and its runner-up) first; unchanged when the AI can't be asked.
    Cached in the work folder per set of candidates."""
    import hashlib
    from pathlib import Path

    from . import ai as ai_mod
    from .util import ffmpeg_base, log, read_json, run, write_json
    if not backend or len(cands) < 2:
        return cands
    ar = None  # the picture's width / height when the reel is a wide picture with bars
    try:
        if isinstance(aspect, (int, float)):
            ar = float(aspect)
        elif aspect and ":" in str(aspect):
            ar = float(str(aspect).split(":")[0]) / float(str(aspect).split(":")[1])
    except (ValueError, ZeroDivisionError):
        ar = None
    head = cands[:top]
    letters = "ABCDEFGH"[:len(head)]
    work = Path(work)
    key = hashlib.sha1(("|".join(f"{s['id']}@{s['t0']:.2f}" for s, _ in head) + f"|{need:.2f}|{ar}|"
                        + str((recipe or {}).get("why", ""))).encode()).hexdigest()[:12]
    cache = work / f"hold_audition_{key}.json"
    ans = None
    if cache.exists():
        try:
            ans = read_json(cache)
        except Exception:
            ans = None
    if not isinstance(ans, dict):
        from PIL import Image, ImageDraw
        tall = not ar or ar < 1.0
        tw, th = (200, 356) if tall else (384, int(round(384 / ar)))
        tmp = work / f"hold_audition_{key}"
        tmp.mkdir(parents=True, exist_ok=True)
        sheet = Image.new("RGB", (40 + 4 * (tw + 6), len(head) * (th + 6) + 6), (18, 18, 18))
        draw = ImageDraw.Draw(sheet)
        for r, (sh, _) in enumerate(head):
            room = ((spans or {}).get(sh["id"], (sh["t0"], sh["t1"]))[1] - sh["t0"]) if spans else need
            span = min(need, max(room, 0.5))
            cx = float((sh.get("ai") or {}).get("subject_x") or 0.5)
            for c, f in enumerate((0.02, 0.34, 0.67, 0.97)):
                out = tmp / f"{letters[r]}{c}.jpg"
                run(ffmpeg_base() + ["-ss", f"{sh['t0'] + span * f:.3f}", "-i", str(sh["src"]), "-frames:v", "1",
                                     "-vf", "scale=-2:360", "-q:v", "4", str(out)], check=False)
                if not out.exists():
                    continue
                im = Image.open(out).convert("RGB")
                want = tw / th
                if im.width / im.height > want:   # the part of a wide frame the reel would show
                    w = int(round(im.height * want))
                    x0 = int(min(max(cx * im.width - w / 2, 0), im.width - w))
                    im = im.crop((x0, 0, x0 + w, im.height))
                else:
                    h = int(round(im.width / want))
                    y0 = (im.height - h) // 2
                    im = im.crop((0, y0, im.width, y0 + h))
                sheet.paste(im.resize((tw, th)), (40 + c * (tw + 6), 6 + r * (th + 6)))
            draw.text((12, 6 + r * (th + 6) + th // 2 - 8), letters[r], fill=(255, 220, 60))
        path = work / f"hold_audition_{key}.jpg"
        sheet.save(path, quality=88)
        txt = (recipe or {}).get("text") or {}
        sung = txt.get("kind") in ("lyrics", "tease", "title")
        like = (f"\nThe reel this one is modelled on opens like this: {recipe['why']}\nChoose the clip that gives "
                "the same feeling with this footage (the place will differ).\n") if (recipe or {}).get("why") else ""
        prompt = AUDITION_PROMPT.format(
            need=need, like=like,
            words=" while words appear over it" if sung else "",
            words2=": words are drawn over it" if sung else "",
            crop="" if tall else ", shown as the widescreen picture the reel uses")
        try:
            ans = ai_mod.extract_json(backend.ask(prompt, [path], max_tokens=300))
        except Exception as e:
            log(f"  opening audition skipped ({str(e)[:80]})")
            return cands
        if not isinstance(ans, dict):
            return cands
        write_json(cache, ans)
    order = [letters.find(str(ans.get(k) or "").strip().upper()[:1] or "?") for k in ("pick", "second")]
    order = [i for n, i in enumerate(order) if i >= 0 and i not in order[:n]]
    if not order:
        return cands
    log(f"opening audition: {head[order[0]][0]['id']}" + (f" ({str(ans.get('why'))[:110]})" if ans.get("why") else ""))
    lead = [head[i] for i in order]
    return lead + [c for c in cands if all(c[0] is not x[0] for x in lead)]


def brief(recipe: dict) -> dict:
    """What the plan keeps of its recipe (plan key `recipe`)."""
    return {"id": recipe.get("id"), "source": recipe.get("source"), "structure": recipe.get("structure"),
            "hold": recipe.get("turn") if recipe.get("structure") == "hold_burst" else None,
            "frame": recipe.get("frame"), "text": (recipe.get("text") or {}).get("kind", "none"),
            "lens": [round(float(x), 2) for x in recipe.get("shots") or []][:60],
            "own_sound": bool(recipe.get("_own")), "why": recipe.get("why") or ""}


# ------------------------------------------------------------------------- text
COLORS = {"white": (255, 255, 255), "yellow": (255, 222, 60), "cream": (245, 236, 205), "beige": (236, 222, 192),
          "gold": (240, 196, 80), "orange": (255, 160, 64), "red": (232, 64, 56), "pink": (255, 150, 190),
          "blue": (110, 170, 255), "green": (140, 220, 140), "teal": (90, 210, 200), "purple": (190, 150, 255)}
FONTS = {"caps": "anton", "script": "caveat", "sans": "montserrat-bold", "serif": "playfair", "mono": "spacemono"}
NARROW = {"sans": "bebas", "caps": "anton", "serif": "dmserif"}   # tall, tight letters
SIZES = {"small": 56, "medium": 86, "large": 124}


def color_of(name: str | None) -> tuple | None:
    """RGB for a colour the AI named ("pale yellow", "#ffe98a"). Dark colours give None: black type suits
    the reference's bright picture, and nobody knows yet what yours will be."""
    s = str(name or "").strip().lower()
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    rgb = tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else \
        next((v for k, v in COLORS.items() if k in s), None)
    if rgb is None:
        return None
    if any(w in s for w in ("pale", "light", "soft", "pastel")):
        rgb = tuple(int(c + (255 - c) * 0.45) for c in rgb)
    if 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] < 110:
        return None
    return rgb if rgb != (255, 255, 255) else None


# "multicolor", "rainbow", "postcard letters": every letter its own colour, like a vintage postcard
POSTCARD = [(238, 92, 66), (255, 176, 59), (255, 226, 110), (96, 200, 190), (245, 236, 205), (240, 130, 160)]


def text_style(recipe: dict, per_word: bool = False, label: bool = False) -> dict:
    """The per-overlay `style` (render.TextTrack) for the reference's kind of lettering.
    label: a name per shot (text kind labels): it changes on the cut, stays where it is from shot to shot
    and is the biggest thing on screen."""
    t = recipe.get("text") or {}
    look = t.get("look", "sans")
    px = SIZES.get(t.get("size"), SIZES["medium"]) * (1.3 if look == "script" else 1.0)
    face = NARROW.get(look) if t.get("width") == "narrow" else None
    face = t.get("font") or face   # the face matched to the reference's own letters (reftext)
    ex = [e for e in t.get("exact") or [] if e.get("size")]
    if ex:  # the reference's own type size: line height in the picture -> font size in ours
        import statistics
        from .config import CANVAS
        sizes = [e["size"] for e in ex]
        h = max(sizes) if t.get("kind") == "title" else statistics.median(sizes)  # a title is its biggest line
        # a phone shows a reel by its width: the line's height as a share of the reference picture's WIDTH, set
        # on ours (a 4:3 reference's lyrics would come out smaller in a 16:9 frame measured by height).
        # (the renderer scales lettering by CANVAS.text: undo it, this is already the size on our canvas)
        try:
            a, b = (float(x) for x in str(recipe.get("frame") or "9:16").split(":"))
            ref_ar = a / b
        except ValueError:
            ref_ar = 9 / 16
        px = max(40.0, min(220.0, h / ref_ar * CANVAS.w * 0.92)) / (1.3 if per_word else 1.0) / (CANVAS.text or 1.0)
        if t.get("kind") in ("title", "tease"):  # words we write ourselves: never smaller than reads at a glance
            px = max(px, SIZES["small"] * 1.1)
    st = {"font": face or FONTS.get(look, FONTS["sans"]), "size": int(round(px * (1.3 if per_word else 1.0))),
          "uppercase": look == "caps" or bool(t.get("upper")), "position": t.get("position", "center"),
          "anim": "cut" if per_word else "fade", "line_gap": 1.05}
    col = color_of(t.get("color"))
    multi = any(w in str(t.get("color") or "").lower() for w in ("multi", "rainbow", "colorful", "colourful"))
    if col:
        st["color"] = list(col)
    elif multi and label:  # postcard letters: the picture shows through them
        st.update({"fill": "picture", "font": t.get("font") or "anton", "uppercase": True,
                   "lead_color": [250, 196, 58]})
    elif multi:
        st["colors"] = [list(c) for c in POSTCARD]
    if per_word:
        st["exit"] = 0.04
    if label:
        st.update({"size": int(round(max(st["size"], SIZES["medium"]) * 1.4)), "anim": "cut", "exit": 0.05,
                   "fixed": True, "fit": 0.8,
                   "lead_font": "gf:Yellowtail:400" if st.get("fill") == "picture" else FONTS["script"]})
        st["lead_size"] = int(round(st["size"] * 0.6))  # the line above the name reads on a phone too
    return st


def _frames(t: float) -> float:
    return round(round(t * OUT_FPS) / OUT_FPS, 4)


def lyric_words(lines: list[dict], until: float, per_word: bool = True) -> list[dict]:
    """[{text, start, duration}] for the sung lines before `until`: one entry per word (each shown until the
    next), or one per line. Word times are spread over the line by word length; a line that trails off
    doesn't slow its words down (they keep the song's usual pace)."""
    lines = [ln for ln in lines or [] if str(ln.get("text") or "").strip() and float(ln["start"]) < until - 0.3]
    if not lines:
        return []
    paces = [(float(ln["end"]) - float(ln["start"])) / max(1, len(str(ln["text"]).split())) for ln in lines]
    pace = statistics.median(paces)
    out = []
    for i, ln in enumerate(lines):
        a = max(0.0, float(ln["start"]))
        nxt = float(lines[i + 1]["start"]) if i + 1 < len(lines) else until
        end = min(max(float(ln["end"]), a + 0.4), nxt, until)
        ws = [w.strip(",.;:!?\"“”…") for w in str(ln["text"]).split()]
        ws = [w for w in ws if any(ch.isalnum() for ch in w)]  # a "…" or a dash alone is no word to show
        if not ws:
            continue
        if not per_word:
            out.append({"text": " ".join(ws), "start": _frames(a), "duration": _frames(end - a)})
            continue
        sung = min(end - a, len(ws) * pace * 1.15)
        wts = [len(w) + 2 for w in ws]
        tot = float(sum(wts))
        t = a
        for k, w in enumerate(ws):
            t2 = a + sung * sum(wts[:k + 1]) / tot
            stop = t2 if k < len(ws) - 1 else min(end, max(t2, t + 0.5))
            if _frames(stop) - _frames(t) >= 3 / OUT_FPS:
                out.append({"text": w, "start": _frames(t), "duration": round(_frames(stop) - _frames(t), 4)})
            t = t2
    return out


def text_overlays(plan: dict, recipe: dict, words_rel: dict | None, copy: dict | None,
                  hook: str | None = None, facts: list[dict] | None = None) -> list[dict]:
    """The recipe's words as plan overlays. No new overlay types: sung words are `caption` overlays, the
    tease is the `hook` held through the opening, the payoff line a `label`, a name per shot `label`s; each
    carries a `style` with the reference's lettering, and `recipe` says which part it plays.
    facts: per segment what is known about where it was filmed (pipeline._seg_facts), for a labels recipe."""
    t = recipe.get("text") or {}
    kind = t.get("kind", "none")
    total = float(plan["duration"])
    turn = turn_time(plan)
    copy = copy or {}
    out: list[dict] = []
    if kind in ("lyrics", "subtitles"):
        # sung or spoken words go on screen only as the reference shows them on its own sound: copied, never
        # transcribed (a transcript of a song is too often wrong, and wrong lyrics ruin a reel)
        out = exact_overlays(plan, recipe) if recipe.get("_own") else []
        if out or kind == "subtitles" or not recipe.get("_own") or not (hook or copy.get("hook")):
            return out
        kind = "tease"                      # its own sound, no words to copy: hold a line instead
    if kind == "labels":
        return label_overlays(plan, recipe, label_names(facts or [{} for _ in plan["segments"]],
                                                        copy.get("labels")))
    if kind not in ("tease", "title"):
        return out
    st = text_style(recipe)
    k = total / float(recipe.get("duration") or total)   # the reference's clock on ours
    cuts = [float(s["out_start"]) for s in plan["segments"]]
    ref = [ln for ln in t.get("lines") or [] if ln.get("to") is not None]

    def on_cut(x: float) -> float:      # words change with the picture when a cut is close
        near = min(cuts, key=lambda c: abs(c - x), default=x)
        return near if abs(near - x) <= 0.35 else _frames(x)

    def span(ln: dict | None) -> tuple[float, float] | None:
        """When the line modelled on reference line `ln` is on screen (None = no such line to go by)."""
        if not ln:
            return None
        a, b = float(ln["from"]) * k, float(ln["to"]) * k
        if b - a >= 0.85 * total:       # there from the first frame to the last
            return 0.1, total - 0.1
        a = max(0.1, on_cut(a) if a > 0.3 else 0.1)
        b = min(total - 0.1, on_cut(b))
        if b - a < 1.4:                 # long enough to read
            b = min(total - 0.1, a + 1.4)
        return a, b

    if kind == "title":
        line = hook or copy.get("title") or copy.get("tease") or copy.get("hook")
        if not line:
            return out
        a, b = span(next((ln for ln in ref if ln.get("role") == "title"), None)) or (0.1, total - 0.1)
        out.append({"type": "hook", "text": line, "start": round(a, 3), "duration": round(b - a, 3),
                    "style": held_position(plan, a, b, st), "recipe": "title"})
        return out
    line = hook or copy.get("tease") or copy.get("hook")
    if not line:
        return out
    pay = copy.get("payoff")
    pay = [p for p in (pay if isinstance(pay, list) else [pay]) if p]
    ref_pay = sorted((ln for ln in ref if ln.get("role") == "payoff"), key=lambda ln: float(ln["from"]))
    first = span(next((ln for ln in ref if ln.get("role") == "tease"), None))
    change = None                       # when the answer takes the tease's place
    if pay and ref_pay:
        change = max(0.1, on_cut(float(ref_pay[0]["from"]) * k))
    if turn and turn < total - 1.0 and (change is None or not 0.8 <= change <= total - 1.0):
        change = turn
    if change is not None and 0.8 <= change <= total - 1.0:
        out.append({"type": "hook", "text": line, "start": 0.1, "duration": round(change - 0.1, 3),
                    "style": held_position(plan, 0.1, change, st), "recipe": "tease"})
        if len(pay) > 1 and len(ref_pay) == len(pay):   # a run of lines, each for as long as the reference's
            marks = [change] + [on_cut(float(ln["from"]) * k) for ln in ref_pay[1:]] + [total - 0.1]
            marks = [max(marks[0], min(m, total - 0.1)) for m in marks]
        else:
            pay, marks = [" ".join(pay)] if pay else [], [change, total - 0.1]
        for i, p in enumerate(pay):
            if marks[i + 1] - marks[i] >= 0.6:
                out.append({"type": "label", "text": p, "start": round(marks[i], 3),
                            "duration": round(marks[i + 1] - marks[i] - (0.03 if i + 1 < len(pay) else 0.0), 3),
                            "style": held_position(plan, marks[i], marks[i + 1], st), "recipe": "payoff"})
    else:   # no turn and no answer: the line is there as long as the reference's is
        a, b = first or (0.1, total - 0.1)
        b = a + max(b - a, 2.0) if a + 2.0 <= total - 0.1 else b
        out.append({"type": "hook", "text": trail_off(line) if first else line, "start": round(a, 3), "duration": round(b - a, 3),
                    "style": held_position(plan, a, b, st), "recipe": "tease" if first else "title"})
    return out


DANGLING = {"and", "the", "a", "an", "of", "to", "with", "for", "in", "on", "at", "or", "but", "my", "our", "your",
            "is", "was", "like", "into", "from", "just"}


def trail_off(line: str) -> str:
    """A tease left unanswered ("Just us, the rig and") trails off with three dots, so it reads as meant."""
    t = line.rstrip()
    words = t.split()
    if words and t[-1].isalnum() and words[-1].lower().strip(",") in DANGLING:
        return t.rstrip(",") + "..."
    return line


def exact_overlays(plan: dict, recipe: dict) -> list[dict]:
    """The reference's own words at their own times (it is the same sound, from 0:00), each where the
    reference has it, in its lettering, size and colour."""
    t = recipe.get("text") or {}
    if not t.get("font"):  # lettering we can't match (hand-drawn, decorative): no words rather than wrong-looking ones
        return []
    total = float(plan["duration"])
    off = float((plan.get("music") or {}).get("start") or 0.0)
    out = []
    lines: list[dict] = []
    for e in sorted(t.get("exact") or [], key=lambda e: e["from"]):
        if lines and e["text"] == lines[-1]["text"] and e["from"] - lines[-1]["to"] < 1.0:
            lines[-1] = {**lines[-1], "to": e["to"]}  # the same words, lost for a moment against a bright shot
        else:
            lines.append(dict(e))
    for e in lines:
        a, b = _frames(max(0.0, e["from"] - off)), _frames(min(total - 0.05, e["to"] - off))
        if b - a < 0.15:
            continue
        one = len(e["text"].split()) <= 2
        st = {**text_style(recipe, False), "anim": "cut" if one else "fade", "exit": 0.04 if one else 0.2,
              "y": e["y"], "x": e["x"]}
        # (one colour for all of its lines: the one the AI named reading the reference; a colour measured per
        # line is thrown off by what is behind small type)
        st["legible"] = True
        out.append({"type": "caption", "text": e["text"], "start": a, "duration": round(b - a, 4), "style": st,
                    "recipe": "lyric"})
    return out


# ----------------------------------------------------------------------- labels
def subtitled(recipe: dict, caps: list[dict]) -> list[dict]:
    """Transcribed subtitles in a recipe reel: none. The words a reference shows are copied from it, exactly,
    where and when it shows them (exact_overlays); a transcript of its sound would put a second, often wrong,
    version on screen (misspelt dialogue, misheard lyrics)."""
    return []


def label_lead(recipe: dict) -> str:
    """The words every label of the reference starts with ("Greetings From..." before each state), or ""."""
    rows = [str(ln["text"]).split() for ln in (recipe.get("text") or {}).get("lines") or []
            if ln.get("role") == "label" and str(ln.get("text") or "").strip()]
    if len(rows) < 2:
        return ""
    n = 0
    while all(len(r) > n + 1 for r in rows) and len({r[n].lower() for r in rows}) == 1:
        n += 1
    return " ".join(rows[0][:n])


def _name_words(v) -> set:
    return {w for w in re.sub(r"[^\w ]+", " ", str(v or "").lower()).split() if len(w) > 2
            and w not in ("the", "and", "national", "park", "state", "forest", "monument", "area", "county")}


def label_names(facts: list[dict], proposed: list | None = None) -> list[str]:
    """One name per shot for a labels recipe. `facts`: per shot what is known about where it was filmed
    {landmark, place, region}. `proposed`: the copywriter's names. A proposed place name that isn't in its
    shot's facts gives way to the region (a label never names somewhere the footage wasn't); labels that
    aren't place names at all (most don't match anything) are left as written. One kind of name through the
    reel: when a third of the shots can only be named by their region, every shot is."""
    from .ai import clean_line
    prop = [clean_line(str(p or ""))[:30] for p in (proposed or [])][:len(facts)]
    prop += [""] * (len(facts) - len(prop))

    def known(p: str, f: dict) -> bool:
        return bool(_name_words(p) & set().union(*(_name_words(v) for v in f.values() if isinstance(v, str))))
    judged = [(p, f) for p, f in zip(prop, facts) if p and f]
    places = bool(judged) and sum(known(p, f) for p, f in judged) >= 0.5 * len(judged)
    out = []
    for p, f in zip(prop, facts):
        fall = str(f.get("region") or "") if f else ""
        if not proposed:
            out.append(fall)
        elif places and p and (not f or not known(p, f)):
            out.append(fall)
        else:
            out.append(p)
    regs = [str(f.get("region") or "") if f else "" for f in facts]
    named = [k for k, o in enumerate(out) if o]
    by_region = [k for k in named if regs[k] and out[k].lower() == regs[k].lower()]
    runs = sum(1 for k in named if regs[k] and (k == named[0] or regs[k] != regs[named[named.index(k) - 1]]))
    if (places and len(by_region) * 3 >= len(named) and len(by_region) < len(named)
            and runs >= max(3, len(named) / 3)):  # (a trip inside one region keeps its place names)
        out = [regs[k] or o for k, o in enumerate(out)]
    return out


def _row_cost(segs: list[dict], names: list[str], mid: float, half: float) -> float:
    """How much of our shots' subjects lies behind lettering whose middle is at `mid` (0..1 down the frame,
    `half` its half height), weighed by how long each shot is up. A person behind the letters counts double; a
    subject that fills the view counts for nothing (there is nowhere to go), but a head does wherever it is:
    words across the back of somebody's head are the one thing everybody sees."""
    def over(a: float, b: float) -> float:
        return max(0.0, min(mid + half, b) - max(mid - half, a)) / (2 * half)
    cost = 0.0
    for k, s in enumerate(segs):
        subj = s.get("subject_out") or {}
        if s.get("panel") or not (names[k] if k < len(names) else "") or "y0" not in subj or "y1" not in subj:
            continue
        y0, y1 = float(subj["y0"]), float(subj["y1"])
        if y1 - y0 <= 0.6:
            cost += over(y0, y1) * float(s["dur"]) * (2.0 if s.get("people") else 1.0)
        if s.get("people") and y1 - y0 > 0.3:   # (a small figure is all inside its box, counted above)
            cost += 4.0 * over(y0, y0 + max(0.05, 0.18 * (y1 - y0))) * float(s["dur"])
    return cost


def label_position(segs: list[dict], names: list[str], preferred: str = "center") -> str:
    """Which third of the frame a name that stays put from shot to shot sits in: the reference's, unless
    there it lies on the subject of most of our shots and another third is clearly freer (_row_cost)."""
    from . import typo
    from .config import CANVAS
    half = 0.075 if CANVAS.h > CANVAS.w else 0.13  # the lettering is taller against a horizontal frame
    bands = [b for b in ("upper", "center", "lower") if b in typo.BANDS]
    if preferred not in bands:
        return preferred
    cost = {b: _row_cost(segs, names, sum(typo.BANDS[b]) / 2 / CANVAS.h, half) for b in bands}
    best = min(cost, key=lambda b: (cost[b], b != preferred))
    return best if cost[best] < 0.6 * cost[preferred] else preferred


def free_row(segs: list[dict], names: list[str], band: str) -> tuple[float | None, float]:
    """(height, what it covers there): the height inside its third (the line's middle, 0..1 down the frame) at
    which a line held across these shots covers clearly less than in the middle of that third: just above or
    below a head, say. None = the middle is as good as anywhere."""
    from . import typo
    from .config import CANVAS
    half = 0.04 if CANVAS.h > CANVAS.w else 0.07
    lo = max(typo.BANDS[band][0], typo.SAFE["top"]) / CANVAS.h + half
    hi = min(typo.BANDS[band][1], typo.SAFE["bottom"]) / CANVAS.h - half
    mid = sum(typo.BANDS[band]) / 2 / CANVAS.h
    base = _row_cost(segs, names, mid, half)
    if base <= 0 or hi <= lo:
        return None, base
    rows = [lo + (hi - lo) * i / 12 for i in range(13)]
    best = min(rows, key=lambda c: (round(_row_cost(segs, names, c, half), 3), abs(c - mid)))
    cost = _row_cost(segs, names, best, half)
    return (round(best, 3), cost) if cost < 0.6 * base else (None, base)


def held_position(plan: dict, a: float, b: float, style: dict) -> dict:
    """The lettering of a line that stays up from `a` to `b`: across several shots it sits where it covers
    least of them. First a height inside the reference's third of the frame (free_row -> style `y`: just off
    a head), and another third only when that is clearly freer still. On one shot the renderer keeps it off
    that subject."""
    from . import typo
    on = ["x" if min(b, float(s["out_start"]) + float(s["dur"])) - max(a, float(s["out_start"])) > 0.1 else ""
          for s in plan["segments"]]
    want = style.get("position")
    out = {k: v for k, v in style.items() if k != "y"}
    if sum(1 for x in on if x) < 2 or not want:
        return out
    if (plan.get("frame") or {}).get("band") or want not in typo.BANDS:  # (a letterbox's words sit in its bars)
        return {**out, "position": label_position(plan["segments"], on, want)}
    rows = {bd: free_row(plan["segments"], on, bd) for bd in ("upper", "center", "lower") if bd in typo.BANDS}
    best = min(rows, key=lambda bd: (rows[bd][1], bd != want))
    up = sum(float(s["dur"]) for s, x in zip(plan["segments"], on) if x)
    band = best if rows[want][1] > 0.08 * up and rows[best][1] < 0.6 * rows[want][1] else want  # (a sliver is fine)
    return {**out, "position": band, **({"y": rows[band][0]} if rows[band][0] is not None else {})}


def label_overlays(plan: dict, recipe: dict, names: list[str]) -> list[dict]:
    """A labels recipe's words: each shot's name on screen while the shot is (neighbours with one name share
    one overlay), under the reference's lead-in line, in its lettering. `names`: one per segment ("" = none)."""
    segs = plan["segments"]
    st = text_style(recipe, label=True)
    st["position"] = label_position(segs, names, st.get("position", "center"))
    lead = label_lead(recipe)
    total = float(plan["duration"])
    out: list[dict] = []
    i = 0
    while i < len(segs):
        name = names[i] if i < len(names) else ""
        j = i
        while j + 1 < len(segs) and name and (names[j + 1] if j + 1 < len(names) else "").lower() == name.lower():
            j += 1
        a = max(0.1, float(segs[i]["out_start"]))
        b = min(total - 0.05, float(segs[j]["out_start"]) + float(segs[j]["dur"]))
        if name and not segs[i].get("panel") and b - a >= 0.6:
            out.append({"type": "label", "text": name, **({"lead": lead} if lead else {}), "start": round(a, 3),
                        "duration": round(b - a, 3), "style": st, "recipe": "label",
                        "shots": [s.get("shot_id") for s in segs[i:j + 1]]})
        i = j + 1
    return out


def labels_stale(plan: dict) -> bool:
    """Has a shot under one of the recipe's labels changed since the label was written?"""
    by_start = {round(float(s["out_start"]), 3): k for k, s in enumerate(plan["segments"])}
    for o in plan.get("overlays") or []:
        if o.get("recipe") != "label" or not o.get("shots"):
            continue
        k = by_start.get(round(float(o["start"]), 3), 0 if float(o["start"]) <= 0.11 else None)
        now = [s.get("shot_id") for s in plan["segments"][k:k + len(o["shots"])]] if k is not None else None
        if now != o["shots"]:
            return True
    return False


def reference_lines(recipe: dict) -> dict:
    """The reference's own text for the copywriter to model ours on: {"tease", "payoff", "title", "label"}.
    A reference that shows several payoff lines, or a label per shot, gives a list (up to 8)."""
    rows: dict = {}
    t = recipe.get("text") or {}
    exact = t.get("exact") or []
    for ln in t.get("lines") or []:
        if str(ln.get("text") or "").strip():
            txt = str(ln["text"]).strip()
            if exact:  # the words exactly as the reference writes them (reftext), at about the same time
                a, b = float(ln.get("from") or 0), float(ln.get("to") or 0)
                best = max(exact, key=lambda e: min(b, e["to"]) - max(a, e["from"]))
                if min(b, best["to"]) - max(a, best["from"]) > 0:
                    txt = best["text"].replace("\n", " ")
            rows.setdefault(ln.get("role") or "title", []).append(txt)
    return {k: (v[:8] if k == "label" or (k == "payoff" and len(v) > 1) else v[0]) for k, v in rows.items()}


# ------------------------------------------------------------------------ critic
def checks(plan: dict, by_id: dict) -> list[tuple]:
    """(key, ok, weight, why, fix) rows for critic.checks: does the plan do what its reference does?"""
    r = plan.get("recipe") or {}
    segs = plan.get("segments") or []
    if not r or not segs:
        return []
    rows = []
    if r.get("structure") == "hold_burst":
        first = segs[0]
        shot = by_id.get(first.get("shot_id")) or {}
        ok = first["dur"] >= HOLD_MIN and shot.get("kind") == "video" and float(first.get("speed") or 1) >= 0.6
        rows.append(("opening_hold", ok, 15,
                     f"opens on one {first['dur']:.1f}s moving shot like its reference" if ok else
                     "the reference holds one long moving shot first; this opening is a photo, short or frozen",
                     None if ok else "hold_shot"))
    kind = r.get("text")
    have = {o.get("recipe") for o in plan.get("overlays") or []}
    want = {"lyrics": "lyric", "tease": "tease", "title": "title", "labels": "label"}.get(kind)
    if want:
        ok = want in have or (kind in ("lyrics", "tease") and bool(have & {"tease", "title", "lyric"}))
        rows.append(("reference_text", ok, 15,
                     "the words do what the reference's words do" if ok else
                     f"the reference's text ({kind}) is missing", None))
    return rows
