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


def catalog() -> dict:
    """The whole library, for `tripshots effects`, MCP and the desktop pickers."""
    def rows(d, kind):
        return [{"id": k, "kind": kind, "energy": v[0], "mood": v[1], "suits": v[2],
                 **({"amount": v[3]} if len(v) > 3 else {})} for k, v in d.items()]
    return {"transitions": rows(TRANSITIONS, "transition"), "text_motions": rows(TEXT_MOTIONS, "text_motion"),
            "text_looks": rows(TEXT_LOOKS, "text_look"), "shot_effects": rows(SHOT_EFFECTS, "shot_effect")}


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
                      "place": s.get("place") or a.get("place")})
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

Answer with JSON only:
{{"transitions": [{{"cut": 3, "id": "push", "why": "..."}}],   (every cut you want to change; "cut" = plain cut)
 "texts": [{{"index": 1, "motion": "slam", "look": null, "why": "..."}}],
 "effects": [{{"shot": 5, "id": "glow", "amount": 0.5, "why": "..."}}],
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
        if e.get("beatless") and nx.get("beatless"):
            pick = ["dissolve"]
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
    for t in raw.get("transitions") or []:
        try:
            n, tid = int(t.get("cut")), str(t.get("id") or "cut")
        except (TypeError, ValueError):
            continue
        if n in ok_cuts and (tid == "cut" or tid in TRANSITIONS):
            tr[n] = tid
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
    return {"transitions": tr, "texts": texts, "effects": effects, "summary": str(raw.get("summary") or "")[:200]}


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
            if name == e.get("trans_out"):
                continue
            if name:
                d, prm = fit_transition(e, nx, name, plan.get("tempo"), None, side)
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
    return done


def direct(plan: dict, by_id: dict, style: dict, backend=None) -> dict:
    """Choose this reel's effects from the library (AI when there is one, else rules) and apply them.
    Returns the plan's `effects` record {by, summary, changes, why}."""
    cfg = {"use": "auto", "transitions": True, "text": True, "shots": True, "max_shot_effects": 2,
           **(style.get("effects") or {})}
    use = str(cfg.get("use", "auto"))
    if use == "off" or not plan.get("segments"):
        return {}
    if (style.get("transitions") or {}).get("order") or plan.get("recipe"):
        cfg["transitions"] = False   # the style's own run of transitions, or a reference's cuts, stay as they are
    shots, cuts, texts = _context(plan, by_id)
    if backend is None and use != "rules":
        return {}   # no AI: the planner's choices (from the style's palette) stand; `use: rules` asks for rules
    raw, by = None, "rules"
    if backend is not None and use in ("auto", "ai"):
        import json
        from .ai import extract_json
        n_tr = sum(1 for c in cuts if c["now"] != "cut")
        prompt = PROMPT.format(
            shots=json.dumps(shots, ensure_ascii=False), cuts=json.dumps(cuts), texts=json.dumps(texts, ensure_ascii=False),
            n_tr=n_tr, tempo=round(float(plan.get("tempo") or 0)), style=style.get("name"),
            style_hint=("Its own transitions are fixed: leave transitions empty." if not cfg["transitions"] else
                        "The style favours: " + ", ".join(sorted({x for v in ((style.get("transitions") or {})
                                                              .get("palette") or {}).values() for x in (v or [])}))
                        + " (prefer these unless the footage clearly asks for another)."),
            lib_tr=_lib(TRANSITIONS), lib_tm=_lib(TEXT_MOTIONS), lib_tl=_lib(TEXT_LOOKS),
            lib_fx=_lib(SHOT_EFFECTS), max_fx=cfg["max_shot_effects"])
        try:
            raw = extract_json(backend.ask(prompt, max_tokens=2500))
            by = "ai"
        except Exception as e:   # the AI is optional here: rules still choose
            debug(f"effects director: AI unavailable ({str(e)[:80]})")
            raw = None
    if not isinstance(raw, dict):
        raw, by = _rules(plan, by_id, cfg), "rules"
    ch = _check(raw, plan, cuts, cfg)
    done = apply_choices(plan, ch, cfg)
    why = [f"cut {t['cut']}: {t.get('why')}" for t in raw.get("transitions") or [] if isinstance(t, dict) and t.get("why")]
    why += [f"shot {f['shot']}: {f['why']}" for f in ch["effects"] if f.get("why")]
    rec = {"by": by, "summary": ch["summary"] or raw.get("summary", ""), "changes": done, "why": why[:20]}
    plan["effects"] = rec
    log(f"effects ({by}): " + (", ".join(done[:8]) or "nothing changed") + (" ..." if len(done) > 8 else ""))
    return rec
