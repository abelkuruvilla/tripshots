"""The retention critic: checks a planned reel the way an editor would, before it is rendered, and fixes what
it can.

Rules (each with a weight; the score is out of 100):
  first second   something moves in the first 0.5 s (a moving clip, or the hook punch)
  hook text      a hook line on screen by 0.2 s, at most 7 words
  rhythm         shot lengths vary (the longest at least 2.5x the shortest), no long run of equal lengths
  people         a person within the first 3 s when the footage has one; people somewhere in the reel
  payoff         a held payoff shot (at least 1.5 s) after the middle
  no repeats     no moment twice, no source twice in a row
  movement       not more than half the shots static
  ending         the ending loops back (or a closing line)
Fixes: turn on the hook punch, move the hook line to the third frame, swap a shot with a person into the first
3 s, swap repeated moments apart, turn on the loop. With an AI backend it also looks at the storyboard and may
suggest up to three swaps or text changes (applied through planedit's safe operations).
"""
from __future__ import annotations

from pathlib import Path

from .util import log


def _people(sh: dict | None) -> bool:
    if not sh:
        return False
    from .story import has_people
    return has_people(sh)


def _moving(seg: dict, sh: dict | None) -> bool:
    if seg.get("kind") == "video":
        m = (sh or {}).get("metrics") or {}
        return (m.get("pan", 0) > 0.003 or m.get("activity", 0) > 0.01 or bool(seg.get("ramp"))
                or float(seg.get("speed", 1) or 1) > 1.2)
    return seg.get("layout") in ("kenburns", "popout", "parallax") or seg.get("parallax", False)


def checks(plan: dict, by_id: dict, shots: list[dict]) -> list[dict]:
    segs = plan["segments"]
    out = []

    def add(key, ok, weight, why, fix=None):
        out.append({"check": key, "ok": bool(ok), "weight": weight, "why": why, **({"fix": fix} if fix else {})})
    first = segs[0] if segs else {}
    mv = _moving(first, by_id.get(first.get("shot_id"))) and first.get("kind") == "video"
    add("first_second", mv or (plan.get("motion") or {}).get("hook_punch"), 15,
        "something moves in the first 0.5 s", None if mv else "hook_punch")
    hooks = [o for o in plan.get("overlays") or [] if o["type"] == "hook"]
    hk = hooks[0] if hooks else None
    add("hook_text", hk and hk["start"] <= 0.2 and len(hk["text"].split()) <= 7, 15,
        "a short hook line on screen by 0.2 s", "hook_start" if hk and hk["start"] > 0.2 else None)
    ds = [s["dur"] for s in segs]
    ratio = max(ds) / max(0.01, min(ds)) if ds else 1
    flat = max((sum(1 for _ in g) for _, g in __import__("itertools").groupby(round(d, 1) for d in ds)), default=0)
    add("rhythm", ratio >= 2.5 and flat <= 4, 15, f"shot lengths vary ({min(ds or [0]):.1f}-{max(ds or [0]):.1f}s)")
    have_people = any(_people(s) for s in shots)
    early = [s for s in segs if s["out_start"] < 3.0]
    early_ok = any(_people(by_id.get(s.get("shot_id"))) for s in early)
    add("people_early", early_ok or not have_people, 10, "a person in the first 3 s",
        None if early_ok or not have_people else "people_early")
    payoff = [s for s in segs if s.get("role") == "peak" or (s["dur"] >= 1.5 and s["out_start"] > 0.35 * plan["duration"])]
    add("payoff", bool(payoff), 10, "a held payoff shot after the middle")
    from .diversity import scene_groups
    used = [by_id[s["shot_id"]] for s in segs if s.get("shot_id") in by_id and not s.get("panel")]
    g = scene_groups(used) if used else {}
    keys = [g.get(s["id"], s["id"]) for s in used]
    rep = len(keys) - len(set(keys))
    adj = sum(1 for a, b in zip(segs, segs[1:]) if a.get("src") and a.get("src") == b.get("src"))
    add("no_repeats", rep == 0 and adj == 0, 10, "no moment twice, no source twice in a row",
        "repeats" if rep or adj else None)
    static = sum(1 for s in segs if not _moving(s, by_id.get(s.get("shot_id"))))
    add("movement", static <= len(segs) / 2, 10, f"{static} of {len(segs)} shots static")
    loop = plan.get("loop") or any(o["type"] == "cta" for o in plan.get("overlays") or [])
    add("ending", loop, 15, "the ending loops back or closes with a line", None if loop else "loop")
    return out


