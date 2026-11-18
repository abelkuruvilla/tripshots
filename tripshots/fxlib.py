"""The effects library and its director: which transition at which cut, how each line of text comes in and how
it is drawn, and which shot (if any) gets a video effect, decided for this reel's footage, music and story.

Library: every transition (motion.py), text motion (hfx.py) and entrance (typo.py), text look (typo.LOOKS) and
shot effect (vfx.py), each described by its energy, mood and what it suits. `tripshots effects` lists it;
the desktop app's pickers show it.

Director (`direct`): the AI backend sees the reel as a list of shots (role, length, music level, what the shot
shows, whether the place changes) and lines of text, plus the library, and picks. Its choices are checked:
only ids from the library, the planner's number of transitions is kept (density belongs to the style; a few
cuts may change), at most three kinds of transition, few shot effects. Without an AI, rules pick by energy and
mood. A style that orders its transitions (`transitions.order`) or a recipe reel keeps its own transitions.
Style `effects` {use auto|ai|rules|off, transitions, text, shots, max_shot_effects}; plan `effects` notes what
was decided and why.
"""
from __future__ import annotations

import numpy as np

from .util import debug, log

# ---------------------------------------------------------------- the library
# energy: calm, medium, intense (where in a song it belongs). moods: the feeling it gives.
TRANSITIONS = {
    "dissolve": ("calm", "soft, dreamy, time passing", "one moment melting into the next; slow songs; beatless intros"),
    "luma": ("calm", "dreamy, luminous", "into a bright shot (sky, water, sunset): the light leads in"),
    "leak": ("calm", "warm, nostalgic, golden", "golden-hour and sunset shots, memories, film looks"),
    "dip": ("calm", "final, reflective", "a chapter ending: a new day, a new place after a pause"),
    "blur": ("calm", "soft, gentle", "two shots of the same place or mood"),
    "ripple": ("calm", "dreamy, watery", "into or out of water, a lake, the sea, a pool"),
    "burn": ("medium", "nostalgic, raw film", "vintage or road-trip feel, a change of day"),
    "push": ("medium", "clean, graphic, travelling", "moving on to the next place along the route (direction of travel)"),
    "wipe": ("medium", "clean, graphic", "a list of places, one after another"),
    "clock": ("medium", "playful, time", "time passing: morning to evening, a countdown"),
    "blinds": ("medium", "graphic, retro", "a stylised montage, design-led reels"),
    "flip": ("medium", "playful, reveal", "a before/after or a reveal of a second side"),
    "whip": ("medium", "energetic, travelling", "fast camera moves, cutting between two moving shots"),
    "zoom_in": ("intense", "energetic, arrival", "arriving somewhere big; into a wide landscape"),
    "zoom_out": ("medium", "reveal", "pulling back to reveal the whole place"),
    "zoomblur": ("intense", "punchy, rushing", "on a drop or a big beat, into a hero shot"),
    "shake": ("intense", "impact, raw", "on a hard hit in the music, an action moment"),
    "flash": ("intense", "punchy, bright", "on a drop; between two bright shots"),
    "rgb": ("intense", "edgy, glitchy", "a hit in an electronic song, night and city shots"),
    "glitch": ("intense", "edgy, digital", "electronic music, urban and night footage"),
    "pixel": ("intense", "playful, digital, retro-game", "a playful jump, a game-like montage"),
    "stretch": ("intense", "energetic, upward", "a jump up, a drone rise, an upbeat montage"),
    "spin": ("intense", "wild, playful", "a party, a high-energy montage (use once at most)"),
    "split": ("medium", "graphic, reveal", "a design-led reveal on the beat"),
    "vsplit": ("medium", "graphic, reveal", "a design-led reveal on the beat"),
    "iris": ("medium", "focus, reveal", "closing in on one subject, an opening into a new scene"),
    "slats": ("medium", "crafty, paper", "scrapbook and travel-diary reels"),
    "stripes": ("medium", "crafty, paper", "scrapbook and travel-diary reels"),
    "diamond": ("medium", "crafty, paper", "scrapbook reels"),
    "frame": ("medium", "crafty, window", "a window onto the next place"),
    "cells": ("medium", "graphic, grid", "grid and mosaic reels"),
    "mirror": ("calm", "reflective, dreamy", "lakes, reflections, symmetry"),
    "polaroid": ("medium", "nostalgic, memory", "a photo dropping in: memories, a trip diary"),
    "film": ("medium", "nostalgic, cinematic, road trip",
             "the picture shrinks onto a film strip that rolls on a frame: a new day, a memory, a road-trip chapter"),
    "tear": ("medium", "crafty, raw, scrapbook", "the picture rips like paper to show the next: a scrapbook or "
             "diary reel, a new chapter (params direction horizontal|vertical)"),
    "cube": ("medium", "energetic, travelling, 3D", "the two shots turn as faces of a cube: moving on to the next "
             "stop in a list or montage (params direction left|right|up|down: the way the trip goes)"),
    "card": ("medium", "social, quick, photo dump", "the shot shrinks to a rounded post card and flicks away: a "
             "photo dump, a list, a quick change of scene"),
    "dots": ("medium", "graphic, techy, night", "the next shot builds out of halftone dots, bright parts first: "
             "night skies, a city, a graphic reveal"),
}
# Settings the director may give a transition ("params"): only these values; the rest are chosen by the planner
TRANSITION_PARAMS = {
    "whip": {"direction": ("left", "right", "up", "down")}, "push": {"direction": ("left", "right", "up", "down")},
    "wipe": {"direction": ("left", "right", "up", "down")}, "spin": {"clockwise": (True, False)},
    "flip": {"axis": ("h", "v")}, "blinds": {"horizontal": (True, False)}, "film": {"direction": ("up", "down")},
    "tear": {"direction": ("horizontal", "vertical")}, "cube": {"direction": ("left", "right", "up", "down")},
}
TEXT_MOTIONS = {   # hfx.py (animated pages) and typo.py entrances
    "rise": ("calm", "elegant", "titles and places, calm openings"),
    "focus": ("calm", "cinematic, soft", "a line that pulls into focus over a wide shot"),
    "cinema": ("calm", "cinematic", "a film title over a landscape"),
    "tracking": ("calm", "airy, luxurious", "short titles, minimal reels"),
    "typewriter": ("medium", "diary, storytelling", "a journal line, a date, a list"),
    "write": ("calm", "personal, handwritten", "a personal note, a place in someone's handwriting"),
    "decode": ("medium", "techy, mysterious", "a reveal, coordinates, a night city"),
    "stamp": ("medium", "travel, passport", "a place name like a passport stamp, a list of stops"),
    "slam": ("intense", "punchy, bold", "a hook on a beat, a bold claim"),
}
TEXT_LOOKS = {   # typo.LOOKS: how the letters are drawn
    "neon": ("intense", "night, electric", "night shots and cities, a party (the text colour glows)"),
    "glow": ("calm", "dreamy, warm", "sunsets, soft dreamy reels"),
    "outline": ("medium", "modern, graphic", "a big word over a busy picture, design-led reels"),
    "offset": ("medium", "playful, retro, poster", "playful or retro titles, a list"),
}
SHOT_EFFECTS = {   # vfx.py
    "glow": ("calm", "dreamy, warm", "sunsets, city lights, sun on water: the highlights bloom", 0.5),
    "dream": ("calm", "hazy, romantic", "a slow, tender moment; a memory", 0.5),
    "leak": ("calm", "warm, nostalgic", "golden hour, a memory", 0.5),
    "dust": ("medium", "vintage film", "an old town, a vintage car, a nostalgic chapter", 0.6),
    "vhs": ("medium", "retro camcorder", "a throwback, friends goofing around, a home-video moment", 0.6),
    "mono": ("calm", "timeless, serious", "one striking moment taken out of time", 1.0),
    "duotone": ("medium", "poster, graphic", "a bold graphic moment, a silhouette", 0.7),
    "chroma": ("intense", "edgy", "night city, a hit in the music", 0.5),
    "flicker": ("intense", "strobe", "an intense section with a clear beat", 0.6),
    "mirror": ("medium", "graphic, symmetric", "architecture, a road, a reflection", 1.0),
    "handheld": ("calm", "lived-in, documentary", "a locked-off tripod shot that feels too still", 0.6),
    "tiltshift": ("calm", "miniature, playful", "a high view over a town, cars, people (looks like a model)", 0.7),
}


