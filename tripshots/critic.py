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
  flow           the camera's movement carries across the cuts (matchcut.carry: no left-then-right, no
                 push-in into a pull-back that it couldn't fix)
Fixes: turn on the hook punch, move the hook line to the third frame, swap a shot with a person into the first
3 s, swap repeated moments apart, turn on the loop. With an AI backend it also looks at the storyboard, in
rounds: each round a fresh reviewer (nothing to defend) lists what is wrong as "blocker" (worth a change) or
"polish" (noted, never holds the reel up) with the change that fixes it (applied through planedit's safe
operations). The next round's reviewer first sees the changes with before/after proof (the old and the new shot
side by side) and says whether each one helped; one that made it worse is undone. It stops when no blocker is
left, when the list stops shrinking (it must halve, or be down to a few), or after `story.critic_rounds` rounds
(default 3: review and fix, check and fix, check; the last round never changes anything it can't check).
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
    rec = plan.get("recipe") or {}
    if rec.get("text") in ("none", "lyrics", "subtitles", "labels"):
        pass  # its reference opens without a hook line: judged below on doing what the reference does
    else:
        add("hook_text", hk and hk["start"] <= 0.2 and len(hk["text"].split()) <= 7, 15,
            "a short hook line on screen by 0.2 s", "hook_start" if hk and hk["start"] > 0.2 else None)
    ds = [s["dur"] for s in segs]
    ratio = max(ds) / max(0.01, min(ds)) if ds else 1
    flat = max((sum(1 for _ in g) for _, g in __import__("itertools").groupby(round(d, 1) for d in ds)), default=0)
    att = plan.get("attention") or {}
    if rec.get("lens") and ds:
        # one reference's own cut: the same number of shots, give or take what the footage and the song allow
        n, want = len(ds), len(rec["lens"])
        add("rhythm", 0.6 * want <= n <= 1.5 * want, 15,
            f"cut like its reference ({n} shots, theirs {want})")
    elif att.get("shot_sec") and ds:
        # a learned style is judged against its own references, not a general rule: a calm reel may hold its
        # shots, a fast montage may not drag
        avg, ref = sum(ds) / len(ds), float(att.get("shot_mean") or att["shot_sec"])
        add("rhythm", 0.6 * ref <= avg <= 1.7 * ref, 15,
            f"paced like the style's references (a cut every {avg:.1f}s, theirs every {ref:.1f}s)")
    else:
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
    if hk and segs:  # the opening line must be about what is on screen while it shows
        first_ai = (by_id.get(segs[0].get("shot_id")) or {}).get("ai") or {}
        named = first_ai.get("landmark")
        others = {(by_id.get(s.get("shot_id")) or {}).get("ai", {}).get("landmark") for s in segs[1:]} - {None, named}
        wrong = next((o for o in others if o and o.lower() in hk["text"].lower()), None)
        add("hook_matches", not wrong, 10, "the hook names what the opening shot shows"
            + (f" (it names {wrong}, shown later)" if wrong else ""), "hook_shot" if wrong else None)
    loop = plan.get("loop") or any(o["type"] == "cta" for o in plan.get("overlays") or [])
    if rec.get("structure") in ("hold_burst", "flash_intro"):
        # a reel that changes gear half way ends on its last beat; looping it into a slow opening would jar
        end = segs[-1]["out_start"] + segs[-1]["dur"] if segs else 0
        add("ending", abs(end - plan["duration"]) < 0.05, 15, "ends on the last beat of the montage")
    else:
        add("ending", loop, 15, "the ending loops back or closes with a line", None if loop else "loop")
    cont = plan.get("continuity")
    if cont and cont.get("cuts"):
        left = cont.get("left") or []
        add("flow", len(left) <= 1, 5, "the camera's movement carries across the cuts"
            + (f" ({'; '.join(left[:2])})" if left else ""))
    if rec:
        from . import recipes
        for key, ok, weight, why, fx in recipes.checks(plan, by_id):
            add(key, ok, weight, why, fx)
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
        _unmatch(segs, k)


def _unmatch(segs: list[dict], k: int) -> None:
    """A slot's shot changed: the cuts into and out of it are no longer the ones the camera's motion carried."""
    segs[k].pop("match", None)
    if k:
        segs[k - 1].pop("match", None)


def long_slots(plan: dict, by_id: dict, places: dict | None = None) -> list[str]:
    """After shots changed hands: a view worth a second isn't left in a flash while a lesser one lingers
    (story._long_slots_first, for a plan). Only slots that play the same part trade, never the hook, the turn,
    the ending, a hold, a split screen or a cut the camera's own motion carries."""
    from .formats import short_place
    from .story import _q
    segs = plan["segments"]
    tied = ("panel", "hold", "incam_out", "incam_in", "match", "clone_of")
    free = [i for i, s in enumerate(segs) if s.get("shot_id") in by_id and not any(s.get(k) for k in tied)
            and s.get("role") not in ("hook", "peak", "ending")
            and not (i and (segs[i - 1].get("incam_out") or segs[i - 1].get("match")))]

    def q(i: int) -> float:
        return _q(by_id[segs[i]["shot_id"]])

    def chapter(i: int) -> str:
        return short_place(places.get(segs[i]["shot_id"])) or "?" if places else ""

    def lasts(j: int, i: int) -> bool:  # a clip has the footage for the longer slot
        sh = by_id[segs[j]["shot_id"]]
        return sh.get("kind") != "video" or float(sh["t1"]) - float(sh["t0"]) >= 0.8 * float(segs[i]["dur"])
    done = []
    for i in sorted(free, key=lambda i: -float(segs[i]["dur"])):
        short = [j for j in free if segs[j].get("role") == segs[i].get("role") and chapter(i) == chapter(j)
                 and float(segs[i]["dur"]) >= 1.8 * float(segs[j]["dur"]) and q(j) >= q(i) + 0.6 and lasts(j, i)]
        if short:
            j = max(short, key=lambda j: (q(j), -float(segs[j]["dur"])))
            _swap(segs, i, j, by_id)
            done.append(f"slots {min(i, j) + 1} and {max(i, j) + 1} exchanged (the better shot stays longer)")
    return done


def fix(plan: dict, by_id: dict, shots: list[dict], cs: list[dict], places: dict | None = None) -> list[str]:
    """`places`: {shot id: place} of a reel told place by place: two slots only trade shots inside one chapter."""
    from .formats import short_place
    done = []
    segs = plan["segments"]

    def chapter(i: int, j: int) -> bool:
        return not places or (short_place(places.get(segs[i].get("shot_id")))
                              == short_place(places.get(segs[j].get("shot_id"))))
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
            pair = next(((i, j) for i in reversed(early) for j in later if chapter(i, j)), None)
            if pair:
                _swap(segs, pair[0], pair[1], by_id)
                done.append(f"shot with a person moved into the first 3 s (slot {pair[0] + 1})")
        elif f == "repeats":
            for i in range(1, len(segs) - 1):
                if segs[i].get("src") and segs[i].get("src") == segs[i - 1].get("src"):
                    for j in range(i + 2, len(segs)):
                        if segs[j].get("src") not in (segs[i - 1].get("src"), segs[i].get("src")) and \
                                segs[j].get("role") not in ("peak", "ending", "hook") and not segs[j].get("panel") \
                                and chapter(i, j):
                            _swap(segs, i, j, by_id)
                            done.append(f"slots {i + 1} and {j + 1} swapped (same clip back to back)")
                            break
        elif f == "hook_shot":  # the hook names a landmark shown later: open on that shot
            hk = next((o for o in plan["overlays"] if o["type"] == "hook"), None)
            j = next((i for i, s in enumerate(segs) if i and not s.get("panel") and hk and
                      ((by_id.get(s.get("shot_id")) or {}).get("ai", {}).get("landmark") or "\0").lower()
                      in hk["text"].lower()), None)
            if j is not None and not segs[0].get("panel") and not segs[0].get("hold") and chapter(0, j):
                _swap(segs, 0, j, by_id)
                done.append(f"opening shot is now the one the hook names (was slot {j + 1})")
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
{earlier}Judge the hook (does slot 1 stop the scroll?), the story (is there a build and a payoff?), variety, and whether
the best shots are used. List what is wrong, each with a severity:
  "blocker": a viewer would scroll away or the reel is visibly worse for it (a weak opening, a flat payoff, the
             same view twice, a dull or broken shot where it matters). Give the change that fixes it.
  "polish":  it could be nicer, but the reel works. A polish item never needs a change.
Changes are operations:
  {{"op": "swap", "segment": N, "shot_id": "S…"}}  put another available shot in slot N
  {{"op": "exchange", "a": N, "b": M}}            swap two slots' shots
  {{"op": "text", "type": "hook", "text": "…"}}    a better hook line (max 7 words)
Reply with JSON only: {{"score": 0-100, "verdict": "one sentence",{verify_key} "issues": [{{"slot": N or null,
"issue": "…", "severity": "blocker"|"polish", "op": {{…}} or null}}]}} (issues may be empty)."""

VERIFY = """
Earlier round: another editor changed these (the second image shows each slot before | after):
{changes}
First check each change on the storyboard: did it help? Then judge the reel as it is now.
"""


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


def spares(plan: dict, by_id: dict, style: dict | None = None, n: int = 20) -> list[dict]:
    """The shots the AI critic may put in: the best of those not in the reel, marked down like the planner
    does for having been shown in an earlier reel, for being grey in footage full of colour and for being
    upright in a wide picture (the critic reads a shot's note, not how the frame will cut it). A landmark the
    reel already shows isn't offered again (a second Half Dome from another angle reads as a repeat)."""
    from .history import mark_down
    from .planner import colourless, misfit
    used = {s.get("shot_id") for s in plan["segments"]}
    grey = colourless(list(by_id.values()))

    def mark(s):
        return str((s.get("ai") or {}).get("landmark") or "").split(",")[0].strip().lower()
    shown = {mark(by_id[i]) for i in used if i in by_id} - {""}
    return sorted((s for s in by_id.values() if s["id"] not in used and mark(s) not in shown),
                  key=lambda s: -float(s.get("ai", {}).get("score", 5)) + 2.4 * mark_down(style or {}, s)
                  + 1.5 * grey.get(s["id"], 0.0) + misfit(s))[:n]


def proof_sheet(changes: list[dict], by_id: dict, out: Path) -> Path | None:
    """Before | after for each change of the last round: the old shot and the new one in that slot."""
    from PIL import Image, ImageDraw
    from .text import load_font
    rows = [c for c in changes if c.get("slot") and (c.get("before") or c.get("after"))][:6]
    if not rows:
        return None
    tw, th = 160, 284
    sheet = Image.new("RGB", (2 * tw + 3 * 8 + 120, len(rows) * (th + 8) + 8), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    font = load_font(20)
    for k, c in enumerate(rows):
        y = 8 + k * (th + 8)
        d.text((8, y + th // 2 - 12), f"slot {c['slot']}", fill=(235, 235, 235), font=font)
        for j, sid in enumerate((c.get("before"), c.get("after"))):
            th_p = (by_id.get(sid) or {}).get("thumb")
            x = 120 + j * (tw + 8)
            try:
                im = Image.open(th_p).convert("RGB")
                sc = max(tw / im.width, th / im.height)
                im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1))
                l, t = (im.width - tw) // 2, (im.height - th) // 2
                sheet.paste(im.crop((l, t, l + tw, t + th)), (x, y))
            except Exception:
                d.rectangle((x, y, x + tw, y + th), outline=(90, 90, 90))
            d.text((x + 6, y + 6), ("before " if j == 0 else "after ") + str(sid or ""), fill=(255, 220, 120), font=font)
    sheet.save(out, quality=88)
    return out


def ai_review(plan_path: Path, plan: dict, by_id: dict, backend, style: dict | None = None,
              changes: list[dict] | None = None) -> dict | None:
    from .ai import extract_json
    from .history import mark_down
    from .text import storyboard
    sb = storyboard(plan, by_id, plan_path.with_suffix(".critic.jpg"))
    before = {s["id"]: mark_down(style or {}, s) for s in by_id.values()}  # shown in an earlier reel
    cands = spares(plan, by_id, style)
    summary = "; ".join(f"slot {i + 1} {s.get('role', '')} {s['dur']:.1f}s {s.get('shot_id')}: "
                        f"{by_id.get(s.get('shot_id'), {}).get('ai', {}).get('note', '')}"
                        for i, s in enumerate(plan["segments"]))
    hooks = [o["text"] for o in plan.get("overlays") or [] if o["type"] == "hook"]
    if hooks:
        summary += f"; hook text \"{hooks[0]}\""
    rec = plan.get("recipe") or {}
    if rec:
        summary += (f". This reel follows one reference reel's recipe on purpose ({rec.get('why') or rec.get('structure')})"
                    + ("; slot 1 is its long opening hold and stays" if rec.get("structure") == "hold_burst" else "")
                    + ("; the text on screen is the song's words, as in the reference: suggest no hook line"
                       if rec.get("text") in ("lyrics", "subtitles", "none") else ""))
    led = [s["shot_id"] for s in plan["segments"][1:-1] if before.get(s.get("shot_id"), 0) >= 1.0]
    if led:
        summary += (f". {', '.join(dict.fromkeys(led))} opened or ended an earlier reel of this series: "
                    "leave them in the middle, never in slot 1 or the last slot")
    imgs = [sb]
    earlier, verify_key = "", ""
    if changes:
        proof = proof_sheet(changes, by_id, plan_path.with_suffix(".proof.jpg"))
        if proof:
            imgs.append(proof)
        earlier = VERIFY.format(changes="\n".join(f"  {k + 1}. {c['what']} (for: {c.get('why') or 'a better reel'})"
                                                   for k, c in enumerate(changes)))
        verify_key = ' "verified": [{"change": K, "helped": true|false}],'
    try:
        data = extract_json(backend.ask(AI_PROMPT.format(
            summary=summary, cands="; ".join(f"{s['id']}: {s.get('ai', {}).get('note', '')}" for s in cands),
            direction=direction(plan.get("direction")), earlier=earlier, verify_key=verify_key),
            imgs, max_tokens=900))
        if not isinstance(data, dict):
            return None
        if "issues" not in data and data.get("ops"):  # an older-style reply: every change counts as a blocker
            data["issues"] = [{"slot": o.get("segment"), "issue": "", "severity": "blocker", "op": o}
                              for o in data["ops"] if isinstance(o, dict)]
        data["issues"] = [i for i in data.get("issues") or [] if isinstance(i, dict)]
        return data
    except Exception as e:
        log(f"critic: AI review skipped ({str(e)[:100]})")
        return None


def review(plan: dict, by_id: dict, shots: list[dict], style: dict, backend=None, work: Path | None = None) -> dict:
    cs = checks(plan, by_id, shots)
    before = score(cs)
    done = fix(plan, by_id, shots, cs, style.get("_places") if (plan.get("story") or {}).get("format") == "list"
               else None)
    ai, rounds = None, []
    if backend is not None and work is not None:
        tmp = Path(work) / "critic.plan.json"
        limit = max(1, min(4, int((style.get("story") or {}).get("critic_rounds", 3) or 3)))
        changes, last_n = None, None
        for r in range(limit):
            ai = ai_review(tmp, plan, by_id, backend, style, changes)  # a fresh reviewer every round
            if not ai:
                break
            # the last round's changes, judged with proof: one that made the reel worse is undone
            undone = []
            for v in ai.get("verified") or []:
                try:
                    c = changes[int(v.get("change")) - 1]
                except (TypeError, ValueError, IndexError):
                    continue
                if v.get("helped") is False and c.get("undo"):
                    c["undo"]()
                    undone.append(c["what"])
            blockers = [i for i in ai["issues"] if str(i.get("severity", "")).lower() == "blocker"]
            polish = [i for i in ai["issues"] if i not in blockers]
            rounds.append({"round": r + 1, "score": ai.get("score"), "verdict": ai.get("verdict"),
                           "blockers": [i.get("issue") for i in blockers], "polish": [i.get("issue") for i in polish],
                           **({"undone": undone} if undone else {})})
            log(f"critic round {r + 1}: {len(blockers)} blocker(s), {len(polish)} polish"
                + (f"; undone: {'; '.join(undone)}" if undone else ""))
            if not blockers or (r == limit - 1 and limit > 1):
                break  # (the last round only checks: a change nobody checks isn't made)
            if last_n is not None and len(blockers) > 3 and len(blockers) > last_n / 2:
                log("critic: the list isn't shrinking: stopping here")
                break
            last_n = len(blockers)
            changes = _apply_issues(plan, by_id, style, blockers[:3])
            done += [c["what"] for c in changes]
            if any(c["what"].startswith("AI: slot") for c in changes):  # a shot put in by eye may land in a flash
                done += long_slots(plan, by_id, style.get("_places")
                                   if (plan.get("story") or {}).get("format") == "list" else None)
            if not changes:
                break
    cs2 = checks(plan, by_id, shots)
    after = score(cs2)
    log(f"critic: {before}/100 -> {after}/100" + (f"; fixed: {'; '.join(done)}" if done else "")
        + (f"; AI: {ai.get('verdict')}" if ai and ai.get("verdict") else ""))
    for c in cs2:
        if not c["ok"]:
            log(f"  still weak: {c['why']}")
    return {"score": after, "score_before": before, "checks": cs2, "fixed": done,
            "ai": {k: ai.get(k) for k in ("score", "verdict", "issues")} if ai else None,
            **({"rounds": rounds} if rounds else {})}


def _apply_issues(plan: dict, by_id: dict, style: dict, issues: list[dict]) -> list[dict]:
    """Apply each blocker's change; return what changed, with its before/after shots and a way to undo it."""
    import copy
    segs = plan["segments"]
    out = []
    for it in issues:
        op = it.get("op")
        if not isinstance(op, dict) or op.get("op") not in ("swap", "exchange", "text"):
            continue
        snap_s, snap_o = copy.deepcopy(segs), copy.deepcopy(plan.get("overlays") or [])
        did = apply_ops(plan, by_id, style, [op])
        if not did:
            continue
        slot = op.get("segment") or op.get("a")
        try:
            k = int(slot) - 1
            before, after = snap_s[k].get("shot_id"), segs[k].get("shot_id")
        except (TypeError, ValueError, IndexError):
            before = after = None

        idx = [int(op[k]) - 1 for k in ("segment", "a", "b") if str(op.get(k, "")).lstrip("-").isdigit()]

        def undo(s0=snap_s, o0=snap_o, idx=idx, text=op["op"] == "text"):
            # only what this change touched: later changes to other slots stay
            for k in idx:
                if 0 <= k < len(segs):
                    segs[k].clear()
                    segs[k].update(s0[k])
            if text:
                for ov, was in zip(plan.get("overlays") or [], o0):
                    if ov.get("type") == "hook" and was.get("type") == "hook":
                        ov["text"] = was["text"]
        out.append({"what": did[0], "why": it.get("issue"), "slot": slot, "before": before, "after": after,
                    "undo": undo})
    return out


def apply_ops(plan: dict, by_id: dict, style: dict, ops: list[dict]) -> list[str]:
    """The AI's suggestions, applied with the same safety rules as planedit (slot timing never moves)."""
    from .planner import _shot_fields
    segs = plan["segments"]
    done = []
    # a reel told place by place keeps its chapters: a shot only gives way to one from the same place
    from .formats import short_place
    places = style.get("_places") if (plan.get("story") or {}).get("format") == "list" else None

    def at(sid):
        return short_place((places or {}).get(sid)) or "?"
    for o in ops:
        try:
            if o["op"] == "swap":
                i = int(o["segment"]) - 1
                sh = by_id.get(str(o.get("shot_id", "")).upper())
                if not (0 <= i < len(segs)) or not sh or segs[i].get("panel") or segs[i].get("hold"):
                    continue  # (a long hold is cast from clips that last: not swapped by eye)
                if places and at(sh["id"]) != at(segs[i].get("shot_id")):
                    continue
                from .matchcut import SLOT
                e, _ = _shot_fields(sh, segs[i]["dur"], segs[i].get("level", "medium"), style, i)
                slot = {k: segs[i][k] for k in SLOT if k in segs[i]}
                segs[i].clear()
                segs[i].update({**e, **slot})
                _unmatch(segs, i)
                done.append(f"AI: slot {i + 1} -> {sh['id']}")
            elif o["op"] == "exchange":
                a, b = int(o["a"]) - 1, int(o["b"]) - 1
                if 0 <= a < len(segs) and 0 <= b < len(segs) and a != b and not segs[a].get("panel") \
                        and not segs[b].get("panel") and not segs[a].get("hold") and not segs[b].get("hold") \
                        and not (places and at(segs[a].get("shot_id")) != at(segs[b].get("shot_id"))):
                    _swap(segs, a, b, by_id)
                    done.append(f"AI: slots {a + 1} and {b + 1} exchanged")
            elif o["op"] == "text" and o.get("type") == "hook" and o.get("text"):
                from .ai import clean_line
                t = clean_line(o["text"])
                if 0 < len(t.split()) <= 7:
                    for ov in plan["overlays"]:
                        if ov["type"] == "hook" and ov.get("recipe"):
                            break  # a line built like its reference's (a title, a tease with its answer) stays
                        if ov["type"] == "hook":
                            ov["text"] = t
                            done.append(f"AI: hook -> \"{t}\"")
                            break
        except (KeyError, TypeError, ValueError):
            continue
    return done