def score(cs: list[dict]) -> int:
    tot = sum(c["weight"] for c in cs)
    return int(round(100 * sum(c["weight"] for c in cs if c["ok"]) / max(1, tot)))


def _swap(segs: list[dict], i: int, j: int, by_id: dict) -> None:
    from .matchcut import SLOT, _refit
    a = {k: v for k, v in segs[i].items() if k not in SLOT}
    b = {k: v for k, v in segs[j].items() if k not in SLOT}
    for k, c in ((i, b), (j, a)):
        slot = {kk: segs[k][kk] for kk in SLOT if kk in segs[k]}
        segs[k].clear()
        segs[k].update({**c, **slot})
        _refit(segs[k], by_id)


def fix(plan: dict, by_id: dict, shots: list[dict], cs: list[dict]) -> list[str]:
    done = []
    segs = plan["segments"]
    for c in cs:
        f = c.get("fix")
        if c["ok"] or not f:
            continue
        if f == "hook_punch":
            plan.setdefault("motion", {})["hook_punch"] = True
            if segs:
                segs[0]["role"] = segs[0].get("role") or "hook"
            done.append("opening shot now settles from a push-in (movement in the first 0.5 s)")
        elif f == "hook_start":
            for o in plan["overlays"]:
                if o["type"] == "hook":
                    end = o["start"] + o["duration"]
                    o["start"], o["duration"] = 0.1, round(end - 0.1, 3)
            done.append("hook line moved to the third frame")
        elif f == "people_early":
            early = [i for i, s in enumerate(segs) if 0 < i and s["out_start"] < 3.0 and not s.get("panel")]
            later = [i for i, s in enumerate(segs) if s["out_start"] >= 3.0 and not s.get("panel")
                     and s.get("role") not in ("peak", "ending") and _people(by_id.get(s.get("shot_id")))]
            if early and later:
                _swap(segs, early[-1], later[0], by_id)
                done.append(f"shot with a person moved into the first 3 s (slot {early[-1] + 1})")
        elif f == "repeats":
            for i in range(1, len(segs) - 1):
                if segs[i].get("src") and segs[i].get("src") == segs[i - 1].get("src"):
                    for j in range(i + 2, len(segs)):
                        if segs[j].get("src") not in (segs[i - 1].get("src"), segs[i].get("src")) and \
                                segs[j].get("role") not in ("peak", "ending", "hook") and not segs[j].get("panel"):
                            _swap(segs, i, j, by_id)
                            done.append(f"slots {i + 1} and {j + 1} swapped (same clip back to back)")
                            break
        elif f == "loop":
            plan["loop"] = True
            done.append("ending now loops into the opening")
    return done


AI_PROMPT = """You are a senior short-form video editor reviewing a planned Instagram Reel (storyboard attached:
slots in order, with their length). The viewer decides in about 1.5 seconds whether to stay.
Plan: {summary}
Other shots available (id: note): {cands}
Direction for this reel (the house notes, then this style's own):
{direction}
Judge the hook (does slot 1 stop the scroll?), the story (is there a build and a payoff?), variety, and whether
the best shots are used. Suggest at most 3 changes that would most improve retention, as operations:
  {{"op": "swap", "segment": N, "shot_id": "S…"}}  put another available shot in slot N
  {{"op": "exchange", "a": N, "b": M}}            swap two slots' shots
  {{"op": "text", "type": "hook", "text": "…"}}    a better hook line (max 7 words)
Reply with JSON only: {{"score": 0-100, "verdict": "one sentence", "ops": [...]}} (ops may be empty)."""


def direction(style_note: str | None = None) -> str:
    """The director's notes (DIRECTOR.md, condensed to its rules) plus the style's own direction."""
    try:
        text = (Path(__file__).parent / "DIRECTOR.md").read_text()
    except OSError:
        text = ""
    rules = [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]
    out = "\n".join(f"- {r}" for r in rules[:24])
    if style_note:
        out += f"\nStyle: {str(style_note).strip()}"
    return out