# Signature moves: the bigger ideas learned from trend reels (each began as a built-in style made from references).
# Any reel may use them: the director picks at most a couple, on shots that can carry them, so a reel gets the
# photo wall without anyone pointing at a grid reel. A style that switches one on itself (motion.mosaic, ...) keeps it.
MOVES = {
    "photo_wall": ("medium", "a trip in one frame, a memory wall",
                   "one held shot of a person mid-reel: the grid cells round them fill with little pictures of the "
                   "trip's other places, hold, and clear (shots listed under photo_wall)"),
    "grid_lines": ("calm", "design-led, editorial, warm",
                   "a fine grid of light lines over the whole reel; calm or warm diaries, and with the photo wall or "
                   "the cells transition"),
    "backdrop_places": ("medium", "playful, travelling, 'everywhere at once'",
                        "a person holding still while the world behind them swaps to another place of the trip on "
                        "each beat (shots listed under backdrop)"),
    "backdrop_colour": ("medium", "graphic, pop, poster",
                        "the person cut out against flat colours from their own scene, a new colour on each beat "
                        "(shots listed under backdrop)"),
    "silhouette": ("intense", "punchy, graphic",
                   "people flash paper-white for two frames as their shot lands on a hit (shots listed under people)"),
    "colour_bloom": ("calm", "cinematic, a moment taking shape",
                     "a shot arrives in black and white and its colour blooms in: the hook, a new place, the payoff"),
    "freeze_intro": ("medium", "playful, 'meet the crew', a beat to remember",
                     "the moment stops on a beat: the person keeps their colour with a thick white sticker outline, "
                     "the world behind goes grey and dim, then it plays on (shots listed under freeze; settings "
                     "beats 1-4 = how long it holds)"),
    "clone_trail": ("medium", "magic, playful, motion",
                    "a person walking or jumping through a still frame leaves copies of themselves where they were "
                    "on earlier beats (shots listed under clone: tripod or still camera only; settings copies 2-5)"),
    "colour_pop": ("calm", "focused, dreamy, 'only you'",
                   "the person stays in colour and the world round them turns black and white: the one person who "
                   "matters, a quiet moment (shots listed under isolate; settings amount 0.5-1)"),
    "spotlight": ("intense", "dramatic, stage, a reveal",
                  "the lights go down round the person and they stay lit: a drop, a big reveal, an entrance "
                  "(shots listed under isolate; settings amount 0.4-0.9)"),
    "camera_roll": ("medium", "photo dump, 'my camera roll', personal",
                    "the reel opens on the phone's camera roll: a grid of the trip's photos scrolls and slows, then "
                    "one opens into the shot (shots listed under opener; settings seconds 0.8-1.6)"),
    "flash_zoom": ("intense", "punchy, hype, 'look at this'",
                   "on the beats the picture snaps closer to the person's face (or the subject) in steps, a flash on "
                   "each hit, following them as they move: a build or a drop, an entrance, a reaction (shots "
                   "listed under zoom; settings hits 2-4, zoom 1.25-1.8 = how close at the end, flash white|warm|"
                   "cool|none, focus face|person, out = the last hit snaps back to the whole frame)"),
}
# what the director may set per move ("settings"): name -> (low, high) or choices; clipped into range
MOVE_SETTINGS = {
    "grid_lines": {"cols": (6, 12), "alpha": (0.15, 0.45)},
    "colour_bloom": {"seconds": (0.3, 1.2)},
    "freeze_intro": {"beats": (1, 4), "outline": (True, False)},
    "clone_trail": {"copies": (2, 5)},
    "colour_pop": {"amount": (0.5, 1.0)},
    "spotlight": {"amount": (0.4, 0.9)},
    "camera_roll": {"seconds": (0.8, 1.6), "light": (True, False)},
    "flash_zoom": {"hits": (2, 4), "zoom": (1.25, 1.8), "flash": ("white", "warm", "cool", "none"),
                   "focus": ("face", "person"), "out": (True, False)},
}
MAX_MOVES = 2   # kinds of move in one reel


