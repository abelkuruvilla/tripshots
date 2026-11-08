"""The story engine: a reel planned as a little story with a hook and a payoff, not a slideshow.

Research on short video (see docs/storytelling.md) says viewers decide in about a second and a half, stay for
a question they want answered, and share moments, not catalogues. So every reel gets an arc:

  hook     the most striking moment first (a flash-forward of the payoff, or a tease), moving within 0.5 s,
           with big text on screen from the third frame
  setup    where we are: an establishing shot, a person arriving
  build    shots that get shorter and shorter into the drop
  peak     the payoff on the drop: the best shot, held long (slow motion when the clip allows)
  release  the energy after the drop, in a varied rhythm
  ending   a held closing shot that looks like the opening, so the reel loops

and a rhythm engine that varies shot lengths on purpose (½ to 8 beats) instead of cutting every 4 beats.
When the audio has words (a song's lines, a film dialogue), cuts land where the lines end and the payoff lands
on the punchline (lyrics.py). Formats (formats.py) change the arc and the text: POV, a numbered list of places,
a "Day N" series, a slow reveal.
"""
from __future__ import annotations

import hashlib

from .config import OUT_FPS

ROLES = ("hook", "setup", "build", "peak", "release", "ending")


def _rand(*parts) -> float:
    h = hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


# ------------------------------------------------------------------ rhythm
PATTERNS = {  # shot lengths in beats, cycled; varied on purpose (fast runs into a held shot)
    "calm": [4, 2, 4, 6, 2, 4],
    "medium": [2, 1, 1, 2, 4, 2, 1, 1, 3],
    "intense": [1, 1, 2, 1, 1, 4, 1, 1, 2],
}
BUILD = [2, 2, 1, 1, 1, 0.5, 0.5]  # accelerating into the drop


class _BeatClock:
    """Times at fractional beat indices (half beats sit halfway between two beats)."""

    def __init__(self, beats: list[float], beat_len: float):
        self.b = list(beats)
        self.bl = beat_len

    def t(self, x: float) -> float:
        i = int(x)
        f = x - i
        if i + 1 < len(self.b):
            return self.b[i] + f * (self.b[i + 1] - self.b[i])
        if not self.b:
            return x * self.bl
        return self.b[-1] + (x - (len(self.b) - 1)) * self.bl

    def index_at(self, t: float) -> float:
        """The beat index (whole) nearest time t."""
        if not self.b:
            return round(t / self.bl)
        return float(min(range(len(self.b)), key=lambda i: abs(self.b[i] - t)))


def _level(e: float, th: tuple) -> str:
    return "calm" if e < th[0] else ("intense" if e >= th[1] else "medium")


def _drops(beats: list[float], energy: list[float], total: float) -> list[float]:
    import numpy as np
    out = []
    for j in range(4, len(beats) - 3):
        prev = float(np.mean(energy[max(0, j - 4):j]))
        nxt = float(np.mean(energy[j:j + 4]))
        if nxt - prev > 0.22 and 0.3 < beats[j] < total - 0.5:
            if not out or beats[j] - out[-1] > 2.0:
                out.append(round(beats[j], 4))
    return out


