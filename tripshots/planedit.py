"""Small, safe edits to a plan.json for agents (and `tripshots edit`), without breaking the beat grid.

Segments are numbered from 1, as on the storyboard. Shot content moves between beat slots; slot
timing (dur, out_start, level, the transition into the next slot) stays where it is.

ops:
  {"op": "swap", "segment": 3, "shot_id": "S012"}        put another shot in slot 3
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
  {"op": "set", "path": "motion.beat_punch", "value": 0.04}          anything else, by dotted path
"""
from __future__ import annotations

from pathlib import Path

from .config import load_style
from .util import ReelError, read_json, write_json

SLOT_KEYS = {"dur", "out_start", "idx", "level", "drop", "trans_out", "trans_dur", "trans_params", "incam_out",
             "incam_in", "hero"}
TRANSITIONS = {None, "whip", "zoom_in", "zoom_out", "spin", "flash", "glitch", "blur", "dissolve", "dip", "leak"}


def _content(seg: dict) -> dict:
    return {k: v for k, v in seg.items() if k not in SLOT_KEYS}


def _put(seg: dict, content: dict) -> None:
    for k in [k for k in seg if k not in SLOT_KEYS]:
        del seg[k]
    seg.update(content)


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
    if sh and seg.get("kind") == "video" and not seg.get("panel"):
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


def apply(plan_path: Path, edits: list[dict]) -> dict:
    plan_path = Path(plan_path)
    plan = read_json(plan_path)
    if not plan:
        raise ReelError(f"could not read {plan_path}")
    style = load_style(plan.get("style"))
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
            regrade = True
            done.append(f"slot {i + 1} -> {sh['id']}")
        elif op in ("move", "exchange"):
            a, b = (_slot(plan, ed["from"]), _slot(plan, ed["to"])) if op == "move" else \
                (_slot(plan, ed["a"]), _slot(plan, ed["b"]))
            contents = [_content(s) for s in segs]
            if op == "move":
                c = contents.pop(a)
                contents.insert(b, c)
            else:
                contents[a], contents[b] = contents[b], contents[a]
            for s, c in zip(segs, contents):
                _put(s, c)
            for k in range(min(a, b), max(a, b) + 1):
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
            for k in ("subject_x", "layout", "pan_from", "pan_to"):
                if k in ed:
                    segs[i][k] = ed[k]
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
        else:
            raise ReelError(f"unknown op {op}")
    if regrade and plan.get("grade"):
        from . import grade
        grade.grade_plan(plan, shots, {"look": plan["grade"].get("look"), "strength": plan["grade"].get("strength"),
                                       "ai": False}, None, Path(plan.get("work") or "."))
    write_json(plan_path, plan)
    from .export import export
    from .text import storyboard
    sb = storyboard(plan, shots, plan_path.with_name(plan_path.name.replace(".plan.json", ".storyboard.jpg")))
    ex = export(plan_path, edl=True, otio=False, md=True, quiet=True)
    return {"plan": str(plan_path), "changes": done, "storyboard": str(sb), **ex}


def candidates(plan_path: Path, top: int = 30) -> list[dict]:
    plan = read_json(plan_path)
    used = {s.get("shot_id") for s in plan["segments"]} | {c.get("shot_id") for s in plan["segments"]
                                                          for c in s.get("clips") or []}
    from .planner import _quality
    out = []
    for s in sorted(_shots(plan).values(), key=lambda s: -_quality(s)):
        a = s.get("ai", {})
        out.append({"id": s["id"], "used": s["id"] in used, "kind": s["kind"], "score": round(_quality(s), 1),
                    "len_s": round(s["t1"] - s["t0"], 1) if s["kind"] == "video" else None,
                    "file": Path(s["src"]).name, "when": (s.get("created") or "")[:16], "note": a.get("note", ""),
                    "tags": a.get("tags", [])[:5], "thumb": s.get("thumb")})
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