def catalog() -> dict:
    """The whole library, for `tripshots effects`, MCP and the desktop pickers."""
    def rows(d, kind):
        return [{"id": k, "kind": kind, "energy": v[0], "mood": v[1], "suits": v[2],
                 **({"amount": v[3]} if len(v) > 3 else {})} for k, v in d.items()]
    return {"transitions": rows(TRANSITIONS, "transition"), "text_motions": rows(TEXT_MOTIONS, "text_motion"),
            "text_looks": rows(TEXT_LOOKS, "text_look"), "shot_effects": rows(SHOT_EFFECTS, "shot_effect"),
            "moves": rows(MOVES, "move")}


def _subject_size(seg: dict) -> float:
    b = seg.get("subject") or {}
    try:
        return (float(b.get("x1", 0)) - float(b.get("x0", 0))) * (float(b.get("y1", 0)) - float(b.get("y0", 0)))
    except (TypeError, ValueError):
        return 0.0


def _still_camera(seg: dict, by_id: dict | None) -> bool:
    sh = (by_id or {}).get(seg.get("shot_id")) or {}
    met, ai = sh.get("metrics") or {}, sh.get("ai") or {}
    if ai.get("motion") and ai["motion"] != "static":
        return False
    return bool(ai.get("motion") == "static" or (met and float(met.get("pan", 1)) < 0.002
                                                  and float(met.get("shake", 1)) < 0.004))


def _person_big(seg: dict, by_id: dict | None) -> bool:
    """Is the person big enough in frame to be cut out (a freeze outline, a colour pop, a clone)? The AI's shot size
    when known (never a wide view of a place), else the subject box."""
    size = (((by_id or {}).get(seg.get("shot_id")) or {}).get("ai") or {}).get("shot_size")
    if size:
        return size != "wide"
    return _subject_size(seg) >= 0.03


def eligible(plan: dict, style: dict, by_id: dict | None = None) -> dict[str, list[int]]:
    """Which shots (1-based) can carry each move: the AI may only choose among these. A move the style already
    does, or one that can't work in this reel, has none."""
    segs = plan["segments"]
    motion = style.get("motion") or {}
    tempo = float(plan.get("tempo") or 120) or 120
    beat = 60.0 / tempo
    every = beat if beat >= 0.3 else 2 * beat
    free = [i for i, s in enumerate(segs) if not s.get("panel") and not s.get("backdrop") and not s.get("mosaic")]
    out = {
        "photo_wall": [i + 1 for i in free if 0 < i < len(segs) - 1 and float(segs[i]["dur"]) >= 1.5
                       and segs[i].get("people")] if not motion.get("mosaic") else [],
        "backdrop": [i + 1 for i in free if segs[i].get("people") and segs[i].get("kind") == "video"
                     and float(segs[i]["dur"]) >= 3 * every and _subject_size(segs[i]) >= 0.03]
        if not motion.get("backdrop") else [],
        "people": [i + 1 for i in free if segs[i].get("people")] if not motion.get("silhouette") else [],
        "colour_bloom": [i + 1 for i in free if float(segs[i]["dur"]) >= 1.0] if not motion.get("colour_in") else [],
        # a beat to stop on, clear of the transitions at either end
        "freeze": [i + 1 for i in free if segs[i].get("people") and float(segs[i]["dur"]) >= max(1.2, 3 * beat)
                   and _person_big(segs[i], by_id)],
        "clone": [i + 1 for i in free if segs[i].get("people") and segs[i].get("kind") == "video"
                  and _person_big(segs[i], by_id)
                  and float(segs[i]["dur"]) >= max(1.6, 4 * beat) and not segs[i].get("speed_ramp")
                  and not segs[i].get("ramp") and _still_camera(segs[i], by_id)],
        # the opening shot, or the first shot of a new place
        "opener": [i + 1 for i in free if float(segs[i]["dur"]) >= 1.6 and not segs[i].get("hold")
                   and (i == 0 or (segs[i].get("place") and segs[i].get("place") != segs[i - 1].get("place")))],
        "isolate": [i + 1 for i in free if segs[i].get("people") and float(segs[i]["dur"]) >= 0.7
                    and _person_big(segs[i], by_id)],
        # two beats or more to punch in on, and someone (or one clear subject) to punch in on
        "zoom": [i + 1 for i in free if not segs[i].get("roll") and len(_hits(segs[i], plan)) >= 2
                 and (segs[i].get("people") or _subject_size(segs[i]) >= 0.02)],
    }
    if not (plan.get("grid") or motion.get("grid")):
        out["grid_lines"] = ["whole reel"]   # needs no particular shot
    return out


# ---------------------------------------------------------------- the director
TEXT_KINDS = ("hook", "location", "cta", "label", "text")


def _context(plan: dict, by_id: dict) -> tuple[list[dict], list[dict], list[dict]]:
    segs = plan["segments"]
    shots, cuts, texts = [], [], []
    for i, s in enumerate(segs):
        a = (by_id.get(s.get("shot_id")) or {}).get("ai") or {}
        shots.append({"n": i + 1, "role": s.get("role"), "dur": round(float(s["dur"]), 2),
                      "music": s.get("level", "medium"), "drop": bool(s.get("drop")), "kind": s.get("kind"),
                      "shows": (a.get("note") or "")[:90], "tags": (a.get("tags") or [])[:5],
                      "light": a.get("time_of_day"), "people": bool(s.get("people") or a.get("people")),
                      "place": s.get("place") or a.get("place"),
                      **({"vibes": a["vibes"]} if a.get("vibes") else {}),
                      **({"size": a["shot_size"]} if a.get("shot_size") else {}),
                      **({"angle": a["angle"]} if a.get("angle") else {})})
    for i in range(len(segs) - 1):
        e, nx = segs[i], segs[i + 1]
        if e.get("incam_out") or e.get("panel") or nx.get("panel"):
            continue
        cuts.append({"cut": i + 1, "from": i + 1, "to": i + 2, "now": e.get("trans_out") or "cut",
                     "music": nx.get("level", "medium"), "drop": bool(nx.get("drop")),
                     "beatless": bool(e.get("beatless") and nx.get("beatless"))})
    for k, o in enumerate(plan.get("overlays") or []):
        if o.get("type") in TEXT_KINDS and not o.get("recipe"):
            texts.append({"index": k + 1, "type": o["type"], "text": (o.get("text") or o.get("main") or "")[:60],
                          "at": round(float(o.get("start", 0)), 2)})
    return shots, cuts, texts