def rhythm(grid: dict, style: dict, target: float, words: dict | None = None, variant: int = 0) -> dict:
    """Shot slots for the whole reel, each with a role and a length chosen for its place in the story.

    Returns {"segments": [{out_start, dur, level, role}], "duration", "drops", "peak"}."""
    beats = grid.get("beats_all") or grid["beats"]
    energy = grid.get("energy_all") or grid.get("energy") or [0.5] * len(beats)
    th = grid.get("thresholds") or (0.35, 0.7)
    bl = float(grid["beat_len"])
    cuts = style["cuts"]
    min_s, max_s = float(cuts["min_shot_sec"]), float(cuts["max_shot_sec"])
    clock = _BeatClock(beats, bl)
    dmin, dmax = float(style["duration"]["min"]), float(style["duration"]["max"])

    if words and words.get("kind") == "dialogue" and words.get("lines"):
        return _dialogue_rhythm(words, beats, energy, th, bl, style, target)

    end_i = clock.index_at(min(target, (beats[-1] if beats else target)))
    while clock.t(end_i) < dmin and end_i < len(beats) + 64:
        end_i += 1
    while clock.t(end_i) > dmax and end_i > 4:
        end_i -= 1
    total = clock.t(end_i)
    drops = _drops(beats, energy, total)
    # the payoff: the biggest drop in the middle of the reel, else 55 % of the way, on a bar line
    mid = [d for d in drops if 0.3 * total <= d <= 0.75 * total]
    if words and words.get("punch_t") is not None and 0.25 * total <= words["punch_t"] <= 0.85 * total:
        peak_i = clock.index_at(words["punch_t"])
    elif mid:
        peak_i = clock.index_at(mid[0])
    else:
        peak_i = float(round(clock.index_at(0.55 * total) / 4) * 4) or clock.index_at(0.55 * total)

    def fit(n: float, lo: float = min_s, hi: float = max_s) -> float:
        """Nearest length (in beats, halves allowed) whose duration sits within [lo, hi]."""
        n = max(0.5, n)
        while n * bl < lo * 0.95 and n < 16:
            n = n * 2 if n >= 1 else n + 0.5
        while n * bl > hi * 1.05 and n > 0.5:
            n = n / 2 if n >= 2 else n - 0.5
        if n < 1 and n * bl < max(0.32, lo * 0.7):
            n = 1.0
        return n

    lengths: list[tuple[float, str]] = []   # (beats, role)
    # hook: one shot, about 1-2 s, then the setup
    # pace: a style learned from slow, cinematic references holds every shot longer (its beats per cut)
    pace = max(1.0, min(4.0, float((cuts.get("beats_per_cut") or {}).get("medium", 2) or 2) / 2))
    hook_n = fit(max(1.0, round(1.4 * min(pace, 1.8) / bl)), 0.9, 2.4 * min(pace, 1.8))
    lengths.append((hook_n, "hook"))
    pos = hook_n
    # setup until the build: a medium pace
    build_beats = min(8.0, max(0.0, round((peak_i - pos) * 0.45)))
    setup_end = peak_i - build_beats
    k = int(_rand("setup", variant) * 6)
    while pos < setup_end - 0.01:
        lvl = _level(energy[min(int(pos), len(energy) - 1)] if energy else 0.5, th)
        pat = PATTERNS["calm" if lvl == "calm" else "medium"]
        n = fit(pat[k % len(pat)] * pace)
        k += 1
        if pos + n > setup_end:
            n = setup_end - pos
            if n * bl < min_s * 0.8:
                if lengths and lengths[-1][1] == "setup":
                    lengths[-1] = (lengths[-1][0] + n, "setup")
                    pos += n
                    break
                build_beats += n
                break
        lengths.append((n, "setup"))
        pos += n
    # build: accelerating cuts into the peak
    rem = peak_i - pos
    bi = 0
    while rem > 0.01:
        n = fit(BUILD[min(bi, len(BUILD) - 1)] * pace, min_s * 0.8, max_s)
        n = min(n, rem)
        if n * bl < max(0.3, min_s * 0.7):
            if lengths:
                lengths[-1] = (lengths[-1][0] + n, lengths[-1][1])
            break
        lengths.append((n, "build"))
        pos += n
        rem -= n
        bi += 1
    # peak: the payoff, held (4-8 beats, at least 2 s)
    peak_n = fit((8 if bl < 0.45 else 4) * min(pace, 2.0), 2.0, max(2.0, max_s * 2.2))
    lengths.append((peak_n, "peak"))
    pos += peak_n
    # ending: a held closer (at least ~2 s); the release fills what is between
    end_n = fit((4 if bl >= 0.4 else 6) * min(pace, 2.0), 1.8, max(2.0, max_s * 1.8))
    rel_end = end_i - end_n
    k = int(_rand("release", variant) * 9)
    while pos < rel_end - 0.01:
        lvl = _level(energy[min(int(pos), len(energy) - 1)] if energy else 0.5, th)
        pat = PATTERNS[lvl]
        n = fit(pat[k % len(pat)] * pace)
        k += 1
        if pos + n > rel_end:
            n = rel_end - pos
            if n * bl < min_s * 0.8:
                end_n += n
                break
        lengths.append((n, "release"))
        pos += n
    if pos > rel_end + 0.01:  # the peak ran past: shorten the ending, keep the total
        end_n = max(end_n - (pos - rel_end), fit(2, 1.0, 3.0))
    lengths.append((end_n, "ending"))
    return _to_segments(lengths, clock, energy, th, drops, peak_i)


