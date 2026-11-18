"""Small, safe edits to a plan.json for agents (and `tripshots edit`), without breaking the beat grid.

Segments are numbered from 1, as on the storyboard. Shot content moves between beat slots; slot
timing (dur, out_start, level, the transition into the next slot) stays where it is.

ops:
  {"op": "swap", "segment": 3, "shot_id": "S012"}        put another shot in slot 3 ("in": 12.4 = play from there)
  {"op": "move", "from": 5, "to": 1}                     move slot 5's shot to the front
  {"op": "exchange", "a": 2, "b": 6}                     swap the shots of two slots
  {"op": "text", "type": "hook", "text": "Old Faithful at dawn"}   set (or add) hook / location / cta text
  {"op": "remove_text", "type": "location"}
  {"op": "transition", "segment": 2, "to": "whip"}       out of slot 2 (null = hard cut)
  {"op": "speed", "segment": 4, "speed": 0.5}             constant speed: 0.5 slow motion, 2 = twice as fast
  {"op": "ramp", "segment": 4, "ramp": "slam", "hit": 0.6} speed ramp (velocity, slam, bullet, rush, impact, surge),
                                                         hit = seconds into the slot; "points": [[0,1],[0.4,0.3],[1,1]]
                                                         for a custom curve; "ramp": null removes it
  {"op": "frame", "segment": 4, "subject_x": 0.3, "layout": "crop"}   reframe (0 = left, 1 = right)
  {"op": "frame", "segment": 4, "auto": true}                    framing back to automatic
  {"op": "set", "path": "motion.beat_punch", "value": 0.04}          anything else, by dotted path

On-screen text, by its number in plan["overlays"] (from 1; `texts` lists them):
  {"op": "add_text", "text": "Day 3", "start": 4.0, "duration": 2.0, "style": {"color": "#ffd23c", "size": 110}}
  {"op": "edit_text", "index": 2, "text": "...", "start": 1.0, "duration": 2.5,
   "style": {"font": "gf:Playfair Display:700", "size": 120, "color": "#ffffff", "position": "upper",
             "y": 0.3, "x": 0.5, "uppercase": true, "anim": "pop", "shadow": 0.8}}   a null style value drops it
  {"op": "delete_text", "index": 2}

The timeline (expert mode; times snap to whole frames, later text moves with the cut):
  {"op": "duration", "segment": 3, "dur": 1.6, "snap": "beat"}   lengthen / shorten a slot ("frame" or "beat")
  {"op": "slip", "segment": 3, "in": 12.4}                       which part of the clip plays (video)
  {"op": "split", "segment": 3, "at": 0.8}                       two slots, at seconds into the slot
  {"op": "delete", "segment": 3}
  {"op": "trim", "segment": 3, "side": "left", "by": 0.4}     shorten from the start (negative lengthens); "right" = the end
  {"op": "freeze", "segment": 3, "at": 0.8, "dur": 1.0}      hold the frame at 0.8 s into slot 3 for a second (cut in there)
  {"op": "reverse", "segment": 3, "on": true}               the clip plays backwards
  {"op": "duplicate", "segment": 3}
  {"op": "effect", "segment": 3, "id": "glow", "amount": 0.5}   a video effect on a shot (vfx.py; id null removes)
  {"op": "auto_effects"}                                     let the effects director choose again (fxlib.py)
  {"op": "remove_move", "segment": 3, "id": "flash_zoom"}    take a signature move off a shot
  {"op": "keyframe", "segment": 3, "t": 0.5, "zoom": 1.6, "x": 0.4, "y": 0.5, "ease": "out"}
      zoom 1.6x onto that point of the picture at 0.5 s into the slot (eased between keyframes; "remove": true
      drops the one at t, "clear": true all of them)
  {"op": "pip_add", "shot_id": "S040", "start": 3.0, "dur": 2.0, "x": 0.72, "y": 0.28, "scale": 0.4}
      another shot on top (x, y its centre, scale its width); {"op": "pip_edit", "index": 1, ...},
      {"op": "pip_delete", "index": 1}
  {"op": "log", "segment": 3, "profile": "dlog"}             flat log footage made normal (camlog.py; auto, or null = as filmed)
  {"op": "insert", "after": 2, "shot_id": "S040", "dur": 1.2}    a new slot (after 0 = at the start)
  {"op": "music", "start": 12.0, "gain_db": -3, "fade_out": 1.2}  where the song starts, its level

Colour:
  {"op": "grade", "look": "teal-orange", "strength": 0.8, "grain": 4, "vignette": true}   the reel's look ("none" = off)
  {"op": "adjust", "segment": 3, "exposure": 0.3, "contrast": 1.1, "saturation": 1.2, "warmth": 0.2, "tint": 0,
   "shadows": 0.2, "highlights": -0.3}   one shot's corrections on top of the look ("segment": "all" for every
   shot; a neutral or null value drops it; "graded": false shows the shot as filmed; "reset": true clears them)
  {"op": "layer", "segment": 3, "region": "sky", "exposure": -0.3, "saturation": 1.1, "hue": -8}
     a secondary on part of the frame (sky, subject, skin, greens, water, ground, edges); "on": false turns it off,
     "remove": true drops it; "segment": "all" for every shot
  {"op": "layers_auto", "segment": 3}            a shot's layers back to automatic ("all" for every shot)

Steadiness (a video shot):
  {"op": "stabilize", "segment": 3, "on": true}      take the shake out of a handheld clip ("segment": "all")

The person stays, the world changes (a video shot with a person in it):
  {"op": "backdrop", "segment": 1, "mode": "places"}   on each beat another place of the trip behind them
                                                        ("colour": flat colours from the shot; "off": none)
"""
from __future__ import annotations

from pathlib import Path

from .config import load_style
from .util import ReelError, read_json, write_json

SLOT_KEYS = {"dur", "out_start", "idx", "level", "drop", "trans_out", "trans_dur", "trans_params", "incam_out",
             "incam_in", "hero", "role", "hold"}   # a slot's place in the story stays when its shot changes
from .motion import TRANSITIONS as _MOTION_TRANSITIONS
TRANSITIONS = {None} | (set(_MOTION_TRANSITIONS) - {"cut", "fade"})   # every one in motion.py (fxlib describes them)


def _content(seg: dict) -> dict:
    return {k: v for k, v in seg.items() if k not in SLOT_KEYS}


def _put(seg: dict, content: dict) -> None:
    for k in [k for k in seg if k not in SLOT_KEYS]:
        del seg[k]
    seg.update(content)


def _plain_cut(segs: list, i: int) -> None:
    """A camera's own swing belongs to the footage that had it: with another shot in the slot the cut is a plain one."""
    if segs[i].pop("incam_out", None) is not None and i + 1 < len(segs):
        segs[i + 1].pop("incam_in", None)
    segs[i].pop("incam_in", None)