PROMPT = """You are the finishing editor of a short travel reel. Choose effects from the library below so each one
serves a moment in this reel. Restraint matters: most cuts stay plain cuts on the beat; an effect marks a change
of place, a change in the music, a drop, a mood. Match the energy of the music at that point and the feeling of
the two shots.

Shots in order: {shots}
Cuts (now = what the planner put there; keep about {n_tr} transitions in total, all at cuts that deserve one,
and at most 3 different kinds): {cuts}
Lines of text: {texts}
Song: {tempo} BPM. Style: {style}. {style_hint}

Library (id: energy | mood | suits):
TRANSITIONS
{lib_tr}
TEXT MOTIONS (how a line comes in)
{lib_tm}
TEXT LOOKS (how letters are drawn; null = plain, which is right for most reels)
{lib_tl}
SHOT EFFECTS (at most {max_fx} shots, only where the shot itself calls for it; none is a fine answer)
{lib_fx}
SIGNATURE MOVES (the big trend ideas; at most {max_moves} kinds in this reel, each on the shots that can carry it.
Use one when the footage and the song suit it, so the reel has a memorable moment; none is fine for a plain cut.
A move suits the reel's mood: the photo wall and grid for warm diaries, the backdrop swap for upbeat songs with
you in frame, silhouettes and the spotlight on hits, colour bloom and colour pop for cinematic or tender moments,
the freeze-frame intro to introduce the people on a beat, the clone trail for someone moving through a still
frame, the camera roll to open a photo-dump or "my trip in pictures" reel, the flash zoom to punch in on a
person on the hits of a build or a drop (warm flash on golden light, none on a calm song). Choose its settings for this reel:
a short hold on a fast song, a longer one on a slow song; fewer clones in a short shot)
{lib_mv}
Shots that can carry each move: {eligible}
Settings each move takes: {settings}
Transition settings ("params", optional; otherwise the planner chooses): {tparams}. Pick a direction that follows
the movement in the shots or the direction of travel, and vary it between cuts.

Answer with JSON only:
{{"transitions": [{{"cut": 3, "id": "push", "params": {{"direction": "left"}}, "why": "..."}}],   (every cut you want to change; "cut" = plain cut)
 "texts": [{{"index": 1, "motion": "slam", "look": null, "why": "..."}}],
 "effects": [{{"shot": 5, "id": "glow", "amount": 0.5, "why": "..."}}],
 "moves": [{{"id": "freeze_intro", "shots": [7], "settings": {{"beats": 2}}, "why": "..."}}],
 "summary": "one sentence on the overall choice"}}"""


def _lib(d: dict) -> str:
    return "\n".join(f"{k}: {v[0]} | {v[1]} | {v[2]}" for k, v in d.items())


def _rules(plan: dict, by_id: dict, cfg: dict) -> dict:
    """No AI: pick each planned transition from the library by the music's energy and what the shots show."""
    segs = plan["segments"]
    out = {"transitions": [], "texts": [], "effects": [], "summary": "chosen by rules (energy and light)"}
    used: list[str] = []
    for i in range(len(segs) - 1):
        e, nx = segs[i], segs[i + 1]
        if not e.get("trans_out") or e.get("incam_out") or e.get("panel") or nx.get("panel"):
            continue
        a = (by_id.get(nx.get("shot_id")) or {}).get("ai") or {}
        tags = " ".join(a.get("tags") or []).lower() + " " + str(a.get("time_of_day") or "").lower()
        lvl = nx.get("level", "medium")
        vib = a.get("vibes") or {}
        top = max(vib, key=vib.get) if vib else None
        if e.get("beatless") and nx.get("beatless"):
            pick = ["dissolve"]
        elif top == "nostalgic" and vib[top] >= 0.6:
            pick = ["leak", "burn"]
        elif top in ("romantic", "serene") and vib[top] >= 0.7 and lvl != "intense":
            pick = ["luma", "dissolve"]
        elif a.get("angle") == "aerial" and lvl != "calm":
            pick = ["zoom_in", "push"]
        elif nx.get("drop") or lvl == "intense":
            pick = ["zoomblur", "flash", "shake"]
        elif any(w in tags for w in ("sunset", "golden", "dusk", "sunrise")):
            pick = ["leak", "luma"]
        elif any(w in tags for w in ("water", "lake", "sea", "ocean", "beach", "river")):
            pick = ["luma", "dissolve"]
        elif lvl == "calm":
            pick = ["dissolve", "blur"]
        else:
            pick = ["push", "whip"]
        kinds = set(used)
        choice = next((p for p in pick if p in kinds), None) if len(kinds) >= 3 else None
        choice = choice or next((p for p in pick if not used or p != used[-1]), pick[0])
        used.append(choice)
        out["transitions"].append({"cut": i + 1, "id": choice, "why": f"{lvl} music" + (", drop" if nx.get("drop") else "")})
    return out