def _to_segments(lengths, clock: _BeatClock, energy, th, drops, peak_i) -> dict:
    segs = []
    x = 0.0
    fprev = 0
    for n, role in lengths:
        x2 = x + n
        f2 = int(round(clock.t(x2) * OUT_FPS))
        if f2 - fprev >= 6:
            e = energy[min(int(x), len(energy) - 1)] if energy else 0.5
            segs.append({"out_start": round(fprev / OUT_FPS, 4), "dur": round((f2 - fprev) / OUT_FPS, 4),
                         "level": _level(e, th), "role": role, "beats": n})
            fprev = f2
        elif segs:  # too short to stand: belongs to the shot before
            segs[-1]["dur"] = round((f2 - round(segs[-1]["out_start"] * OUT_FPS)) / OUT_FPS, 4)
            fprev = f2
        x = x2
    for s in segs:
        if s["role"] == "peak":
            s["level"] = "intense" if s["level"] != "calm" else "medium"
    total = round(fprev / OUT_FPS, 4)
    peak_t = next((s["out_start"] for s in segs if s["role"] == "peak"), None)
    return {"segments": segs, "duration": total, "drops": [d for d in drops if d < total - 0.5],
            "peak": peak_t}


def _dialogue_rhythm(words: dict, beats, energy, th, bl, style, target) -> dict:
    """Film dialogue (or a voice-over) as the sound: one shot per line, cut in the pause after it, the
    payoff on the punchline. Long lines get a second shot at their middle pause."""
    lines = [ln for ln in words["lines"] if ln["start"] < target + 6]
    min_s, max_s = float(style["cuts"]["min_shot_sec"]), float(style["cuts"]["max_shot_sec"]) * 1.6
    cuts = [0.0]
    for a, b in zip(lines, lines[1:]):
        t = (a["end"] + b["start"]) / 2 if b["start"] > a["end"] else b["start"]
        near = [x for x in beats if abs(x - t) < 0.12]  # a beat right in the pause: use it
        t = near[0] if near else t
        if t - cuts[-1] >= min_s * 0.9:
            cuts.append(t)
    end = lines[-1]["end"] + 0.5 if lines else target
    end = min(max(end, float(style["duration"]["min"])), float(style["duration"]["max"]))
    # hold no shot for too long: split long stretches
    import math
    out = [cuts[0]]
    for t in [c for c in cuts[1:] if c < end - min_s * 0.9] + [end]:
        a = out[-1]
        k = max(1, math.ceil((t - a) / max_s))
        out += [a + (t - a) * j / k for j in range(1, k + 1)]
    out = sorted(set(round(x, 3) for x in out if x <= end + 1e-6))
    if out[-1] < end - 0.3:
        out.append(end)
    punch = words.get("punch_t")
    peak_k = None
    if punch is not None:
        peak_k = min(range(len(out) - 1), key=lambda k: abs(out[k] - punch))
    elif len(out) > 3:
        peak_k = int((len(out) - 1) * 0.6)
    segs = []
    for k, (a, b) in enumerate(zip(out, out[1:])):
        fa, fb = int(round(a * OUT_FPS)), int(round(b * OUT_FPS))
        if fb - fa < 6:
            continue
        role = ("hook" if k == 0 else "ending" if k == len(out) - 2 else "peak" if k == peak_k
                else "build" if peak_k is not None and k == peak_k - 1 else "setup" if peak_k is None or k < peak_k
                else "release")
        segs.append({"out_start": round(fa / OUT_FPS, 4), "dur": round((fb - fa) / OUT_FPS, 4),
                     "level": "medium", "role": role, "line": k})
    # contiguous frames
    for s, n in zip(segs, segs[1:]):
        s["dur"] = round(n["out_start"] - s["out_start"], 4)
    total = round(segs[-1]["out_start"] + segs[-1]["dur"], 4) if segs else end
    return {"segments": segs, "duration": total, "drops": [], "peak": next(
        (s["out_start"] for s in segs if s["role"] == "peak"), None)}