def ai_review(plan_path: Path, plan: dict, by_id: dict, backend) -> dict | None:
    from .ai import extract_json
    from .text import storyboard
    sb = storyboard(plan, by_id, plan_path.with_suffix(".critic.jpg"))
    used = {s.get("shot_id") for s in plan["segments"]}
    cands = sorted((s for s in by_id.values() if s["id"] not in used),
                   key=lambda s: -float(s.get("ai", {}).get("score", 5)))[:20]
    summary = "; ".join(f"slot {i + 1} {s.get('role', '')} {s['dur']:.1f}s {s.get('shot_id')}: "
                        f"{by_id.get(s.get('shot_id'), {}).get('ai', {}).get('note', '')}"
                        for i, s in enumerate(plan["segments"]))
    hooks = [o["text"] for o in plan.get("overlays") or [] if o["type"] == "hook"]
    if hooks:
        summary += f"; hook text \"{hooks[0]}\""
    try:
        data = extract_json(backend.ask(AI_PROMPT.format(
            summary=summary, cands="; ".join(f"{s['id']}: {s.get('ai', {}).get('note', '')}" for s in cands),
            direction=direction(plan.get("direction"))),
            [sb], max_tokens=700))
        return data if isinstance(data, dict) else None
    except Exception as e:
        log(f"critic: AI review skipped ({str(e)[:100]})")
        return None


def review(plan: dict, by_id: dict, shots: list[dict], style: dict, backend=None, work: Path | None = None) -> dict:
    cs = checks(plan, by_id, shots)
    before = score(cs)
    done = fix(plan, by_id, shots, cs)
    ai = None
    if backend is not None and work is not None:
        tmp = Path(work) / "critic.plan.json"
        ai = ai_review(tmp, plan, by_id, backend)
        ops = [o for o in (ai or {}).get("ops") or [] if isinstance(o, dict)
               and o.get("op") in ("swap", "exchange", "text")][:3]
        if ops:
            done += apply_ops(plan, by_id, style, ops)
    cs2 = checks(plan, by_id, shots)
    after = score(cs2)
    log(f"critic: {before}/100 -> {after}/100" + (f"; fixed: {'; '.join(done)}" if done else "")
        + (f"; AI: {ai.get('verdict')}" if ai and ai.get("verdict") else ""))
    for c in cs2:
        if not c["ok"]:
            log(f"  still weak: {c['why']}")
    return {"score": after, "score_before": before, "checks": cs2, "fixed": done,
            "ai": {k: ai.get(k) for k in ("score", "verdict", "ops")} if ai else None}


def apply_ops(plan: dict, by_id: dict, style: dict, ops: list[dict]) -> list[str]:
    """The AI's suggestions, applied with the same safety rules as planedit (slot timing never moves)."""
    from .planner import _shot_fields
    segs = plan["segments"]
    done = []
    for o in ops:
        try:
            if o["op"] == "swap":
                i = int(o["segment"]) - 1
                sh = by_id.get(str(o.get("shot_id", "")).upper())
                if not (0 <= i < len(segs)) or not sh or segs[i].get("panel"):
                    continue
                from .matchcut import SLOT
                e, _ = _shot_fields(sh, segs[i]["dur"], segs[i].get("level", "medium"), style, i)
                slot = {k: segs[i][k] for k in SLOT if k in segs[i]}
                segs[i].clear()
                segs[i].update({**e, **slot})
                done.append(f"AI: slot {i + 1} -> {sh['id']}")
            elif o["op"] == "exchange":
                a, b = int(o["a"]) - 1, int(o["b"]) - 1
                if 0 <= a < len(segs) and 0 <= b < len(segs) and a != b and not segs[a].get("panel") \
                        and not segs[b].get("panel"):
                    _swap(segs, a, b, by_id)
                    done.append(f"AI: slots {a + 1} and {b + 1} exchanged")
            elif o["op"] == "text" and o.get("type") == "hook" and o.get("text"):
                from .ai import clean_line
                t = clean_line(o["text"])
                if 0 < len(t.split()) <= 7:
                    for ov in plan["overlays"]:
                        if ov["type"] == "hook":
                            ov["text"] = t
                            done.append(f"AI: hook -> \"{t}\"")
                            break
        except (KeyError, TypeError, ValueError):
            continue
    return done