def _check(raw: dict, plan: dict, cuts: list[dict], cfg: dict) -> dict:
    """Keep only what fits the library and the reel's own restraint."""
    segs = plan["segments"]
    ok_cuts = {c["cut"] for c in cuts}
    planned = sum(1 for c in cuts if c["now"] != "cut")
    allowed = planned + planned // 3   # a hard-cut style (none planned) stays hard-cut
    tr: dict[int, str] = {c["cut"]: c["now"] for c in cuts}
    params: dict[int, dict] = {}
    for t in raw.get("transitions") or []:
        try:
            n, tid = int(t.get("cut")), str(t.get("id") or "cut")
        except (TypeError, ValueError):
            continue
        if n in ok_cuts and (tid == "cut" or tid in TRANSITIONS):
            tr[n] = tid
            allowed_p = TRANSITION_PARAMS.get(tid) or {}
            got = {k: v for k, v in (t.get("params") or {}).items() if k in allowed_p and v in allowed_p[k]} \
                if isinstance(t.get("params"), dict) else {}
            if got:
                params[n] = got
    # restraint: no more transitions than the style planned (plus a few), at most three kinds
    kinds: list[str] = []
    for n in sorted(tr):
        if tr[n] == "cut":
            continue
        if tr[n] not in kinds:
            if len(kinds) >= 3:
                tr[n] = kinds[0]
            else:
                kinds.append(tr[n])
    on = [n for n in sorted(tr) if tr[n] != "cut"]
    keep = set(on[:allowed]) | {n for n in on if segs[n].get("drop") or segs[n].get("role") == "peak"}
    tr = {n: (v if n in keep else "cut") for n, v in tr.items()}
    from .hfx import MOTIONS
    from .typo import LOOKS
    texts = []
    n_ov = len(plan.get("overlays") or [])
    for t in raw.get("texts") or []:
        try:
            k = int(t.get("index"))
        except (TypeError, ValueError):
            continue
        if not 1 <= k <= n_ov:
            continue
        m, lk = t.get("motion"), t.get("look")
        texts.append({"index": k, "motion": m if m in MOTIONS else None, "look": lk if lk in LOOKS else None,
                      "why": str(t.get("why") or "")[:120]})
    effects = []
    for f in raw.get("effects") or []:
        try:
            n, fid = int(f.get("shot") or f.get("segment")), str(f.get("id"))
        except (TypeError, ValueError):
            continue
        if fid in SHOT_EFFECTS and 1 <= n <= len(segs) and not segs[n - 1].get("panel") \
                and len(effects) < int(cfg.get("max_shot_effects", 2)):
            amt = float(f.get("amount") or SHOT_EFFECTS[fid][3])
            effects.append({"shot": n, "id": fid, "amount": round(max(0.15, min(1.0, amt)), 2),
                            "why": str(f.get("why") or "")[:120]})
    params = {n: v for n, v in params.items() if tr.get(n) not in (None, "cut")}
    return {"transitions": tr, "params": params, "texts": texts, "effects": effects, "moves": check_moves(raw.get("moves"), cfg),
            "summary": str(raw.get("summary") or "")[:200]}


MOVE_SLOTS = {"photo_wall": "photo_wall", "backdrop_places": "backdrop", "backdrop_colour": "backdrop",
              "silhouette": "people", "colour_bloom": "colour_bloom", "grid_lines": None,
              "freeze_intro": "freeze", "clone_trail": "clone", "colour_pop": "isolate", "spotlight": "isolate",
              "camera_roll": "opener", "flash_zoom": "zoom"}
MOVE_MAX_SHOTS = {"photo_wall": 1, "backdrop_places": 1, "backdrop_colour": 1, "silhouette": 3, "colour_bloom": 2,
                  "freeze_intro": 2, "clone_trail": 1, "colour_pop": 2, "spotlight": 1, "camera_roll": 1, "flash_zoom": 2}


def _settings(mid: str, raw) -> dict:
    """The move's settings from the AI, only known ones, clipped into range."""
    out = {}
    for k, rng in (MOVE_SETTINGS.get(mid) or {}).items():
        v = (raw or {}).get(k) if isinstance(raw, dict) else None
        if v is None:
            continue
        if isinstance(rng[0], bool):
            out[k] = bool(v)
            continue
        if isinstance(rng[0], str):   # one of a few named choices
            if str(v) in rng:
                out[k] = str(v)
            continue
        try:
            out[k] = round(max(rng[0], min(rng[1], float(v))), 2)
        except (TypeError, ValueError):
            pass
    return out


def check_moves(raw, cfg: dict) -> list[dict]:
    """Only known moves, only on shots that can carry them, at most MAX_MOVES kinds, one backdrop kind."""
    elig = cfg.get("_eligible") or {}
    out, taken = [], set()
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict) or m.get("id") not in MOVES or len(out) >= int(cfg.get("max_moves", MAX_MOVES)):
            continue
        mid = m["id"]
        if any(o["id"] == mid for o in out) or (mid.startswith("backdrop") and any(o["id"].startswith("backdrop") for o in out)):
            continue
        slot = MOVE_SLOTS[mid]
        if slot is None:
            if not elig.get("grid_lines"):   # a reel that already has its grid
                continue
            out.append({"id": mid, "shots": [], "settings": _settings(mid, m.get("settings")),
                        "why": str(m.get("why") or "")[:120]})
            continue
        try:
            want = [int(x) for x in (m.get("shots") or ([m["shot"]] if m.get("shot") else []))]
        except (TypeError, ValueError):
            continue
        ok = [n for n in want if n in (elig.get(slot) or []) and n not in taken][:MOVE_MAX_SHOTS[mid]]
        if ok:
            taken.update(ok)
            out.append({"id": mid, "shots": ok, "settings": _settings(mid, m.get("settings")),
                        "why": str(m.get("why") or "")[:120]})
    return out


