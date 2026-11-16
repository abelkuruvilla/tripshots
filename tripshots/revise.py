"""Notes on a finished reel -> edits: `tripshots revise NAME.plan.json --note "12.3: too dark here"`.

The user watches the reel, stops where something is off and types what they see ("too dark", "swap this for the
canyon", "the text covers her face"). Each note is pinned to a time, so it is tied to the shot and the text on
screen then. The AI backend gets the notes, a still of the reel at each one (with its text), the spare shots
and planedit's safe operations, and answers with edits (and one line per note saying what it did). Without an
AI, plain rules handle the common notes (brighter / darker / warmer / cooler, replace this shot, cut it, faster /
slower, remove the text). Edits go through planedit.apply (so undo works), then the reel is rendered again.
Writes NAME.revise.json: the notes, what was done for each, and what could not be done.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .util import ReelError, log, read_json, write_json

PROMPT = """You are the editor of an Instagram Reel made from the user's travel footage. The user watched it and left
notes pinned to moments (a still of the reel at each note is attached, in order; the last image is a sheet of
the other shots available, by id). Turn every note into edits of the plan, using only these operations (slots
and texts are numbered from 1):
{ops}

The reel ({dur:.1f}s), slot by slot (start-end, role, shot id: what it shows):
{slots}
Text on screen (number: start-end "text"):
{texts}
Other shots available (id: what it shows): {cands}

The notes:
{notes}

Make the smallest change that does what each note asks; keep the cut on the beat (prefer swapping shots, colour,
text and framing edits over changing lengths). A note that is praise or needs nothing gets no edit. Every edit
names the note it is for. Reply with JSON only:
{{"edits": [{{"note": K, "op": "swap", "segment": N, "shot_id": "S…"}}, {{"note": K, "op": "adjust", "segment": N, ...}}],
 "answers": [{{"note": K, "did": "one short sentence for the user"}}]}}"""

RETRY = """

You answered with these edits; the plan refused some of them:
{refused}
Give replacement edits for those notes only (the others were made), with the same operations and the same JSON
form."""


def _at(plan: dict, t: float) -> int:
    segs = plan["segments"]
    for i, s in enumerate(segs):
        if float(s["out_start"]) <= t < float(s["out_start"]) + float(s["dur"]):
            return i
    return len(segs) - 1


def parse_note(s: str) -> dict:
    """"12.3: too dark" or "0:12.3 too dark" -> {"t": 12.3, "text": "too dark"}."""
    m = re.match(r"\s*(?:(\d+):)?(\d+(?:\.\d+)?)\s*[:\-–]?\s*(.+)$", s)
    if not m:
        raise ReelError(f"a note is a time and what to change, like \"12.3: too dark\" (got {s!r})")
    return {"t": float(m.group(1) or 0) * 60 + float(m.group(2)), "text": m.group(3).strip()}


def rules(plan: dict, notes: list[dict], spare: list[str]) -> tuple[list[dict], list[dict]]:
    """The common notes without an AI: (edits, answers)."""
    edits, answers = [], []
    spare = list(spare)
    for k, n in enumerate(notes):
        i, w = _at(plan, n["t"]) + 1, n["text"].lower()
        texts_now = [j + 1 for j, o in enumerate(plan.get("overlays") or [])
                     if float(o.get("start", 0)) <= n["t"] < float(o.get("start", 0)) + float(o.get("duration", 0))]
        did = None
        if re.search(r"\b(too )?dark|brighter|underexposed", w):
            edits.append({"op": "adjust", "segment": i, "exposure": 0.35})
            did = f"brightened shot {i}"
        elif re.search(r"\b(too )?bright|darker|overexposed|blown", w):
            edits.append({"op": "adjust", "segment": i, "exposure": -0.3, "highlights": -0.3})
            did = f"darkened shot {i}"
        elif re.search(r"warmer|too (cold|blue)", w):
            edits.append({"op": "adjust", "segment": i, "warmth": 0.3})
            did = f"warmed shot {i}"
        elif re.search(r"cooler|too (warm|orange|yellow)", w):
            edits.append({"op": "adjust", "segment": i, "warmth": -0.3})
            did = f"cooled shot {i}"
        elif re.search(r"\b(remove|delete|cut|drop)\b.*\b(text|title|words|caption)", w) and texts_now:
            edits.append({"op": "delete_text", "index": texts_now[0]})
            did = f"removed text {texts_now[0]}"
        elif re.search(r"\b(remove|delete|cut|drop)\b( this| the)? (shot|clip|bit)|\bcut it\b", w):
            edits.append({"op": "delete", "segment": i})
            did = f"cut shot {i}"
        elif re.search(r"replace|swap|change (this|the) shot|boring|weak|ugly|blurry|shaky", w) and spare:
            edits.append({"op": "swap", "segment": i, "shot_id": spare.pop(0)})
            did = f"replaced shot {i} with {edits[-1]['shot_id']}"
        elif re.search(r"slow(er)?( it)? down|slow motion|too fast", w):
            edits.append({"op": "speed", "segment": i, "speed": 0.6})
            did = f"slowed shot {i}"
        elif re.search(r"speed (it )?up|faster|too slow|drags", w):
            edits.append({"op": "speed", "segment": i, "speed": 1.6})
            did = f"sped up shot {i}"
        answers.append({"note": k + 1, "did": did or "not understood without the AI: try saying it another way"})
    return edits, answers


def _apply(plan_path: Path, edits: list[dict]) -> tuple[list[str], list[dict]]:
    """Apply edits (one undo step when they all work; else each that works, one by one). An edit may name the
    note it is for (`note`): that key isn't part of the edit."""
    from . import planedit
    edits = [{**e["op"], "note": e.get("note")} if isinstance(e.get("op"), dict) else e for e in edits]  # (nested)
    plain = [{k: v for k, v in e.items() if k != "note"} for e in edits]
    if not plain:
        return [], []
    try:
        return planedit.apply(plan_path, plain)["changes"], []
    except Exception:
        done, failed = [], []
        for e, p in zip(edits, plain):
            try:
                done += planedit.apply(plan_path, [p])["changes"]
            except Exception as ex:
                failed.append({"edit": e, "why": str(ex)[:200]})
        return done, failed