def _set_in(seg: dict, sh: dict, shots: dict, at) -> None:
    """Where a clip starts playing in its slot, chosen by hand: anywhere in the whole file (a long file is cut into
    several shots, and the part wanted may run past this one's edges)."""
    if seg.get("kind") != "video":
        return
    from .clippick import file_length
    length = file_length(shots, sh)
    use = float(seg["dur"]) * float(seg.get("speed", 1.0))
    if use > length:   # the slot is longer than the whole clip: a gentle slow-down, as when the planner fits it
        seg["speed"] = round(max(0.2, length / float(seg["dur"])), 3)
        use = float(seg["dur"]) * seg["speed"]
    seg["in"] = round(max(0.0, min(max(0.0, length - use), float(at))), 3)
    seg["track"] = False


def _slot(plan, n) -> int:
    i = int(n) - 1
    if not 0 <= i < len(plan["segments"]):
        raise ReelError(f"segment {n} doesn't exist (1..{len(plan['segments'])})")
    return i


def _shots(plan) -> dict:
    work = Path(plan.get("work") or ".")
    return {s["id"]: s for s in (read_json(work / "shots_scored.json", []) or [])}


def _refit(seg: dict, plan: dict, style: dict) -> None:
    """After a shot lands in a slot of another length: pick its best window for this slot's duration."""
    from .planner import _best_window
    sh = _shots(plan).get(seg.get("shot_id"))
    if sh and seg.get("kind") == "video" and not seg.get("panel") and not seg.get("freeze"):
        if seg.get("ramp"):
            from .planner import _set_ramp
            if _set_ramp(seg, sh, seg["ramp"], seg.get("ramp_hit")):
                return
            for k in ("ramp", "ramp_hit", "ramp_points"):
                seg.pop(k, None)
            seg["speed"] = 1.0
        speed = float(seg.get("speed", 1.0))
        if (sh["t1"] - sh["t0"]) < seg["dur"] * speed:
            speed = max(0.6, (sh["t1"] - sh["t0"]) / seg["dur"])
        seg["speed"] = round(speed, 3)
        seg["in"] = round(_best_window(sh, seg["dur"] * speed), 3)
        seg.pop("ramp", None)


def json_copy(d):
    import copy
    return copy.deepcopy(d)


def _refit_keep_in(seg: dict, plan: dict, style: dict) -> None:
    """A slot changed length: keep where its clip starts while the clip has enough footage, else slide back,
    else slow it down a little."""
    sh = _shots(plan).get(seg.get("shot_id"))
    if not sh or seg.get("kind") != "video" or "in" not in seg or seg.get("freeze"):
        return   # a held frame keeps its frame
    t0, t1 = float(sh["t0"]), float(sh["t1"])
    speed = float(seg.get("speed", 1.0))
    use = float(seg["dur"]) * speed
    if float(seg["in"]) + use <= t1:
        return
    if t1 - t0 >= use:
        seg["in"] = round(t1 - use, 3)
        return
    from .retime import SPEED_MIN
    seg["speed"] = round(max(SPEED_MIN, (t1 - t0) / float(seg["dur"])), 3)
    seg["in"] = round(t0, 3)


FPS = 30
TEXT_TYPES = ("hook", "location", "cta", "label", "caption", "text")
ANIMS = ("pop", "slide", "fade", "scale", "typewriter", "tracking", "rise", "cut")
POSITIONS = ("auto", "upper", "center", "lower")


def _frames(sec: float, least: int = 1) -> float:
    return round(max(least, round(float(sec) * FPS)) / FPS, 4)