def apply_choices(plan: dict, ch: dict, cfg: dict) -> list[str]:
    """Write checked choices into the plan; returns what changed, in words."""
    from .planner import fit_transition
    segs = plan["segments"]
    done = []
    if cfg.get("transitions", True):
        side = 0
        for n, tid in sorted((ch.get("transitions") or {}).items()):
            e, nx = segs[n - 1], segs[n]
            name = None if tid == "cut" else tid
            own = (ch.get("params") or {}).get(n) or {}
            if name == e.get("trans_out"):
                if own and name:   # the same transition, set the AI's way
                    e["trans_params"] = {**(e.get("trans_params") or {}), **own}
                    done.append(f"cut {n}: {name} " + " ".join(f"{k}={v}" for k, v in own.items()))
                continue
            if name:
                d, prm = fit_transition(e, nx, name, plan.get("tempo"), None, side)
                prm = {**prm, **own}
                d = min(d, 0.9 * min(float(e["dur"]), float(nx["dur"])))
                if d < 0.12:
                    continue
                side += 1
                e.update({"trans_out": name, "trans_dur": round(max(2, int(round(d * 30 / 2)) * 2) / 30, 4),
                          "trans_params": prm})
            else:
                e.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
            done.append(f"cut {n}: {name or 'plain cut'}")
    if cfg.get("text", True):
        ovs = plan.get("overlays") or []
        for t in ch.get("texts") or []:
            o = ovs[t["index"] - 1]
            if o.get("user"):
                continue   # the user's own lettering stays
            if t.get("motion"):
                o["motion"] = t["motion"]
            if t.get("look"):
                o.setdefault("style", {})["look"] = t["look"]
            if t.get("motion") or t.get("look"):
                done.append(f"text {t['index']}: " + " ".join(x for x in (t.get("motion"), t.get("look")) if x))
    if cfg.get("shots", True):
        for f in ch.get("effects") or []:
            segs[f["shot"] - 1]["effect"] = {"id": f["id"], "amount": f["amount"], "auto": True}
            done.append(f"shot {f['shot']}: {f['id']}")
    if cfg.get("moves", True):
        done += apply_moves(plan, ch.get("moves") or [], cfg.get("_shots"))
    return done


def apply_moves(plan: dict, moves: list[dict], shots: list[dict] | None) -> list[str]:
    """Put the chosen signature moves into the plan, with the planner's own code for each (planner.plan_mosaic,
    plan_backdrops) and the same segment keys a style that does them sets."""
    from .planner import plan_backdrops, plan_mosaic, plan_roll
    segs = plan["segments"]
    tempo = float(plan.get("tempo") or 120) or 120
    beat = 60.0 / tempo
    done = []
    for m in moves:
        mid, at = m["id"], [n - 1 for n in m.get("shots") or []]
        st = m.get("settings") or {}
        if mid == "grid_lines":
            plan["grid"] = {"cols": int(st.get("cols", 8)), "alpha": float(st.get("alpha", 0.3))}
            done.append("move: grid lines")
        elif mid == "photo_wall" and shots:
            cols = int((plan.get("grid") or {}).get("cols", 8))
            k = plan_mosaic(segs, shots, {"motion": {"grid": {"cols": cols}}}, at=at[0])
            if k is not None:
                done.append(f"move: photo wall on shot {k + 1}")
        elif mid.startswith("backdrop") and shots:
            mode = "places" if mid == "backdrop_places" else "colour"
            got = plan_backdrops(segs, shots, {"motion": {"backdrop": mode}}, 60.0 / tempo, at=at)
            if got:
                done.append(f"move: backdrop ({mode}) on shot {got[0] + 1}")
        elif mid == "silhouette":
            for i in at:
                segs[i]["silhouette"] = True
            done.append("move: silhouette flash on shot " + ", ".join(str(i + 1) for i in at))
        elif mid == "colour_bloom":
            for i in at:
                segs[i]["colour_in"] = float(st.get("seconds", 0.6))
            done.append("move: colour bloom on shot " + ", ".join(str(i + 1) for i in at))
        elif mid == "freeze_intro":
            got = [i for i in at if _pose(segs[i], plan, beat, st)]
            if not got:
                continue
            done.append("move: freeze-frame intro on shot " + ", ".join(str(i + 1) for i in got))
        elif mid == "clone_trail":
            got = [i for i in at if _clones(segs[i], plan, beat, st)]
            if not got:
                continue
            done.append(f"move: clone trail on shot {got[0] + 1}")
        elif mid in ("colour_pop", "spotlight"):
            kind = "pop" if mid == "colour_pop" else "spotlight"
            for i in at:
                segs[i]["isolate"] = {"kind": kind, "amount": float(st.get("amount", 1.0 if kind == "pop" else 0.85))}
            done.append(f"move: {mid.replace('_', ' ')} on shot " + ", ".join(str(i + 1) for i in at))
        elif mid == "flash_zoom":
            got = [i for i in at if _zoompunch(segs[i], plan, st)]
            if not got:
                continue
            done.append("move: flash zoom on shot " + ", ".join(str(i + 1) for i in got))
        elif mid == "camera_roll" and shots and at:
            k = plan_roll(segs, shots, at[0], beat)
            if k is None:
                continue
            if st.get("seconds"):
                segs[k]["roll"]["dur"] = round(min(float(st["seconds"]), 0.55 * float(segs[k]["dur"])), 3)
            if st.get("light"):
                segs[k]["roll"]["light"] = True
            if k > 0:   # it opens out of the grid on the cut itself: no transition into it
                segs[k - 1].update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
            done.append(f"move: camera roll opens shot {k + 1}")
        else:
            continue
        plan.setdefault("moves", []).append({k: v for k, v in m.items() if k != "why"} | {"auto": True})
    return done


def _ends(seg: dict, plan: dict) -> tuple[float, float]:
    """(start, end) of the part of a shot clear of the transitions at either end, in seconds into the shot."""
    segs = plan["segments"]
    i = next(k for k, s in enumerate(segs) if s is seg)
    lead = float(segs[i - 1].get("trans_dur") or 0) / 2 if i and segs[i - 1].get("trans_out") else 0.0
    tail = float(seg.get("trans_dur") or 0) / 2 if seg.get("trans_out") else 0.0
    return lead, float(seg["dur"]) - tail


def _beats_in(seg: dict, plan: dict) -> list[float]:
    t0 = float(seg.get("out_start", 0))
    return [float(b) - t0 for b in plan.get("beats") or [] if 0 < float(b) - t0 < float(seg["dur"])]


def _pose(seg: dict, plan: dict, beat: float, st: dict) -> bool:
    """Freeze-frame intro: stop on a beat at least a quarter of a second in, hold `beats` beats (about 0.6 s at
    least), and play on before the way out."""
    a, b = _ends(seg, plan)
    hold = max(0.5, min(1.4, float(st.get("beats", 2)) * beat))
    on = [t for t in _beats_in(seg, plan) if t >= a + 0.25 and t + hold <= b - 0.15] or \
         ([a + 0.3] if a + 0.3 + hold <= b - 0.15 else [])
    if not on:
        return False
    seg["pose"] = {"at": round(on[0], 3), "dur": round(hold, 3), "outline": bool(st.get("outline", True))}
    return True