# ------------------------------------------------------------------ casting
def _ai(s):
    return s.get("ai") or {}


def has_people(s: dict) -> bool:
    a = _ai(s)
    p = a.get("people")
    n = int(p.get("count") or 0) if isinstance(p, dict) else 0
    if n > 0:
        return True
    from .framing import person_box
    if person_box(s):
        return True
    text = " ".join(a.get("tags", [])[:12]) + " " + str(a.get("note", ""))
    return any(w in text.lower() for w in ("person", "silhouette", "hiker", " man ", "woman", "people", "selfie"))


def moving(s: dict) -> bool:
    m = s.get("metrics") or {}
    return s.get("kind") == "video" and (m.get("pan", 0) > 0.004 or m.get("activity", 0) > 0.012)


def _q(s):
    return float(_ai(s).get("score", 5.0))


def role_score(s: dict, role: str, ctx: dict) -> float:
    a = _ai(s)
    q = _q(s)
    people = has_people(s)
    pw = float(ctx.get("people_weight", 1.0))
    dyn = 1.0 if a.get("mood") == "dynamic" else 0.0
    v = q
    if role == "hook":
        v += 1.5 * (a.get("role") == "hook") + 0.6 * dyn + (1.0 if moving(s) else 0.0) + 0.6 * pw * people
        v += 0.3 * float(a.get("aesthetic", q) or q) / 10
        if ctx.get("tease"):  # reveal format: open on something intriguing, keep the best for the payoff
            v = 5 + 1.0 * moving(s) + 0.5 * people - 0.3 * q
    elif role == "peak":
        v += 0.8 * dyn + 0.8 * moving(s) + 0.8 * pw * people
        v += 0.6 if s.get("kind") == "video" and float(s.get("fps") or 0) >= 48 else 0.0
    elif role == "ending":
        v = 0.6 * q + 2.0 * (a.get("role") == "closer") + 0.8 * (a.get("mood") == "calm") + 0.8 * pw * people
        if ctx.get("loop_ref") is not None and ctx.get("looks", {}).get(s["id"]) is not None:
            from .diversity import look_similarity
            v += 3.0 * look_similarity(ctx["loop_ref"], ctx["looks"][s["id"]])
    elif role == "setup":
        v += 0.6 * (a.get("role") in ("establish", "hook")) + 0.4 * (a.get("mood") == "calm") + 0.5 * pw * people
    elif role == "build":
        v += 1.0 * dyn + 1.0 * moving(s)
    else:  # release
        v += 0.6 * dyn + 0.5 * moving(s) + 0.3 * pw * people
    return v