def _color(v) -> list[int]:
    """'#ffd23c', 'ffd23c' or [255, 210, 60] -> [r, g, b]."""
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return [max(0, min(255, int(c))) for c in v[:3]]
    s = str(v).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return [int(s[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        raise ReelError(f"not a colour: {v} (use #rrggbb)")


def font_ok(name: str) -> bool:
    from . import fontlib
    from .typo import FONTS
    fam = fontlib.parse(name)
    return str(name).lower() in FONTS or bool(fam and fam[0] in fontlib.CATALOG)


def _text_style(cur: dict, new: dict) -> dict:
    """A text's own lettering with the asked changes, checked (a null value drops the key: the style's default)."""
    out = dict(cur or {})
    for k, v in (new or {}).items():
        if v is None or v == "":
            out.pop(k, None)
            continue
        if k == "font":
            if not font_ok(v):
                raise ReelError(f"unknown font {v} (a bundled name, or gf:Family:weight from the font list)")
            out[k] = str(v)
        elif k in ("color", "lead_color"):
            out[k] = _color(v)
        elif k == "colors":
            out[k] = [_color(c) for c in v] if isinstance(v, list) and v else None
        elif k in ("size", "lead_size"):
            out[k] = max(24, min(400, int(v)))
        elif k in ("x", "y"):
            out[k] = round(max(0.0, min(1.0, float(v))), 4)
        elif k == "position":
            if v not in POSITIONS:
                raise ReelError(f"position is one of {', '.join(POSITIONS)}")
            out[k] = v
            out.pop("y", None)   # a band, not a height
        elif k == "anim":
            if v not in ANIMS:
                raise ReelError(f"animation is one of {', '.join(ANIMS)}")
            out[k] = v
        elif k == "look":
            from .typo import LOOKS
            if v not in LOOKS:
                raise ReelError(f"text look is one of {', '.join(LOOKS)} (or null)")
            out[k] = v
        elif k in ("uppercase", "fixed"):
            out[k] = bool(v)
        elif k in ("line_gap", "shadow", "fit", "exit"):
            out[k] = round(float(v), 3)
        elif k == "fill":
            out[k] = "picture" if v in ("picture", True) else None
        elif k == "lead_font":
            if not font_ok(v):
                raise ReelError(f"unknown font {v}")
            out[k] = str(v)
        else:
            raise ReelError(f"text style has no {k}")
    return {k: v for k, v in out.items() if v is not None}


def _overlay(plan: dict, n) -> int:
    ovs = plan.get("overlays") or []
    i = int(n) - 1
    if not 0 <= i < len(ovs) or ovs[i].get("type") not in TEXT_TYPES:
        raise ReelError(f"text {n} doesn't exist")
    return i


def texts(plan: dict) -> list[dict]:
    """Every line of on-screen text with its number (for edit_text / delete_text)."""
    out = []
    for i, o in enumerate(plan.get("overlays") or []):
        if o.get("type") not in TEXT_TYPES:
            continue
        text = o.get("text") or " ".join(x for x in (o.get("main"), o.get("sub")) if x)
        out.append({"index": i + 1, "type": o["type"], "text": text, "start": round(float(o.get("start", 0)), 3),
                    "duration": round(float(o.get("duration", 0)), 3), "style": o.get("style") or {},
                    "lead": o.get("lead"), "recipe": o.get("recipe"), "motion": o.get("motion")})
    return out


def retime(plan: dict) -> None:
    """Slots back to back from 0 (after a slot was added, removed or changed length); text past the end is cut."""
    t = 0.0
    for k, s in enumerate(plan["segments"]):
        s["out_start"], s["idx"] = round(t, 4), k
        t += float(s["dur"])
    plan["duration"] = round(t, 4)
    keep = []
    for o in plan.get("overlays") or []:
        st = float(o.get("start", 0))
        if st >= t - 0.1:
            continue
        if "duration" in o:
            o["duration"] = round(min(float(o["duration"]), t - st), 4)
        keep.append(o)
    plan["overlays"] = keep
    pips = []
    for pp in plan.get("pips") or []:
        if float(pp.get("start", 0)) < t - 0.3:
            pp["dur"] = round(min(float(pp["dur"]), t - float(pp["start"])), 4)
            pips.append(pp)
    if "pips" in plan:
        plan["pips"] = pips
    if plan.get("freeze") and float(plan["freeze"].get("t", 0)) >= t:
        plan.pop("freeze")
    if plan["segments"]:
        plan["segments"][-1]["trans_out"] = None


def _shift_text(plan: dict, after: float, by: float) -> None:
    """Text that starts after a cut moves with it. Subtitles and lyrics stay with the song, which doesn't move."""
    for o in plan.get("overlays") or []:
        if o.get("type") == "caption" or o.get("recipe") in ("lyric", "subtitles"):
            continue
        if o.get("type") == "hook" and after < 0.5 and float(o.get("start", 0)) < 0.5:
            continue  # a shot put in front: the hook still opens the reel
        if float(o.get("start", 0)) >= after - 0.02:
            o["start"] = round(max(0.0, float(o["start"]) + by), 4)


def _snap_beat(plan: dict, t: float) -> float:
    beats = [float(b) for b in plan.get("beats") or []]
    return min(beats, key=lambda b: abs(b - t)) if beats else t


def _regrade(plan: dict, shots: dict) -> None:
    """New grading LUTs for every shot in the plan's look (cached per-shot colourist notes, no new AI calls);
    grain and vignette set by hand stay."""
    from . import grade
    g = dict(plan.get("grade") or {})
    if g.get("look") in (None, "none", "off"):
        return
    grade.grade_plan(plan, shots, {"look": g.get("look"), "strength": g.get("strength", 0.75), "ai": False,
                                   "match": g.get("match")}, None, Path(plan.get("work") or "."))
    for k in ("grain", "vignette"):
        if g.get(f"{k}_set"):
            plan["grade"][k], plan["grade"][f"{k}_set"] = g[k], True
    if g.get("why") and not plan["grade"].get("why"):
        plan["grade"]["why"] = g["why"]


UNDO_KEEP = 60


def _history(plan_path: Path) -> Path:
    from .config import HOME
    from .util import short_hash
    return HOME / "undo" / short_hash(str(Path(plan_path).resolve()), 16)


def _push(d: Path, text: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    have = sorted(d.glob("*.json"))
    n = int(have[-1].stem) + 1 if have else 1
    (d / f"{n:06d}.json").write_text(text)
    for old in have[:max(0, len(have) + 1 - UNDO_KEEP)]:
        old.unlink(missing_ok=True)


def _pop(d: Path) -> str | None:
    have = sorted(d.glob("*.json")) if d.exists() else []
    if not have:
        return None
    text = have[-1].read_text()
    have[-1].unlink()
    return text


def history(plan_path: Path) -> dict:
    h = _history(plan_path)
    return {"undo": len(list((h / "undo").glob("*.json"))) if (h / "undo").exists() else 0,
            "redo": len(list((h / "redo").glob("*.json"))) if (h / "redo").exists() else 0}


def step(plan_path: Path, back: bool = True) -> dict:
    """Undo (back) or redo the last edit of a plan."""
    plan_path = Path(plan_path)
    h = _history(plan_path)
    text = _pop(h / ("undo" if back else "redo"))
    if text is None:
        raise ReelError("nothing to undo" if back else "nothing to redo")
    _push(h / ("redo" if back else "undo"), plan_path.read_text())
    plan_path.write_text(text)
    plan = read_json(plan_path)
    from .framing import use_plan
    from .text import storyboard
    use_plan(plan)
    storyboard(plan, _shots(plan), plan_path.with_name(plan_path.name.replace(".plan.json", ".storyboard.jpg")))
    return {"plan": str(plan_path), "changes": ["undone" if back else "redone"], **history(plan_path)}


def apply(plan_path: Path, edits: list[dict], undo: bool = True) -> dict:
    plan_path = Path(plan_path)
    plan = read_json(plan_path)
    if not plan:
        raise ReelError(f"could not read {plan_path}")
    as_was = plan_path.read_text()   # for undo
    style = load_style(plan.get("style"))
    from .framing import use_plan
    use_plan(plan)     # a horizontal or letterboxed plan: new shots are framed for its picture
    shots = _shots(plan)
    segs = plan["segments"]
    done, regrade = [], False
    for ed in edits:
        op = ed.get("op")
        if op == "swap":
            i = _slot(plan, ed["segment"])
            sh = shots.get(ed["shot_id"])
            if not sh:
                raise ReelError(f"unknown shot {ed['shot_id']} (see the plan's shot candidates)")
            from .planner import _shot_fields
            e, _ = _shot_fields(sh, segs[i]["dur"], segs[i].get("level", "mid"), style, i)
            _put(segs[i], e)
            _plain_cut(segs, i)
            if ed.get("in") is not None:
                _set_in(segs[i], sh, shots, ed["in"])
            regrade = True
            done.append(f"slot {i + 1} -> {sh['id']}")
        elif op in ("move", "exchange"):
            a, b = (_slot(plan, ed["from"]), _slot(plan, ed["to"])) if op == "move" else \
                (_slot(plan, ed["a"]), _slot(plan, ed["b"]))
            contents = [_content(s) for s in segs]
            before = [s.get("shot_id") for s in segs]
            if op == "move":
                c = contents.pop(a)
                contents.insert(b, c)
            else:
                contents[a], contents[b] = contents[b], contents[a]
            for s, c in zip(segs, contents):
                _put(s, c)
            for k in range(min(a, b), max(a, b) + 1):
                if segs[k].get("shot_id") != before[k]:
                    _plain_cut(segs, k)
                _refit(segs[k], plan, style)
            done.append(f"{op} {a + 1} <-> {b + 1}")
        elif op == "text":
            typ, text = ed.get("type", "hook"), str(ed["text"]).strip()
            ovs = [o for o in plan.setdefault("overlays", []) if o.get("type") == typ]
            if ovs:
                ovs[0]["text"] = text
                for k in ("main", "sub"):
                    ovs[0].pop(k, None)
            else:
                start = 0.1 if typ == "hook" else (max(0.0, plan["duration"] - 2.2) if typ == "cta" else 1.0)
                plan["overlays"].append({"type": typ, "text": text, "start": start, "duration": 2.0})
            if typ == "hook" and len(text.split()) > 7:
                done.append("note: hooks read best at 7 words or fewer")
            done.append(f"{typ} text: {text}")
        elif op == "remove_text":
            n0 = len(plan.get("overlays", []))
            plan["overlays"] = [o for o in plan.get("overlays", []) if o.get("type") != ed["type"]]
            done.append(f"removed {n0 - len(plan['overlays'])} {ed['type']} overlay(s)")
        elif op == "transition":
            i = _slot(plan, ed["segment"])
            to = ed.get("to")
            if to not in TRANSITIONS:
                raise ReelError(f"unknown transition {to} ({', '.join(t for t in TRANSITIONS if t)}, or null)")
            segs[i].update({"trans_out": to, "trans_params": ed.get("params", {})})
            segs[i].pop("incam_out", None)
            if not to:
                segs[i]["trans_dur"] = 0.0
            elif i + 1 < len(segs):
                from .planner import fit_transition
                d, prm = fit_transition(segs[i], segs[i + 1], to, plan.get("tempo"), ed.get("beats"))
                segs[i]["trans_dur"] = d
                segs[i]["trans_params"] = {**prm, **(ed.get("params") or {})}
            done.append(f"slot {i + 1} out: {to or 'hard cut'}")
        elif op == "speed":
            from .retime import SPEED_MAX, SPEED_MIN
            i = _slot(plan, ed["segment"])
            if segs[i].get("kind") != "video":
                raise ReelError(f"slot {i + 1} isn't a video clip: speed only applies to video")
            want = max(SPEED_MIN, min(SPEED_MAX, float(ed["speed"])))
            for k in ("ramp", "ramp_hit", "ramp_points"):
                segs[i].pop(k, None)
            segs[i]["speed"] = want
            _refit(segs[i], plan, style)
            got = segs[i]["speed"]
            done.append(f"slot {i + 1} speed {got:g}x" + ("" if abs(got - want) < 0.01 else
                                                         f" (asked {want:g}x; the clip is too short for more)"))
        elif op == "ramp":
            from .retime import KINDS
            i = _slot(plan, ed["segment"])
            seg = segs[i]
            kind, pts = ed.get("ramp"), ed.get("points")
            if seg.get("kind") != "video" or seg.get("panel"):
                raise ReelError(f"slot {i + 1} isn't a single video clip: ramps only apply to video")
            if not kind and not pts:
                for k in ("ramp", "ramp_hit", "ramp_points"):
                    seg.pop(k, None)
                seg["speed"] = 1.0
                _refit(seg, plan, style)
                done.append(f"slot {i + 1} ramp removed")
                continue
            if kind and kind not in KINDS:
                raise ReelError(f"unknown ramp {kind} ({', '.join(KINDS)}, or points)")
            from .planner import _set_ramp
            sh = shots.get(seg.get("shot_id"))
            old = dict(seg)
            if pts:
                seg["ramp_points"] = [[float(u), float(v)] for u, v in pts]
            else:
                seg.pop("ramp_points", None)
            hit = ed.get("hit")
            if hit is not None and not 0 <= float(hit) <= seg["dur"]:
                raise ReelError(f"hit must be between 0 and {seg['dur']} (seconds into slot {i + 1})")
            if not sh or not _set_ramp(seg, sh, kind or "custom", None if hit is None else float(hit)):
                seg.clear()
                seg.update(old)
                raise ReelError(f"slot {i + 1}'s clip is too short for a {kind or 'custom'} ramp; swap in a longer clip")
            if pts:
                seg["ramp_points"] = [[float(u), float(v)] for u, v in pts]
            seg["track"] = False
            done.append(f"slot {i + 1} {kind or 'custom'} ramp")
        elif op == "frame":
            i = _slot(plan, ed["segment"])
            if segs[i].get("panel"):
                raise ReelError(f"slot {i + 1} is a split screen: to show one shot full screen there, swap it "
                                "(op swap with a shot id)")
            if ed.get("auto"):   # back to automatic: the render places the window on what plays (compose.py)
                segs[i].pop("frame_by", None)
                done.append(f"slot {i + 1} framed automatically")
                continue
            for k in ("subject_x", "layout", "pan_from", "pan_to"):
                if k in ed:
                    segs[i][k] = ed[k]
            if "subject_x" in ed:   # placed by hand: the automatic framing leaves it where it is
                segs[i]["frame_by"] = "hand"
            if "subject_x" in ed and isinstance(segs[i].get("subject"), dict):
                sb = segs[i]["subject"]
                w = sb.get("x1", 0.6) - sb.get("x0", 0.4)
                sb.update({"cx": ed["subject_x"], "x0": max(0, ed["subject_x"] - w / 2),
                           "x1": min(1, ed["subject_x"] + w / 2)})
            done.append(f"slot {i + 1} reframed")
        elif op == "set":
            cur = plan
            keys = str(ed["path"]).split(".")
            for k in keys[:-1]:
                cur = cur[int(k) - 1] if isinstance(cur, list) else cur.setdefault(k, {})
            last = keys[-1]
            if isinstance(cur, list):
                cur[int(last) - 1] = ed["value"]
            else:
                cur[last] = ed["value"]
            done.append(f"{ed['path']} = {ed['value']}")
        elif op == "add_text":
            text = str(ed.get("text") or "").strip()
            if not text:
                raise ReelError("add_text needs some text")
            total = sum(float(s["dur"]) for s in segs)
            start = max(0.0, min(float(ed.get("start", 0.0)), total - 0.2))
            o = {"type": ed.get("type") if ed.get("type") in TEXT_TYPES else "text", "text": text,
                 "start": round(start, 4), "duration": round(min(float(ed.get("duration", 2.0)), total - start), 4),
                 "style": _text_style({}, ed.get("style") or {"position": "center"}), "user": True}
            plan.setdefault("overlays", []).append(o)
            done.append(f"text {len(plan['overlays'])} added: {text}")
        elif op == "edit_text":
            i = _overlay(plan, ed["index"])
            o = plan["overlays"][i]
            if "style" in ed or "motion" in ed:
                if o["type"] == "location":   # its own lettering: drawn as a plain title from now on
                    o["text"] = o.get("text") or " ".join(x for x in (o.get("main"), o.get("sub")) if x)
                    o["type"] = "text"
                    for k in ("main", "sub", "coords", "gps"):
                        o.pop(k, None)
                o["style"] = _text_style(o.get("style") or {}, ed.get("style") or {})
            if "motion" in ed:
                if ed["motion"]:
                    o["motion"] = str(ed["motion"])
                else:
                    o.pop("motion", None)
            if "text" in ed:
                t = str(ed["text"]).strip()
                if not t:
                    raise ReelError("a text can't be empty: delete it instead")
                o["text"] = t
                for k in ("main", "sub"):
                    o.pop(k, None)
                o.pop("clone_of", None)
            total = sum(float(s["dur"]) for s in segs)
            if "start" in ed:
                o["start"] = round(max(0.0, min(float(ed["start"]), total - 0.2)), 4)
            if "duration" in ed or "start" in ed:
                o["duration"] = round(max(0.2, min(float(ed.get("duration", o.get("duration", 2.0))),
                                                   total - float(o["start"]))), 4)
            if "lead" in ed:
                if ed["lead"]:
                    o["lead"] = str(ed["lead"])
                else:
                    o.pop("lead", None)
            o["user"] = True
            done.append(f"text {i + 1} changed")
        elif op == "delete_text":
            i = _overlay(plan, ed["index"])
            gone = plan["overlays"].pop(i)
            done.append(f"text {i + 1} removed: {gone.get('text') or gone.get('main')}")
        elif op == "duration":
            i = _slot(plan, ed["segment"])
            s = segs[i]
            if s.get("panel"):
                raise ReelError(f"slot {i + 1} is a split screen: its panels are timed to its length")
            dur = _frames(ed["dur"], 4)
            if ed.get("snap") == "beat":
                end = _snap_beat(plan, float(s.get("out_start", 0)) + dur)
                dur = _frames(end - float(s.get("out_start", 0)), 4)
            old = float(s["dur"])
            s["dur"] = dur
            if s.get("ramp"):
                from .planner import _set_ramp
                sh = shots.get(s.get("shot_id"))
                if not sh or not _set_ramp(s, sh, s["ramp"], min(float(s.get("ramp_hit") or dur / 2), dur * 0.8)):
                    for k in ("ramp", "ramp_hit", "ramp_points"):
                        s.pop(k, None)
                    s["speed"] = 1.0
                    _refit(s, plan, style)
            else:
                _refit_keep_in(s, plan, style)
            _shift_text(plan, float(s.get("out_start", 0)) + old, dur - old)
            retime(plan)
            done.append(f"slot {i + 1} lasts {dur:.2f}s (was {old:.2f}s)")
        elif op == "slip":
            i = _slot(plan, ed["segment"])
            s = segs[i]
            sh = shots.get(s.get("shot_id"))
            if s.get("kind") != "video" or not sh:
                raise ReelError(f"slot {i + 1} isn't a video clip")
            _set_in(s, sh, shots, ed["in"])
            done.append(f"slot {i + 1} plays from {s['in']:.2f}s of its clip")
        elif op == "split":
            i = _slot(plan, ed["segment"])
            s = segs[i]
            if s.get("panel") or s.get("ramp"):
                raise ReelError(f"slot {i + 1} has a split screen or a speed ramp: it can't be cut in two")
            at = _frames(ed["at"], 2)
            if not 2 / FPS <= at <= float(s["dur"]) - 2 / FPS:
                raise ReelError(f"cut slot {i + 1} somewhere between 0.07 and {float(s['dur']) - 0.07:.2f}s")
            b = json_copy(s)
            s["dur"], b["dur"] = at, _frames(float(s["dur"]) - at, 2)
            if s.get("kind") == "video" and "in" in s and not s.get("freeze"):
                if s.get("reverse"):   # backwards: the first piece shows the later part of the window
                    s["in"] = round(float(s["in"]) + float(b["dur"]) * float(s.get("speed", 1.0)), 3)
                else:
                    b["in"] = round(float(s["in"]) + at * float(s.get("speed", 1.0)), 3)
            s.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
            s.pop("incam_out", None)
            b.pop("incam_in", None)
            b.pop("hold", None)
            segs.insert(i + 1, b)
            retime(plan)
            done.append(f"slot {i + 1} cut in two at {at:.2f}s")
        elif op == "trim":   # take time off (or add it back to) one end of a slot; the clip's other end stays put
            i = _slot(plan, ed["segment"])
            s = segs[i]
            if s.get("panel") or s.get("ramp"):
                raise ReelError(f"slot {i + 1} has a split screen or a speed ramp: change its length instead")
            side, by = ed.get("side", "right"), float(ed.get("by", 0))
            if side not in ("left", "right"):
                raise ReelError("trim side is left or right")
            old = float(s["dur"])
            dur = _frames(old - by, 4)
            by = old - dur
            speed = 1.0 if s.get("freeze") else float(s.get("speed", 1.0))
            moves_in = (side == "left") != bool(s.get("reverse"))   # backwards, the clip's start is the slot's end
            if moves_in and s.get("kind") == "video" and "in" in s and not s.get("freeze"):
                sh = shots.get(s.get("shot_id"))
                lo = float(sh["t0"]) if sh else 0.0
                new_in = float(s["in"]) + by * speed
                if new_in < lo - 1e-3:   # no footage before the clip's start: lengthen only as far as there is
                    dur = _frames(old + (float(s["in"]) - lo) / speed, 4)
                    by, new_in = old - dur, lo
                s["in"] = round(new_in, 3)
                s["track"] = False
            s["dur"] = dur
            if not moves_in:
                _refit_keep_in(s, plan, style)
            _shift_text(plan, float(s.get("out_start", 0)) + old, -by)
            retime(plan)
            done.append(f"slot {i + 1} trimmed at the {'start' if side == 'left' else 'end'}: {dur:.2f}s (was {old:.2f}s)")
        elif op == "freeze":   # hold one frame: the slot's frame at `at` seconds, for `dur` seconds, cut in there
            i = _slot(plan, ed["segment"])
            s = segs[i]
            if s.get("kind") != "video" or s.get("panel") or s.get("ramp"):
                raise ReelError(f"slot {i + 1} isn't a plain video clip: only a clip's frame can be held")
            at = _frames(ed.get("at", 0.0), 0) if float(ed.get("at", 0.0)) > 0 else 0.0
            hold = _frames(ed.get("dur", 1.0), 4)
            if not 0 <= at <= float(s["dur"]):
                raise ReelError(f"freeze somewhere between 0 and {float(s['dur']):.2f}s into slot {i + 1}")
            speed = float(s.get("speed", 1.0))
            src_t = float(s.get("in", 0.0)) + (float(s["dur"]) - at if s.get("reverse") else at) * speed
            fz = {k: v for k, v in json_copy(s).items() if k not in ("incam_in", "incam_out", "hold", "reverse")}
            fz.update({"dur": hold, "in": round(src_t, 3), "freeze": True, "speed": 1.0, "track": False,
                       "trans_out": None, "trans_dur": 0.0, "trans_params": {}, "role": None})
            fz.pop("stabilize", None)
            if 2 / FPS <= at <= float(s["dur"]) - 2 / FPS:   # in the middle: cut the clip there, the hold between
                b = json_copy(s)
                s["dur"], b["dur"] = at, _frames(float(s["dur"]) - at, 2)
                if "in" in s and not s.get("reverse"):
                    b["in"] = round(float(s["in"]) + at * speed, 3)
                elif s.get("reverse"):
                    s["in"] = round(float(s["in"]) + float(b["dur"]) * speed, 3)
                s.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
                s.pop("incam_out", None)
                b.pop("incam_in", None)
                b.pop("hold", None)
                segs[i + 1:i + 1] = [fz, b]
                start = float(s.get("out_start", 0)) + at
            elif at < 2 / FPS:   # at its start: the hold comes first
                segs.insert(i, fz)
                start = float(s.get("out_start", 0))
            else:                # at its end
                segs.insert(i + 1, fz)
                start = float(s.get("out_start", 0)) + float(s["dur"])
            _shift_text(plan, start, hold)
            retime(plan)
            done.append(f"frame held for {hold:.2f}s in slot {i + 1}")
        elif op == "reverse":   # the slot's window of the clip plays backwards
            i = _slot(plan, ed["segment"])
            s = segs[i]
            if s.get("kind") != "video" or s.get("panel") or s.get("ramp") or s.get("freeze"):
                raise ReelError(f"slot {i + 1} isn't a plain video clip: only a moving clip can play backwards")
            if ed.get("on", not s.get("reverse")):
                s["reverse"] = True
            else:
                s.pop("reverse", None)
            s["track"] = False
            done.append(f"slot {i + 1} " + ("plays backwards" if s.get("reverse") else "plays forwards"))
        elif op == "effect":   # a video effect on one shot (vfx.py; "id": null removes it)
            from .vfx import EFFECTS
            targets = range(len(segs)) if ed.get("segment") == "all" else [_slot(plan, ed["segment"])]
            fid = ed.get("id")
            if fid and fid not in EFFECTS:
                raise ReelError(f"unknown effect {fid} ({', '.join(EFFECTS)}, or null)")
            for i in targets:
                if segs[i].get("panel"):
                    continue
                if fid:
                    amt = float(ed.get("amount", (segs[i].get("effect") or {}).get("amount", 0.6)))
                    segs[i]["effect"] = {"id": fid, "amount": round(max(0.0, min(1.0, amt)), 2)}
                else:
                    segs[i].pop("effect", None)
            done.append((f"{fid} on " if fid else "no effect on ") +
                        ("every shot" if ed.get("segment") == "all" else f"slot {targets[0] + 1}"))
        elif op == "log":   # flat log footage: which camera's curve makes it normal (camlog.py); null = as filmed
            from .camlog import PROFILES, detect
            prof = ed.get("profile")
            targets = range(len(segs)) if ed.get("segment") == "all" else [_slot(plan, ed["segment"])]
            if prof not in PROFILES and prof not in (None, "auto"):
                raise ReelError(f"camera log is one of {', '.join(PROFILES)}, auto, or null")
            n = 0
            for i in targets:
                for c in (segs[i].get("clips") or [segs[i]]):
                    if c.get("kind") != "video":
                        continue
                    sh = shots.get(c.get("shot_id")) or {}
                    c["log"] = (detect(sh) if sh else None) if prof == "auto" else prof
                    n += 1
            regrade = True
            done.append(f"camera log {prof or 'off'} on " + (f"{n} clips" if ed.get("segment") == "all" else f"slot {targets[0] + 1}"))
        elif op == "keyframe":   # zoom and position over time inside one shot (motion.apply_keys)
            i = _slot(plan, ed["segment"])
            sg = segs[i]
            if sg.get("panel"):
                raise ReelError(f"slot {i + 1} is a split screen: keyframe its panels' shots instead")
            keys = [dict(k) for k in sg.get("keys") or []]
            if ed.get("clear"):
                keys = []
            else:
                t = _frames(max(0.0, min(float(sg["dur"]), float(ed.get("t", 0.0)))), 0)
                keys = [k for k in keys if abs(float(k["t"]) - t) > 0.5 / FPS]
                if not ed.get("remove"):
                    from .motion import EASES
                    k = {"t": t, "zoom": round(max(1.0, min(4.0, float(ed.get("zoom", 1.0)))), 3),
                         "x": round(max(0.0, min(1.0, float(ed.get("x", 0.5)))), 4),
                         "y": round(max(0.0, min(1.0, float(ed.get("y", 0.5)))), 4)}
                    if ed.get("ease") in EASES:
                        k["ease"] = ed["ease"]
                    keys.append(k)
            keys.sort(key=lambda k: k["t"])
            if keys:
                sg["keys"] = keys
            else:
                sg.pop("keys", None)
            done.append(f"slot {i + 1}: {len(keys)} keyframe(s)")
        elif op == "pip_add":   # another shot on top, in a corner (render.Pips)
            sh = shots.get(ed.get("shot_id"))
            if not sh:
                raise ReelError(f"unknown shot {ed.get('shot_id')} (see the plan's shot candidates)")
            total = sum(float(x["dur"]) for x in segs)
            start = _frames(max(0.0, min(float(ed.get("start", 0.0)), total - 0.5)), 0)
            dur = _frames(max(0.5, min(float(ed.get("dur", 2.0)), total - start)), 4)
            pip = {"shot_id": sh["id"], "kind": sh["kind"], "src": sh["src"], "start": start, "dur": dur,
                   "x": round(float(ed.get("x", 0.72)), 4), "y": round(float(ed.get("y", 0.28)), 4),
                   "scale": round(max(0.15, min(1.0, float(ed.get("scale", 0.4)))), 3),
                   "src_w": sh.get("w"), "src_h": sh.get("h"), "thumb": sh.get("thumb")}
            if sh["kind"] == "video":
                from .planner import _best_window
                pip.update({"in": round(_best_window(sh, dur), 3), "hdr": sh.get("hdr", False),
                            "transfer": sh.get("transfer")})
            else:
                pip["still"] = sh.get("still") or sh["src"]
            plan.setdefault("pips", []).append(pip)
            done.append(f"picture in picture {len(plan['pips'])}: {sh['id']} at {start:.2f}s")
        elif op in ("pip_edit", "pip_delete"):
            pips = plan.get("pips") or []
            k = int(ed.get("index", 0)) - 1
            if not 0 <= k < len(pips):
                raise ReelError(f"picture in picture {ed.get('index')} doesn't exist (1..{len(pips)})")
            if op == "pip_delete":
                pips.pop(k)
                done.append(f"picture in picture {k + 1} removed")
            else:
                pp = pips[k]
                total = sum(float(x["dur"]) for x in segs)
                for key, lo, hi in (("x", 0.0, 1.0), ("y", 0.0, 1.0), ("scale", 0.15, 1.0), ("round", 0.0, 0.5)):
                    if key in ed:
                        pp[key] = round(max(lo, min(hi, float(ed[key]))), 4)
                if "start" in ed:
                    pp["start"] = _frames(max(0.0, min(float(ed["start"]), total - 0.5)), 0)
                if "dur" in ed or "start" in ed:
                    pp["dur"] = _frames(max(0.5, min(float(ed.get("dur", pp["dur"])), total - pp["start"])), 4)
                done.append(f"picture in picture {k + 1} changed")
            plan["pips"] = pips
        elif op == "remove_move":   # take a signature move off a shot (fxlib.MOVES)
            from . import fxlib
            i = _slot(plan, ed["segment"])
            if not fxlib.remove_move(plan, i + 1, str(ed.get("id"))):
                raise ReelError(f"shot {i + 1} has no {ed.get('id')}")
            done.append(f"shot {i + 1}: {fxlib.MOVE_NAMES.get(ed['id'], ed['id']).lower()} removed")
        elif op == "auto_effects":   # the effects director again (fxlib.direct): AI if there is one, else rules
            from . import fxlib
            from .ai import get_backend
            try:
                backend = get_backend(ed.get("backend"))
            except Exception:
                backend = None
            for sg in segs:   # what it chose before goes; what you set by hand stays
                if (sg.get("effect") or {}).get("auto"):
                    sg.pop("effect", None)
            fxlib.clear_moves(plan)
            st = {**style, "effects": {**(style.get("effects") or {}), "use": "auto" if backend else "rules",
                                       **{k: ed[k] for k in ("transitions", "text", "shots", "moves") if k in ed}}}
            rec = fxlib.direct(plan, shots, st, backend, list(shots.values()))
            done.append(f"effects chosen by {rec.get('by', 'rules')}: " + (", ".join(rec.get("changes") or []) or "no change"))
        elif op == "delete":
            i = _slot(plan, ed["segment"])
            if len(segs) == 1:
                raise ReelError("a reel needs at least one shot")
            gone = segs.pop(i)
            if i > 0 and segs[i - 1].pop("incam_out", None) is not None:
                segs[i - 1]["trans_out"] = None   # its swing led into the slot that's gone
            if i < len(segs):
                segs[i].pop("incam_in", None)
            _shift_text(plan, float(gone.get("out_start", 0)) + float(gone["dur"]), -float(gone["dur"]))
            retime(plan)
            done.append(f"slot {i + 1} removed")
        elif op == "duplicate":
            i = _slot(plan, ed["segment"])
            c = json_copy(segs[i])
            c.pop("incam_in", None)
            segs[i].pop("incam_out", None)
            segs.insert(i + 1, c)
            _shift_text(plan, float(segs[i].get("out_start", 0)) + float(c["dur"]), float(c["dur"]))
            retime(plan)
            done.append(f"slot {i + 1} repeated")
        elif op == "insert":
            after = int(ed.get("after", len(segs)))
            if not 0 <= after <= len(segs):
                raise ReelError(f"after must be 0..{len(segs)}")
            sh = shots.get(ed.get("shot_id"))
            if not sh:
                raise ReelError(f"unknown shot {ed.get('shot_id')} (see the plan's shot candidates)")
            from .planner import _shot_fields
            dur = _frames(ed.get("dur", 1.5), 4)
            e, _ = _shot_fields(sh, dur, "mid", style, after)
            new = {**e, "dur": dur, "level": "mid", "drop": False, "trans_out": None, "trans_dur": 0.0,
                   "trans_params": {}, "role": None}
            if ed.get("in") is not None:
                _set_in(new, sh, shots, ed["in"])
            at = sum(float(s["dur"]) for s in segs[:after])
            segs.insert(after, new)
            _shift_text(plan, at, dur)
            retime(plan)
            regrade = True
            done.append(f"{sh['id']} added as slot {after + 1}")
        elif op == "grade":   # the whole reel's look
            g = dict(plan.get("grade") or {})
            look = ed.get("look", g.get("look"))
            if look in (None, "none", "off"):
                plan["grade"] = {"look": "none"}
                for sg in segs:
                    for c in (sg.get("clips") or [sg]):
                        c.pop("lut", None)
                done.append("no colour grade")
                continue
            from .grade import list_looks
            if look not in list_looks():
                raise ReelError(f"unknown look {look} ({', '.join(list_looks())}, or none)")
            g["look"] = look
            if "strength" in ed:
                g["strength"] = round(max(0.0, min(1.0, float(ed["strength"]))), 2)
            if look != (plan.get("grade") or {}).get("look"):
                g.pop("grain_set", None)
                g.pop("vignette_set", None)
                g.pop("why", None)
                if list_looks()[look].get("builtin"):
                    g.pop("match", None)   # "take every shot fully into it" belongs to a learned look
            if "grain" in ed:
                g["grain"], g["grain_set"] = max(0, min(12, int(ed["grain"]))), True
            if "vignette" in ed:
                g["vignette"], g["vignette_set"] = bool(ed["vignette"]), True
            plan["grade"] = g
            _regrade(plan, shots)
            done.append(f"look {look} at {int(round(float(plan['grade'].get('strength', 0.75)) * 100))}%")
        elif op == "adjust":  # one shot's own colour (or every shot's: "segment": "all")
            from .fx import ADJUST
            targets = range(len(segs)) if ed.get("segment") == "all" else [_slot(plan, ed["segment"])]
            for i in targets:
                for c in (segs[i].get("clips") or [segs[i]]):
                    adj = dict(c.get("adjust") or {})
                    for k, (lo, hi, neutral) in ADJUST.items():
                        if k in ed:
                            v = ed[k]
                            if v is None or abs(float(v) - neutral) < 1e-3:
                                adj.pop(k, None)
                            else:
                                adj[k] = round(max(lo, min(hi, float(v))), 3)
                    if adj:
                        c["adjust"] = adj
                    else:
                        c.pop("adjust", None)
                    if "graded" in ed:
                        if ed["graded"]:
                            c.pop("no_grade", None)
                        else:
                            c["no_grade"] = True
            if ed.get("reset"):
                for i in targets:
                    for c in (segs[i].get("clips") or [segs[i]]):
                        c.pop("adjust", None)
                        c.pop("no_grade", None)
            done.append(("every shot's" if ed.get("segment") == "all" else f"slot {targets[0] + 1}'s") + " colour")
        elif op == "layer":   # a secondary correction on part of the frame (nodes.py)
            from .nodes import REGIONS, RANGES, clean
            region = ed.get("region")
            if region not in REGIONS:
                raise ReelError(f"region is one of {', '.join(REGIONS)}")
            targets = range(len(segs)) if ed.get("segment") == "all" else [_slot(plan, ed["segment"])]
            for i in targets:
                sg = segs[i]
                if sg.get("panel"):
                    continue
                layers = [dict(l) for l in sg.get("layers") or []]
                cur = next((l for l in layers if l["region"] == region), None)
                if ed.get("remove"):
                    layers = [l for l in layers if l["region"] != region]
                else:
                    if cur is None:
                        cur = {"region": region}
                        layers.append(cur)
                    for k in RANGES:
                        if k in ed:
                            cur[k] = ed[k]
                    if "on" in ed:
                        cur["on"] = bool(ed["on"])
                    cur["auto"] = False
                    cur.pop("why", None)
                    layers = [clean(l) if l["region"] == region else l for l in layers]
                if layers:
                    sg["layers"] = layers
                else:
                    sg.pop("layers", None)
            done.append(f"{region} layer " + ("removed" if ed.get("remove") else "set") +
                        (" on every shot" if ed.get("segment") == "all" else f" on slot {targets[0] + 1}"))
        elif op == "layers_auto":   # a shot's layers back to what the colourist decided
            from .grade import ai_notes, get_look, set_layers, shot_stats
            targets = range(len(segs)) if ed.get("segment") == "all" else [_slot(plan, ed["segment"])]
            look = get_look((plan.get("grade") or {}).get("look")) if (plan.get("grade") or {}).get("look") not in (None, "none") else None
            for i in targets:
                sg = segs[i]
                if sg.get("panel") or sg.get("shot_id") not in shots:
                    continue
                sg.pop("layers", None)
                sh = shots[sg["shot_id"]]
                note, _ = ai_notes([sh], {sh["id"]: shot_stats(sh)}, None, Path(plan.get("work") or "."), False)
                set_layers(sg, sh, note.get(sh["id"]) or {}, look)   # the colourist's remembered verdict, or the rules
            done.append("layers back to automatic")
        elif op == "stabilize":  # take the shake out of a clip (stabilize.py), or leave it as filmed
            on = bool(ed.get("on", True))
            idx = range(len(segs)) if ed.get("segment") == "all" else [_slot(plan, ed["segment"])]
            n = 0
            for i in idx:
                if segs[i].get("kind") != "video" or segs[i].get("panel"):
                    if ed.get("segment") != "all":
                        raise ReelError(f"slot {i + 1} isn't a single video clip: only clips can be stabilised")
                    continue
                if on:
                    segs[i]["stabilize"] = True
                else:
                    segs[i].pop("stabilize", None)
                n += 1
            done.append(("stabilised " if on else "as filmed: ") + (f"{n} shots" if ed.get("segment") == "all"
                                                                    else f"slot {idx[0] + 1}"))
        elif op == "backdrop":   # the person stays while the background changes on the beat (render.Backdrops)
            i = _slot(plan, ed["segment"])
            mode = str(ed.get("mode") or "places")
            if mode in ("off", "none", "null"):
                segs[i].pop("backdrop", None)
                done.append(f"slot {i + 1}: its own background")
            else:
                if mode not in ("places", "colour"):
                    raise ReelError("backdrop mode: places, colour or off")
                if segs[i].get("kind") != "video" or segs[i].get("panel"):
                    raise ReelError(f"slot {i + 1} isn't a single video clip: the swap needs a moving shot of a person")
                from .planner import backdrop_items
                bl = 60.0 / float(plan.get("tempo") or 120)
                every = bl if bl >= 0.3 else 2 * bl
                beats = max(1, int(float(segs[i]["dur"]) / every) - 1)
                items = backdrop_items(mode, segs[i], list(shots.values()), {s.get("shot_id") for s in segs}, beats)
                if not items:
                    raise ReelError("no other places with a picture to put behind the person")
                segs[i]["backdrop"] = {"mode": mode, "items": items, "every": round(every, 4)}
                done.append(f"slot {i + 1}: " + ("other places" if mode == "places" else "flat colours")
                            + " behind the person, on each beat")
        elif op == "music":
            m = plan.setdefault("music", {})
            if "start" in ed:
                m["start"] = round(max(0.0, float(ed["start"])), 3)
            if "gain_db" in ed:
                m["gain_db"] = round(max(-30.0, min(12.0, float(ed["gain_db"]))), 1)
            if "fade_out" in ed:
                m["fade_out"] = round(max(0.0, min(8.0, float(ed["fade_out"]))), 2)
            done.append("music " + ", ".join(f"{k} {m[k]}" for k in ("start", "gain_db", "fade_out") if k in ed))
        else:
            raise ReelError(f"unknown op {op}")
    if regrade and plan.get("grade"):
        _regrade(plan, shots)
    write_json(plan_path, plan)
    if undo:
        h = _history(plan_path)
        _push(h / "undo", as_was)
        import shutil
        shutil.rmtree(h / "redo", ignore_errors=True)
    from .export import export
    from .text import storyboard
    sb = storyboard(plan, shots, plan_path.with_name(plan_path.name.replace(".plan.json", ".storyboard.jpg")))
    ex = export(plan_path, edl=True, otio=False, md=True, quiet=True)
    return {"plan": str(plan_path), "changes": done, "storyboard": str(sb), **ex, **history(plan_path)}


def candidates(plan_path: Path, top: int = 30) -> list[dict]:
    plan = read_json(plan_path)
    used = {s.get("shot_id") for s in plan["segments"]} | {c.get("shot_id") for s in plan["segments"]
                                                          for c in s.get("clips") or []}
    from .insight import burned_in
    from .planner import _quality
    out = []
    shots = _shots(plan)
    lens: dict[str, float] = {}
    for s in shots.values():
        if s.get("kind") == "video":
            lens[s["src"]] = max(lens.get(s["src"], 0.0), float(s.get("t1") or 0))
    for s in sorted(shots.values(), key=lambda s: -_quality(s)):
        a = s.get("ai", {})
        out.append({"id": s["id"], "used": s["id"] in used, "kind": s["kind"], "score": round(_quality(s), 1),
                    "len_s": round(s["t1"] - s["t0"], 1) if s["kind"] == "video" else None,
                    "file_s": round(lens.get(s["src"], 0), 1) if s["kind"] == "video" else None,
                    "file": Path(s["src"]).name, "when": (s.get("created") or "")[:16], "note": a.get("note", ""),
                    "tags": a.get("tags", [])[:5], "thumb": s.get("thumb"), "caption": a.get("caption", ""),
                    "vibes": list((a.get("vibes") or {}))[:2], "size": a.get("shot_size"), "angle": a.get("angle"),
                    "words": burned_in(s) >= 0.5})
    return out[:top]


def candidates_sheet(plan_path: Path, top: int = 30) -> Path | None:
    from PIL import Image, ImageDraw
    cands = candidates(plan_path, top)
    cols, cw, ch = 6, 220, 150
    rows = (len(cands) + cols - 1) // cols
    if not rows:
        return None
    sheet = Image.new("RGB", (cols * cw, rows * (ch + 24)), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(cands):
        x, y = (i % cols) * cw, (i // cols) * (ch + 24)
        if c.get("thumb") and Path(c["thumb"]).exists():
            with Image.open(c["thumb"]) as im:
                im = im.convert("RGB")
                im.thumbnail((cw - 8, ch - 6))
                sheet.paste(im, (x + (cw - im.width) // 2, y + 3))
        d.text((x + 4, y + ch + 4), f"{c['id']} {c['score']}{' (in reel)' if c['used'] else ''}",
               fill=(255, 214, 0) if not c["used"] else (150, 150, 150))
    out = Path(plan_path).with_name(Path(plan_path).name.replace(".plan.json", ".candidates.jpg"))
    sheet.save(out, "JPEG", quality=85)
    return out