def _clones(seg: dict, plan: dict, beat: float, st: dict) -> bool:
    """Clone trail: a pose kept on each of `copies` beats spread over the shot, before its last third."""
    a, b = _ends(seg, plan)
    n = int(st.get("copies", 3))
    times = [t for t in _beats_in(seg, plan) if a + 0.1 <= t <= a + (b - a) * 0.7]
    if len(times) < 2:
        times = list(np.linspace(a + 0.15, a + (b - a) * 0.65, n)) if b - a >= 1.2 else []
    if len(times) < 2:
        return False
    step = max(1, len(times) // n)
    seg["clones"] = {"times": [round(float(t), 3) for t in times[::step][:n]], "alpha": 0.9}
    return True


def _hits(seg: dict, plan: dict, gap: float = 0.28) -> list[float]:
    """The beats a flash zoom can hit in a shot: clear of the transitions, not in the last moment before the cut,
    at least `gap` apart (every other beat on a very fast song)."""
    a, b = _ends(seg, plan)
    out: list[float] = []
    for t in _beats_in(seg, plan):
        if a + 0.15 <= t <= b - 0.2 and (not out or t - out[-1] >= gap):
            out.append(t)
    return out


def _zoompunch(seg: dict, plan: dict, st: dict) -> bool:
    """Flash zoom: the last `hits` beats before the cut each snap the picture closer (it builds into the cut), the
    zoom growing in even steps to `zoom`; with `out` the last hit snaps back to the whole frame instead."""
    if seg.get("pose") or seg.get("clones") or seg.get("roll"):
        return False   # (a stopped or opened picture is its own moment)
    hits = _hits(seg, plan)
    n = max(2, min(int(st.get("hits", 3)), len(hits)))
    if len(hits) < 2:
        return False
    times = hits[-n:]
    focus = str(st.get("focus") or ("face" if seg.get("people") else "person"))
    top = float(st.get("zoom", 1.55 if focus == "face" else 1.4))
    out = bool(st.get("out")) and n >= 3
    steps = n - 1 if out else n
    zooms = [round(top ** ((k + 1) / steps), 3) for k in range(steps)] + ([1.0] if out else [])
    seg["zoompunch"] = {"times": [round(t, 3) for t in times], "zooms": zooms,
                        "flash": str(st.get("flash", "white")), "focus": focus}
    return True


# each move's segment key, and its name in the app
SEG_KEYS = {"photo_wall": "mosaic", "backdrop_places": "backdrop", "backdrop_colour": "backdrop",
            "silhouette": "silhouette", "colour_bloom": "colour_in", "freeze_intro": "pose", "clone_trail": "clones",
            "colour_pop": "isolate", "spotlight": "isolate", "camera_roll": "roll", "flash_zoom": "zoompunch"}
MOVE_NAMES = {"photo_wall": "Photo wall", "backdrop_places": "Backdrop swap (places)",
              "backdrop_colour": "Backdrop swap (colours)", "silhouette": "Silhouette flash",
              "colour_bloom": "Colour bloom", "freeze_intro": "Freeze-frame intro", "clone_trail": "Clone trail",
              "colour_pop": "Colour pop", "spotlight": "Spotlight", "camera_roll": "Camera roll",
              "flash_zoom": "Flash zoom", "grid_lines": "Grid lines"}


def moves_on(seg: dict) -> list[str]:
    """The signature moves a shot carries (whoever set them: the director, a style or you)."""
    out = []
    for mid, k in SEG_KEYS.items():
        v = seg.get(k)
        if not v:
            continue
        if k == "isolate" and (v.get("kind", "pop") == "pop") != (mid == "colour_pop"):
            continue
        if k == "backdrop" and ((v.get("mode") if isinstance(v, dict) else v) == "colour") != (mid == "backdrop_colour"):
            continue
        out.append(mid)
    return out


def remove_move(plan: dict, slot: int, mid: str) -> bool:
    """Take one move off one shot (and out of the plan's record of the director's moves)."""
    segs = plan.get("segments") or []
    if not 0 < slot <= len(segs) or mid not in SEG_KEYS or mid not in moves_on(segs[slot - 1]):
        return False
    segs[slot - 1].pop(SEG_KEYS[mid], None)
    kept = []
    for m in plan.get("moves") or []:
        if m.get("id") == mid and slot in (m.get("shots") or []):
            m = {**m, "shots": [n for n in m["shots"] if n != slot]}
            if not m["shots"]:
                continue
        kept.append(m)
    plan["moves"] = kept
    return True


def clear_moves(plan: dict) -> int:
    """Take out the moves the director chose before (plan `moves`, auto), before it chooses again."""
    keys = SEG_KEYS
    segs = plan.get("segments") or []
    gone = 0
    for m in plan.pop("moves", None) or []:
        if m.get("id") == "grid_lines":
            plan.pop("grid", None)
        for n in m.get("shots") or []:
            if 0 < n <= len(segs):
                segs[n - 1].pop(keys.get(m.get("id"), ""), None)
        gone += 1
    return gone


def _rule_moves(plan: dict, by_id: dict, elig: dict) -> list[dict]:
    """No AI: one move when the reel plainly has what it needs: you in frame on an upbeat song -> the backdrop
    swap; you on its drop -> the flash zoom; a held shot of you mid-reel -> the photo wall; you on the payoff of a
    fast song -> the freeze-frame intro; else colour bloom on the payoff."""
    segs = plan["segments"]
    tempo = float(plan.get("tempo") or 0)
    if elig.get("backdrop") and tempo >= 100:
        n = max(elig["backdrop"], key=lambda n: _subject_size(segs[n - 1]))
        return [{"id": "backdrop_places", "shots": [n], "why": "you in frame on an upbeat song"}]
    drop = next((i + 1 for i, s in enumerate(segs) if s.get("drop") and i + 1 in (elig.get("zoom") or [])
                 and s.get("people")), None)
    if drop and tempo >= 100:
        return [{"id": "flash_zoom", "shots": [drop], "why": "you on the drop of an upbeat song: punch in on the hits"}]
    if elig.get("photo_wall") and sum(float(s["dur"]) for s in segs) >= 12:
        mid = sum(float(s["dur"]) for s in segs) / 2
        n = min(elig["photo_wall"], key=lambda n: abs(float(segs[n - 1]["out_start"]) - mid))
        return [{"id": "photo_wall", "shots": [n], "why": "a held shot of you in the middle of the reel"}]
    peak = next((i + 1 for i, s in enumerate(segs) if s.get("role") == "peak"), None)
    if peak and peak in (elig.get("freeze") or []) and tempo >= 110:
        return [{"id": "freeze_intro", "shots": [peak], "why": "you on the payoff of a fast song: stop on the beat"}]
    if peak and peak in (elig.get("colour_bloom") or []):
        return [{"id": "colour_bloom", "shots": [peak], "why": "the payoff blooms into colour"}]
    return []


def direct(plan: dict, by_id: dict, style: dict, backend=None, shots: list[dict] | None = None) -> dict:
    """Choose this reel's effects from the library (AI when there is one, else rules) and apply them.
    Returns the plan's `effects` record {by, summary, changes, why}."""
    cfg = {"use": "auto", "transitions": True, "text": True, "shots": True, "moves": True, "max_shot_effects": 2,
           "max_moves": MAX_MOVES, **(style.get("effects") or {})}
    use = str(cfg.get("use", "auto"))
    if use == "off" or not plan.get("segments"):
        return {}
    if (style.get("transitions") or {}).get("order") or plan.get("recipe"):
        cfg["transitions"] = False   # the style's own run of transitions, or a reference's cuts, stay as they are
    cfg["_shots"] = shots
    cfg["_eligible"] = elig = eligible(plan, style, by_id) if cfg.get("moves", True) else {}
    seen, cuts, texts = _context(plan, by_id)   # (the reel's shots as the AI sees them)
    if backend is None and use != "rules":
        # no AI: the planner's transitions, text and looks (from the style's palette) stand; `use: rules` asks for
        # rules. A signature move still comes when the reel plainly has what it needs
        moves = check_moves(_rule_moves(plan, by_id, elig), cfg) if cfg.get("moves", True) else []
        done = apply_moves(plan, moves, shots) if moves else []
        if not done:
            return {}
        rec = {"by": "rules", "summary": "a signature move chosen by rules", "changes": done,
               "why": [f"{m['id']}: {m['why']}" for m in moves if m.get("why")]}
        plan["effects"] = rec
        log("effects (rules): " + ", ".join(done))
        return rec
    raw, by = None, "rules"
    if backend is not None and use in ("auto", "ai"):
        import json
        from .ai import extract_json
        n_tr = sum(1 for c in cuts if c["now"] != "cut")
        prompt = PROMPT.format(
            shots=json.dumps(seen, ensure_ascii=False), cuts=json.dumps(cuts), texts=json.dumps(texts, ensure_ascii=False),
            n_tr=n_tr, tempo=round(float(plan.get("tempo") or 0)), style=style.get("name"),
            style_hint=("Its own transitions are fixed: leave transitions empty." if not cfg["transitions"] else
                        "The style favours: " + ", ".join(sorted({x for v in ((style.get("transitions") or {})
                                                              .get("palette") or {}).values() for x in (v or [])}))
                        + " (prefer these unless the footage clearly asks for another)."),
            lib_tr=_lib(TRANSITIONS), lib_tm=_lib(TEXT_MOTIONS), lib_tl=_lib(TEXT_LOOKS),
            lib_fx=_lib(SHOT_EFFECTS), max_fx=cfg["max_shot_effects"],
            lib_mv=_lib(MOVES) if cfg.get("moves", True) else "(none in this reel)", max_moves=cfg["max_moves"],
            eligible=json.dumps({k: v for k, v in elig.items() if v}) if elig else "{}",
            settings=json.dumps({k: v for k, v in MOVE_SETTINGS.items()}),
            tparams=json.dumps({k: {p: list(c) for p, c in v.items()} for k, v in TRANSITION_PARAMS.items()}))
        try:
            raw = extract_json(backend.ask(prompt, max_tokens=2500))
            by = "ai"
        except Exception as e:   # the AI is optional here: rules still choose
            debug(f"effects director: AI unavailable ({str(e)[:80]})")
            raw = None
    if not isinstance(raw, dict):
        raw, by = _rules(plan, by_id, cfg), "rules"
        if cfg.get("moves", True):
            raw["moves"] = _rule_moves(plan, by_id, elig)
        if cfg.get("shots", True):   # without an AI, a shot whose own vibe is strong gets the effect made for it
            segs = plan["segments"]
            for i, sg in enumerate(segs):
                a = (by_id.get(sg.get("shot_id")) or {}).get("ai") or {}
                vib = a.get("vibes") or {}
                if sg.get("panel") or not vib or len(raw["effects"]) >= int(cfg.get("max_shot_effects", 2)):
                    continue
                top = max(vib, key=vib.get)
                fid = {"nostalgic": "dust", "romantic": "dream", "serene": "glow" if str(a.get("time_of_day")) in
                       ("sunset", "golden-hour", "sunrise") else None}.get(top)
                if fid and vib[top] >= 0.8:
                    raw["effects"].append({"shot": i + 1, "id": fid, "amount": SHOT_EFFECTS[fid][3] * 0.8,
                                           "why": f"a {top} shot"})
    ch = _check(raw, plan, cuts, cfg)
    done = apply_choices(plan, ch, cfg)
    why = [f"cut {t['cut']}: {t.get('why')}" for t in raw.get("transitions") or [] if isinstance(t, dict) and t.get("why")]
    why += [f"shot {f['shot']}: {f['why']}" for f in ch["effects"] if f.get("why")]
    why += [f"{m['id']}: {m['why']}" for m in ch.get("moves") or [] if m.get("why")]
    rec = {"by": by, "summary": ch["summary"] or raw.get("summary", ""), "changes": done, "why": why[:20]}
    plan["effects"] = rec
    log(f"effects ({by}): " + (", ".join(done[:8]) or "nothing changed") + (" ..." if len(done) > 8 else ""))
    return rec