def cast(chosen: list[dict], segs: list[dict], style: dict, variant: int = 0, groups: dict | None = None,
         tease: bool = False, places: dict | None = None, fmt: str = "montage") -> list[dict]:
    """Put each chosen shot where it serves the story: the hook, the payoff, the ending first, then the rest."""
    from .diversity import thumb_look
    pool = list(chosen)
    order: list[dict | None] = [None] * len(segs)
    st = style.get("story") or {}
    ctx = {"people_weight": 1.6 if st.get("people_first", True) else 0.5, "tease": tease, "looks": {}}
    from .planner import taste_scores
    taste = taste_scores(chosen, style)  # a learned style's light, colour and people

    def used_pen(s):  # thin footage repeats shots in the pool: never the same one twice while others remain
        return -50.0 if any(o is not None and o["id"] == s["id"] for o in order) else 0.0

    def take(idx: int, role: str, extra=None):
        if not pool:
            return
        ranked = sorted(pool, key=lambda s: role_score(s, role, ctx) + taste.get(s["id"], 0.0) + used_pen(s)
                        + (extra(s) if extra else 0), reverse=True)
        pick = ranked[min(variant, len(ranked) - 1)] if role == "hook" and variant else ranked[0]
        order[idx] = pick
        pool.remove(pick)
    roles = [s.get("role", "release") for s in segs]
    if "hook" in roles:
        take(roles.index("hook"), "hook")
    if "peak" in roles:
        take(roles.index("peak"), "peak")
    if "ending" in roles and len(segs) > 2:
        hook = order[roles.index("hook")] if "hook" in roles else None
        if hook is not None and style.get("loop", True):
            ctx["loop_ref"] = thumb_look(hook.get("thumb"))
            ctx["looks"] = {s["id"]: thumb_look(s.get("thumb")) for s in pool}
        take(len(roles) - 1 - roles[::-1].index("ending"), "ending")
    # people in the first seconds when we have someone and the hook isn't them
    hook_i = roles.index("hook") if "hook" in roles else 0
    if st.get("people_first", True) and order[hook_i] is not None and not has_people(order[hook_i]):
        early = [i for i, s in enumerate(segs) if order[i] is None and s["out_start"] < 3.0]
        ppl = [s for s in pool if has_people(s) and _q(s) >= _q(order[hook_i]) - 2.0]
        if early and ppl:
            best = max(ppl, key=lambda s: role_score(s, roles[early[0]], ctx) + used_pen(s))
            order[early[0]] = best
            pool.remove(best)
    # the rest by role, in story order; chronology inside the middle when the style asks for it
    rest = [i for i in range(len(segs)) if order[i] is None]
    if fmt == "list" and places:  # chapters: one place after another, the best place last
        from .formats import list_order
        for i, sh in zip(rest, list_order(pool, places)):
            order[i] = sh
        pool = []
    elif style["shots"].get("ordering") == "chronological":
        pool.sort(key=lambda s: (s.get("created") or "", s["src"], s.get("t0", 0)))
        for i, s in zip(rest, pool):
            order[i] = s
        pool = []
    else:
        for i in rest:
            if not pool:
                break
            role = roles[i]
            prev = order[i - 1] if i > 0 else None

            def adj(s, prev=prev):
                pen = 0.0
                if prev is not None and s.get("src") == prev.get("src"):
                    pen -= 2.0
                if prev is not None and groups and groups.get(s["id"], s["id"]) == groups.get(prev["id"], prev["id"]):
                    pen -= 3.0
                return pen + (_rand("mix", variant, s["id"], i) - 0.5) * (1.2 if variant else 0.3)
            ranked = sorted(pool, key=lambda s: role_score(s, role, ctx) + 0.5 * taste.get(s["id"], 0.0) + adj(s)
                            + used_pen(s), reverse=True)
            order[i] = ranked[0]
            pool.remove(ranked[0])
    # footage thinner than the slots: repeat the best (planner merged most of these away)
    best = sorted(chosen, key=_q, reverse=True)
    for i in range(len(order)):
        if order[i] is None:
            order[i] = best[i % len(best)]
    return order


def restrain_transitions(segs: list[dict]) -> int:
    """Most cuts in a good edit are plain cuts on the beat; effects mark moments. Keep the transition into the
    payoff, then at most one in every four other cuts, and only gentle ones outside intense sections."""
    removed = 0
    peak = next((i for i, s in enumerate(segs) if s.get("role") == "peak"), None)
    since = 99
    for i, s in enumerate(segs[:-1]):
        tr = s.get("trans_out")
        if not tr or s.get("incam_out"):
            since += 1
            continue
        into_peak = peak is not None and i == peak - 1
        level = s.get("level", "medium")
        wild = tr in ("glitch", "spin", "flash") and level != "intense"
        if into_peak and not wild:
            since = 0
            continue
        if wild or since < 3 or s.get("role") in ("hook",):
            s.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
            removed += 1
            since += 1
        else:
            since = 0
    return removed


def describe(segs: list[dict]) -> str:
    """'hook 1.4s · setup 2×2.1s · build 4 (0.4-0.8s) · peak 2.8s · release 3 · ending 2.5s'"""
    parts = []
    for role in ROLES:
        ds = [s["dur"] for s in segs if s.get("role") == role]
        if not ds:
            continue
        parts.append(f"{role} {ds[0]:.1f}s" if len(ds) == 1 else f"{role} {len(ds)} ({min(ds):.1f}-{max(ds):.1f}s)")
    return " · ".join(parts)