def revise(plan_path: Path, notes: list[dict], backend_name: str | None = None, render: bool = True) -> dict:
    from . import planedit
    from .framing import use_plan
    plan_path = Path(plan_path).resolve()
    plan = read_json(plan_path)
    if not plan:
        raise ReelError(f"could not read {plan_path}")
    notes = sorted([{"t": float(n["t"]), "text": str(n["text"]).strip()} for n in notes if str(n.get("text", "")).strip()],
                   key=lambda n: n["t"])
    if not notes:
        raise ReelError("no notes")
    use_plan(plan)
    segs = plan["segments"]
    shots = planedit._shots(plan)
    cands = [c for c in planedit.candidates(plan_path, 40) if not c["used"]][:24]
    edits, answers, how = [], [], "rules"
    backend = None
    try:
        from .ai import get_backend
        backend = get_backend(backend_name)
    except Exception as e:
        log(f"revise: no AI ({str(e)[:80]}): plain rules only")
    from .ai import extract_json
    if backend is not None:
        from .render import still
        work = plan_path.with_name(plan_path.name.replace(".plan.json", ".notes"))
        work.mkdir(exist_ok=True)
        imgs = []
        for k, n in enumerate(notes[:8]):
            try:
                imgs.append(still(plan, min(n["t"], float(plan["duration"]) - 0.05), work / f"note{k + 1}.jpg"))
            except Exception as e:
                log(f"revise: no still for note {k + 1} ({str(e)[:60]})")
        sheet = planedit.candidates_sheet(plan_path, 40)
        if sheet:
            imgs.append(sheet)
        slots = "\n".join(
            f"  {i + 1}: {float(s['out_start']):.1f}-{float(s['out_start']) + float(s['dur']):.1f}s "
            f"{s.get('role', '')} {s.get('shot_id') or s.get('panel', '')}: "
            f"{(shots.get(s.get('shot_id')) or {}).get('ai', {}).get('note', '')[:90]}" for i, s in enumerate(segs))
        texts = "\n".join(f"  {t['index']}: {t['start']:.1f}-{t['start'] + t['duration']:.1f}s \"{t['text']}\""
                          for t in planedit.texts(plan)) or "  (none)"
        ops = (planedit.__doc__ or "").split("ops:", 1)[-1].strip()
        noted = "\n".join(f"  {k + 1}. at {n['t']:.1f}s (slot {_at(plan, n['t']) + 1}): \"{n['text']}\""
                          for k, n in enumerate(notes))
        prompt = PROMPT.format(ops=ops, dur=float(plan["duration"]), slots=slots, texts=texts, notes=noted,
                               cands="; ".join(f"{c['id']}: {c['note'][:70]}" for c in cands))
        try:
            data = extract_json(backend.ask(prompt, imgs, max_tokens=1500))
            if isinstance(data, dict):
                edits = [e for e in data.get("edits") or [] if isinstance(e, dict) and e.get("op")]
                answers = [a for a in data.get("answers") or [] if isinstance(a, dict)]
                how = "ai"
        except Exception as e:
            log(f"revise: the AI could not answer ({str(e)[:100]}): plain rules instead")
    if how == "rules":
        edits, answers = rules(plan, notes, [c["id"] for c in cands])
    done, failed = _apply(plan_path, edits)
    if failed and how == "ai":
        # what the plan refused goes back once, with the reason and everything it saw, for another way to do it
        try:
            more = extract_json(backend.ask(prompt + "\n\nYour reply: " + json.dumps({"edits": edits, "answers": answers})
                                            + RETRY.format(refused="\n".join(f"  {json.dumps(f['edit'])}: {f['why']}"
                                                                              for f in failed)), imgs, max_tokens=1000))
            if isinstance(more, dict) and more.get("edits"):
                again = [e for e in more["edits"] if isinstance(e, dict) and e.get("op")]
                d2, failed = _apply(plan_path, again)
                done += d2
                edits = edits + again
                fixed = {a.get("note"): a for a in more.get("answers") or [] if isinstance(a, dict)}
                answers = [fixed.get(a.get("note"), a) for a in answers]
        except Exception as e:
            log(f"revise: no second try ({str(e)[:80]})")
    for f in failed:  # never tell the user something was done when the plan refused it
        k = f["edit"].get("note")
        for a in answers:
            if k is not None and a.get("note") == k:
                a["did"] = f"Not done: {f['why']}"
    for a in answers:
        log(f"note {a.get('note')}: {a.get('did')}")
    report = {"plan": str(plan_path), "notes": notes, "how": how, "edits": edits, "changes": done,
              "answers": answers, **({"failed": failed} if failed else {})}
    if render and done:
        from .pipeline import render_plan
        report["video"] = str(render_plan(plan_path, None))
    write_json(plan_path.with_name(plan_path.name.replace(".plan.json", ".revise.json")), report)
    return report
