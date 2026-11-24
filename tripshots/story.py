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
from collections import Counter

from .config import OUT_FPS

ROLES = ("hook", "setup", "build", "peak", "release", "ending")
# how far below the best a fresher shot may be and still take a slot that carries the reel (an opening seen
# before is the easiest repeat to notice, so there the newer shot gets more room)
LEAD_SLACK = {"hook": 2.5, "ending": 1.5}
PEAK_Q = 0.8  # the turn of a reel goes to one of its best-looking shots: this close to the best (a reveal: half)


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

    def x_at(self, t: float) -> float:
        """The fractional beat index at time t (the inverse of `t`)."""
        b = self.b
        if not b:
            return t / self.bl
        if t >= b[-1]:
            return len(b) - 1 + (t - b[-1]) / self.bl
        if t <= b[0]:
            return max(0.0, (t - b[0]) / self.bl)
        import bisect
        i = bisect.bisect_right(b, t) - 1
        return i + (t - b[i]) / max(b[i + 1] - b[i], 1e-6)


def _level(e: float, th: tuple) -> str:
    return "calm" if e < th[0] else ("intense" if e >= th[1] else "medium")


def _drops(beats: list[float], energy: list[float], total: float) -> list[float]:
    import numpy as np

    def rise(j: int) -> float:
        return float(np.mean(energy[j:j + 4])) - float(np.mean(energy[max(0, j - 4):j]))

    out, n, j = [], len(beats) - 3, 4
    while j < n:
        if rise(j) > 0.22 and 0.3 < beats[j] < total - 0.5:
            # the four-beat averages start to part a beat or two before the hit: the drop is where they part most
            k = max(range(j, min(j + 4, n)), key=lambda i: (round(rise(i), 4), -i))
            if beats[k] >= total - 0.5:
                k = j
            if not out or beats[k] - out[-1] > 2.0:
                out.append(round(beats[k], 4))
            j = k + 1
        else:
            j += 1
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

    recipe = style.get("_recipe")
    if words and words.get("kind") == "dialogue" and words.get("lines") and not recipe:
        return _dialogue_rhythm(words, beats, energy, th, bl, style, target)

    end_i = clock.index_at(min(target, (beats[-1] if beats else target)))
    while clock.t(end_i) < dmin and end_i < len(beats) + 64:
        end_i += 1
    while clock.t(end_i) > dmax and end_i > 4:
        end_i -= 1
    total = clock.t(end_i)
    drops = _drops(beats, energy, total)
    flow = grid.get("flow_all") or []
    peaks = [p for p in grid.get("peaks") or [] if p["t"] < total - 0.5]
    for p in peaks:  # the song's climaxes (music.peaks) are drops too
        if not any(abs(p["t"] - d) < 1.0 for d in drops):
            drops = sorted(drops + [p["t"]])
    # the payoff: the song's biggest climax in the middle of the reel, else its biggest energy drop there, else
    # 55 % of the way, on a bar line
    mid = [p["t"] for p in sorted(peaks, key=lambda p: (p["kind"] != "drop", -p["rise"]))
           if 0.3 * total <= p["t"] <= 0.75 * total]
    mid += [d for d in drops if 0.3 * total <= d <= 0.75 * total and d not in mid]

    def flowing(pos: float) -> bool:
        """No drum pulse here (music.sections): hold shots longer and let them flow, don't cut to a metronome."""
        return bool(flow) and flow[min(int(pos), len(flow) - 1)]
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

    if recipe:  # one reference's own shot lengths, laid on this song (recipes.py)
        from . import recipes
        avail = grid.get("avail")
        limit = clock.x_at(avail) if avail and target >= avail - 0.3 else float(clock.index_at(target))
        lengths = recipes.slots(recipe, {**grid, "drops": _drops(beats, energy, clock.t(limit))}, clock, limit)
        if lengths:  # (a reference's own cut stays as it was: no flowing sections, no breath)
            total = clock.t(sum(n for n, _ in lengths))
            return _to_segments(lengths, clock, energy, th, _drops(beats, energy, total), 0.0)
    att = style.get("attention") or {}
    if att.get("curve") and att.get("shot_sec"):
        return _curve_rhythm(att, clock, bl, end_i, energy, th, drops, mid, words, variant, flow, peaks,
                             cut_shift(style))

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
        pat = PATTERNS["calm" if lvl == "calm" or flowing(pos) else "medium"]
        n = fit(pat[k % len(pat)] * pace * (1.4 if flowing(pos) else 1.0), hi=max_s * (1.5 if flowing(pos) else 1.0))
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
        n = fit(BUILD[min(bi, len(BUILD) - 1)] * pace, min_s * 0.8, max_s) if not flowing(pos) else \
            fit(2 * pace * 1.4, hi=max_s * 1.5)  # no beat to accelerate on: the run-in flows too
        while n * bl > 1.5 and n > 1 and not flowing(pos):  # into a climax: something new every 1-1.5 s
            n = n / 2 if n >= 2 else n - 0.5
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
        pat = PATTERNS["calm" if flowing(pos) else lvl]
        n = fit(pat[k % len(pat)] * pace * (1.4 if flowing(pos) else 1.0), hi=max_s * (1.5 if flowing(pos) else 1.0))
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
    return _to_segments(lengths, clock, energy, th, drops, peak_i, flow, peaks, cut_shift(style))


def _snap(sec: float, bl: float) -> float:
    """A length in seconds as beats: whole beats, or half beats for short shots; never under about 0.3 s."""
    n = sec / bl
    n = round(n * 2) / 2 if n < 1.25 else float(round(n))  # half beats only for the shortest shots
    n = max(0.5, n)
    while n * bl < 0.3:
        n += 0.5
    return n


def _curve_rhythm(att: dict, clock: _BeatClock, bl: float, end_i: float, energy, th, drops, mid, words,
                  variant: int = 0, flow=None, peaks=None, shift=None) -> dict:
    """Shot slots that follow a learned style's own rhythm (style `attention`, measured by `learn`): the
    reference's shot length at each point of its length, its opening hold and where it holds its payoff, on
    this song's beats. A fast montage stays fast where the reference was fast; a slow reel keeps its holds."""
    curve = [float(x) for x in att["curve"]]
    med = float(att["shot_sec"])
    total_b = float(end_i)

    def want(pos_b: float) -> float:
        u = min(0.999, max(0.0, pos_b / total_b))
        x = u * len(curve) - 0.5  # bin centres, linear in between
        i = int(max(0, min(len(curve) - 2, x // 1)))
        f = min(1.0, max(0.0, x - i))
        held = 1.4 if flow and flow[min(int(pos_b), len(flow) - 1)] else 1.0  # no beat to cut on: hold longer
        return held * med * (curve[i] * (1 - f) + curve[i + 1] * f)

    # where the payoff is held: the reference's place, moved to a drop of this song when one is near
    peak_u = att.get("peak_at")
    peak_i = None
    if words and words.get("punch_t") is not None and 0.2 * clock.t(end_i) <= words["punch_t"] <= 0.9 * clock.t(end_i):
        peak_i = clock.index_at(words["punch_t"])
    elif peak_u is not None and 0.15 <= float(peak_u) <= 0.82:
        peak_i = float(round(peak_u * total_b))
        near = [clock.index_at(d) for d in drops if abs(clock.index_at(d) - peak_i) <= 0.15 * total_b]
        if near:
            peak_i = float(min(near, key=lambda x: abs(x - peak_i)))
    elif mid:
        peak_i = clock.index_at(mid[0])
    open_n = _snap(float((att.get("open") or {}).get("hold") or want(0.0)), bl)
    lengths: list[list] = [[open_n, "hook"]]
    pos = open_n
    while pos < total_b - 0.01:
        n = _snap(want(pos) * (1.0 + 0.12 * (_rand("curve", variant, len(lengths)) - 0.5) * (1 if variant else 0)), bl)
        if n >= 1 and abs((pos + n) - round(pos + n)) > 0.01:  # after a half-beat shot: back onto the beat
            n = n + 0.5 if want(pos) >= n * bl else max(0.5, n - 0.5)
        if peak_i is not None and pos < peak_i < pos + n and (peak_i - pos) * bl >= 0.35:
            n = peak_i - pos  # a cut lands on the payoff's beat
        if total_b - (pos + n) < 0.5 * n:  # no stub at the end: the last shot takes what is left
            n = total_b - pos
        lengths.append([n, "release"])
        pos += n
    if len(lengths) > 1 and lengths[-1][0] * bl < 0.6 and len(lengths) > 2:
        lengths[-2][0] += lengths[-1][0]
        lengths.pop()
    # roles, for casting: hook, the payoff, the run into it, the ending
    starts, x = [], 0.0
    for n, _ in lengths:
        starts.append(x)
        x += n
    k_peak = None
    if peak_i is not None and len(lengths) > 3:
        near = [k for k in range(1, len(lengths) - 1) if peak_i - 1.01 <= starts[k] <= peak_i + 0.15 * total_b]
        k_peak = (max(near, key=lambda k: (lengths[k][0], -abs(starts[k] - peak_i))) if near else
                  min(range(1, len(lengths) - 1), key=lambda k: abs(starts[k] - peak_i)))
    elif len(lengths) > 3:  # no marked payoff: the longest shot of the second half
        cand = [k for k in range(1, len(lengths) - 1) if starts[k] >= 0.4 * total_b] or list(range(1, len(lengths) - 1))
        k_peak = max(cand, key=lambda k: lengths[k][0])
    # the payoff is a held shot: at least a typical shot of this style and 0.8 s (it takes the next slot if not)
    while k_peak is not None and k_peak < len(lengths) - 2 and lengths[k_peak][0] * bl < max(0.8, med):
        lengths[k_peak][0] += lengths[k_peak + 1][0]
        del lengths[k_peak + 1]
        del starts[k_peak + 1]
    for k in range(1, len(lengths)):
        if k == len(lengths) - 1:
            lengths[k][1] = "ending"
        elif k_peak is None:
            lengths[k][1] = "setup" if starts[k] < 0.5 * total_b else "release"
        elif k == k_peak:
            lengths[k][1] = "peak"
        elif k < k_peak:
            lengths[k][1] = "build" if k >= k_peak - 3 and k > 1 else "setup"
    return _to_segments([(n, r) for n, r in lengths], clock, energy, th, drops,
                        peak_i if peak_i is not None else starts[k_peak] if k_peak else 0.0, flow, peaks, shift)


def cut_shift(style: dict) -> dict:
    """The learned editor's habit of where a cut sits against the beat (learn: attention `cut_phase`):
    {"frames": cut this many frames early (-) or late (+), "beats": 0.5 = on the off-beat}. Only a habit the
    references show clearly (consistent and common) is copied."""
    cp = (style.get("attention") or {}).get("cut_phase") or {}
    if cp.get("n", 0) < 8 or cp.get("R", 0) < 0.45:
        return {}
    if abs(float(cp.get("phase", 0)) - 0.5) < 0.15 and cp.get("on_beat", 1) < 0.35 and cp["R"] >= 0.55:
        return {"beats": 0.5}
    f = max(-3, min(3, int(cp.get("offset_f") or 0)))
    return {"frames": f} if f and cp.get("on_beat", 0) >= 0.25 else {}


def _to_segments(lengths, clock: _BeatClock, energy, th, drops, peak_i, flow=None, peaks=None, shift=None) -> dict:
    segs = []
    x = 0.0
    fprev = 0
    shift = shift or {}
    for k_l, (n, role) in enumerate(lengths):
        x2 = x + n
        f2 = int(round(clock.t(x2) * OUT_FPS))
        if shift and k_l < len(lengths) - 1:
            # the editor's habit: a frame or two before the beat, or on the off-beat (never the cut into the
            # payoff or onto a drop: those land on the hit)
            nxt_role = lengths[k_l + 1][1]
            on_hit = nxt_role == "peak" or any(abs(clock.t(x2) - d) < 0.12 for d in drops)
            if shift.get("beats") and not on_hit:
                f2 = int(round(clock.t(x2 + shift["beats"]) * OUT_FPS))
            f2 += int(shift.get("frames", 0))
        if f2 - fprev >= 6:
            e = energy[min(int(x), len(energy) - 1)] if energy else 0.5
            fl = flow[int(x):max(int(x) + 1, int(x2))] if flow else []
            calm = bool(fl) and sum(fl) * 2 > len(fl)  # mostly without a beat to cut on (music.sections)
            segs.append({"out_start": round(fprev / OUT_FPS, 4), "dur": round((f2 - fprev) / OUT_FPS, 4),
                         "level": "calm" if calm else _level(e, th), "role": role, "beats": n,
                         **({"beatless": True} if calm else {})})
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
    # the breath: when the song goes quiet just before its climax, so does the picture (planner holds the shot
    # before the payoff still: no transition out of it but a clean cut on the hit, no beat punches)
    k = next((i for i, s in enumerate(segs) if s["role"] == "peak"), None)
    hit = next((p for p in peaks or [] if peak_t is not None and abs(p["t"] - peak_t) < 0.2), None)
    if k and hit and hit.get("breath", 0) >= 0.25 and segs[k - 1]["role"] != "hook":
        segs[k - 1]["breath"] = round(min(0.75, float(hit["breath"])), 2)
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


def _words(s: dict) -> set:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w
            for t in (_ai(s).get("tags") or [])[:7] for w in str(t).lower().split()}


def alike(a: dict, b: dict) -> bool:
    """The same kind of view (the rig from the drone again, another lake with someone at the shore): what the AI
    called the scene and three words of what it saw first. Shots with no place on record repeat this way."""
    scene = _ai(a).get("scene")
    return bool(scene) and scene == _ai(b).get("scene") and len(_words(a) & _words(b)) >= 3


def landmark(s: dict) -> str:
    """The landmark the AI named, without its park ("Half Dome, Yosemite" and "Half Dome" are one)."""
    return str(_ai(s).get("landmark") or "").split(",")[0].strip().lower()


def same_view(a: dict, b: dict) -> bool:
    """The same kind of view from the same half day (the forest road again, two hours on): after a shot that
    stays on screen for seconds it reads as a repeat, however far apart the two were filmed."""
    from .diversity import _when
    ta, tb = _when(a), _when(b)
    return ta is not None and tb is not None and abs(ta - tb) <= 12 * 3600 and alike(a, b)


def moving(s: dict) -> bool:
    m = s.get("metrics") or {}
    return s.get("kind") == "video" and (m.get("pan", 0) > 0.004 or m.get("activity", 0) > 0.012)


def _q(s):
    from .planner import _quality
    return _quality(s)


ANIMAL_WORDS = {"wildlife", "animal", "moose", "elk", "bison", "bear", "deer", "bird", "eagle", "whale", "seal", "fox",
                "wolf", "horse", "goat", "sheep", "cow", "dog", "cat", "pronghorn", "otter", "puffin"}


def first_frame_pull(s: dict) -> float:
    """What stops a thumb on the opening shot, beyond its quality: a clip over a still (a photo's slow zoom reads
    as a still frame), an animal, and enough light (a dark first frame is swiped past)."""
    a = _ai(s)
    v = 0.0 if s.get("kind") == "video" else -0.8
    words = {str(t).lower() for t in a.get("tags") or []} | {str(a.get("scene") or "").lower()}
    if words & ANIMAL_WORDS:
        v += 0.6
    bright = (s.get("metrics") or {}).get("bright")
    if bright is not None and float(bright) < 0.22:
        v -= 0.6
    om = (s.get("insight") or {}).get("open_motion")
    if s.get("kind") == "video" and om is not None and float(om) < 0.05:
        v -= 0.6   # a clip that hardly moves at first (a tripod on a far view) opens like a photo
    return v


OPEN_MEASURE = 8   # the clips most likely to open the reel get their first-second movement measured


def measure_openers(pool: list[dict], ctx: dict, k: int = OPEN_MEASURE) -> int:
    """Measure how much the likeliest opening clips move in their first quarter second (insight.open_motion),
    for the ones the analysis didn't reach (it measures only the best shots of a large library). Returns how
    many were measured."""
    todo = [s for s in pool if s.get("kind") == "video" and s.get("src")
            and (s.get("insight") or {}).get("open_motion") is None]
    todo.sort(key=lambda s: -role_score(s, "hook", ctx))
    n = 0
    for s in todo[:k]:
        try:
            from .insight import open_motion
            om = open_motion(s)
        except Exception:
            om = None
        if om is not None:
            s.setdefault("insight", {})["open_motion"] = om
            n += 1
    return n


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
        from .planner import opening_bonus
        v += opening_bonus(s)
        v += first_frame_pull(s)
        if ctx.get("tease"):  # reveal format: open on something intriguing, keep the best for the payoff
            v = 5 + 1.0 * moving(s) + 0.5 * people - 0.3 * q + first_frame_pull(s)
    elif role == "peak":
        v += 0.8 * dyn + 0.8 * moving(s) + 0.8 * pw * people
        vib = a.get("vibes") or {}
        v += 0.6 * max(vib.get("epic", 0), vib.get("energetic", 0))
        v += 0.6 if s.get("kind") == "video" and float(s.get("fps") or 0) >= 48 else 0.0
    elif role == "ending":
        v = 0.6 * q + 2.0 * (a.get("role") == "closer") + 0.8 * (a.get("mood") == "calm") + 0.8 * pw * people
        vib = a.get("vibes") or {}
        v += 0.6 * max(vib.get("serene", 0), vib.get("nostalgic", 0), vib.get("romantic", 0))   # an ending that settles
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


DETAIL_SCENES = {"detail", "food", "plants", "wildlife", "portrait"}


def shot_kind(s: dict) -> str:
    """wide | people | detail: the size of what a shot shows (for a learned style's shot mix)."""
    ai = s.get("ai") or {}
    if has_people(s):
        return "people"
    return "detail" if ai.get("scene") in DETAIL_SCENES else "wide"


def _moving(s: dict) -> bool:
    m = s.get("metrics") or {}
    return s.get("kind") == "video" and (m.get("pan", 0) > 0.004 or m.get("activity", 0) > 0.015)


# ------------------------------------------------------------- a long hold
HOLD_ACTS = ("walk", "hik", "stand", "run", "driv", "rid", "look", "gaz", "sit", "climb", "wad", "stroll")
HOLD_MOTIONS = {"drone", "walk", "walking", "push", "pan", "tilt"}
HOLD_FLAWS = {"obstructed", "cluttered", "dark", "motion-blur", "accidental", "out-of-focus", "blurry", "tilted",
              "overexposed", "finger", "noisy"}


def clip_spans(shots: list[dict]) -> dict[str, tuple[float, float]]:
    """For each video shot, the unbroken stretch of its clip that it sits in. Long clips are stored as
    back-to-back chunks; a shot held for many seconds may run on into the next ones. {shot id: (start, end)}"""
    by: dict[str, list[dict]] = {}
    for s in shots:
        if s.get("kind") == "video":
            by.setdefault(s["src"], []).append(s)
    out = {}
    for chunks in by.values():
        chunks.sort(key=lambda s: s["t0"])
        run = [chunks[0]]
        for s in chunks[1:] + [None]:
            if s is not None and abs(s["t0"] - run[-1]["t1"]) < 0.08:
                run.append(s)
                continue
            for r in run:
                out[r["id"]] = (run[0]["t0"], run[-1]["t1"])
            run = [s]
    return out


def hold_score(s: dict) -> float:
    """How well a clip carries a long opening hold: one beautiful, steady, moving view, best with someone in it
    (walking away, standing at the edge) so the eye has something to follow while the words appear."""
    a = _ai(s)
    w = a.get("watch") or {}
    v = _q(s) + 0.5 * float(a.get("aesthetic") or _q(s)) / 10
    if has_people(s):
        p = a.get("people") if isinstance(a.get("people"), dict) else {}
        act = str(p.get("activity") or "").lower()
        v += 1.0 + (0.7 if any(k in act for k in HOLD_ACTS) else 0.0)
        from .framing import person_box
        pb = person_box(s)
        if pb and (pb["x1"] - pb["x0"]) * (pb["y1"] - pb["y0"]) < 0.12:
            v += 0.5  # a small figure in a big landscape
    if {a.get("motion"), w.get("motion")} & HOLD_MOTIONS:
        v += 1.0
    elif not moving(s):
        v -= 1.0  # a locked-off view with nothing moving reads as a photo
    v += {"steady": 0.6, "slight_shake": -0.4, "shaky": -2.5}.get(w.get("stability"), 0.0)
    issues = set(a.get("issues") or [])
    v -= 1.5 * ("shaky" in issues) + 1.0 * len(issues & HOLD_FLAWS) + 0.4 * ("low-contrast" in issues)
    if w.get("framing") not in (None, "upright"):
        v -= 2.0
    return v


def hold_candidates(shots: list[dict], need: float, style: dict, open_kind: str | None = None,
                    n: int = 12) -> list[tuple[dict, float]]:
    """The clips that can be held for `need` seconds without a cut, best first: [(shot it starts on, score)].
    The hold may run on through the following chunks of the same clip (clip_spans); slowing a clip to cover the
    time is the last resort."""
    from .history import mark_down
    from .planner import colourless, taste_scores
    usable = [s for s in shots if s.get("kind") == "video" and _ai(s).get("usable", True)]
    grey = colourless([s for s in shots if _ai(s).get("usable", True)])
    spans = clip_spans(usable)
    by: dict[str, list[dict]] = {}
    for s in usable:
        by.setdefault(s["src"], []).append(s)
    first = []
    for s in usable:  # cheap pass: long enough, then judged on its own
        room = spans[s["id"]][1] - s["t0"]
        if room < need * 0.75:
            continue
        speed = min(1.0, room / need)
        first.append((hold_score(s) - 4.0 * (1.0 - speed), s, speed))
    first.sort(key=lambda c: c[0], reverse=True)
    first = first[:max(60, n * 5)]
    taste = taste_scores([c[1] for c in first], style)
    want = {"person": "people"}.get(open_kind or "", open_kind)
    out = []
    for _, s, speed in first:  # the whole stretch it would show has to hold up, not just where it starts
        end = s["t0"] + need * speed
        covered = [c for c in by[s["src"]] if c["t0"] < end - 0.3 and c["t1"] > s["t0"] + 0.3] or [s]
        sc = [hold_score(c) for c in covered]
        v = 0.6 * sum(sc) / len(sc) + 0.4 * min(sc) - 4.0 * (1.0 - speed) + taste.get(s["id"], 0.0)
        v -= 5.0 * max(mark_down(style, c, lead=True) for c in covered)  # an earlier reel's opening: not again
        v -= 4.0 * grey.get(s["id"], 0.0)  # seconds of grey sand to open a reel full of colour
        if want and (shot_kind(s) == want or (want == "action" and _moving(s))):
            v += 1.0
        out.append((s, round(v, 3)))
    out.sort(key=lambda c: c[1], reverse=True)
    picked, seen = [], set()
    for s, v in out:  # one start per clip
        if s["src"] not in seen:
            seen.add(s["src"])
            picked.append((s, v))
    return picked[:n]


def cast(chosen: list[dict], segs: list[dict], style: dict, variant: int = 0, groups: dict | None = None,
         tease: bool = False, places: dict | None = None, fmt: str = "montage",
         hold: list[tuple[dict, float]] | None = None, where: dict | None = None) -> list[dict]:
    """Put each chosen shot where it serves the story: the hook, the payoff, the ending first, then the rest.
    `hold`: the clips that can carry a long opening shot (hold_candidates); the hook is one of them.
    `where`: {shot id: place} (diversity.place_keys): a place isn't shown twice in a row, and rarely twice."""
    from .diversity import thumb_look
    pool = list(chosen)
    order: list[dict | None] = [None] * len(segs)
    st = style.get("story") or {}
    style.pop("_grammar", None)
    grammar_on = bool(st.get("grammar", True))
    ctx = {"people_weight": 1.6 if st.get("people_first", True) else 0.5, "tease": tease, "looks": {}}
    from .planner import colourless, taste_scores
    taste = taste_scores(chosen, style)  # a learned style's light, colour and people
    grey = colourless(chosen)  # a grey shot in a colourful reel doesn't open, turn or close it

    att = style.get("attention") or {}
    open_kind = (att.get("open") or {}).get("shot")
    mix = att.get("mix") or {}
    counts = {"wide": 0, "people": 0, "detail": 0}

    def open_bonus(s):  # open the way the references open (on a person, a wide view, a detail, movement)
        return 1.5 if open_kind and (shot_kind(s) == {"person": "people"}.get(open_kind, open_kind)
                                     or (open_kind == "action" and _moving(s))) else 0.0

    def mix_bonus(s):  # keep wide views, people and details in the references' proportions
        if not mix:
            return 0.0
        k = shot_kind(s)
        n = sum(counts.values()) + 1
        return 1.2 * (float(mix.get(k, 0)) - counts[k] / n)

    def used_pen(s):  # thin footage repeats shots in the pool: never the same one twice while others remain
        return -50.0 if any(o is not None and o["id"] == s["id"] for o in order) else 0.0

    def seen(s, weight=1.0):  # the place again: the viewer has been there already
        if not where:
            return 0.0
        k = where.get(s["id"], s["id"])
        return -weight * sum(1 for o in order if o is not None and where.get(o["id"], o["id"]) == k)

    def again(s, weight=1.0):  # the same kind of view again: the rig from the drone a third time; a landmark
        mark = landmark(s)      # again from another angle (two Half Domes in one reel) is a repeat as well
        return -weight * sum((1.0 if alike(o, s) else 0.0) + (2.5 if mark and landmark(o) == mark else 0.0)
                             for o in order if o is not None and o["id"] != s["id"])

    def take(idx: int, role: str, extra=None):
        if not pool:
            return
        from .history import mark_down
        base = {s["id"]: role_score(s, role, ctx) + taste.get(s["id"], 0.0) + used_pen(s) + seen(s, 2.0) + again(s)
                - 1.5 * grey.get(s["id"], 0.0) + (extra(s) if extra else 0) for s in pool}
        # what carried an earlier reel doesn't carry this one, among the shots that can carry it about as well:
        # a slot the reel turns on is never handed to a middling shot for being new
        shown = {landmark(o) for o in order if o is not None} - {""}
        new = [s for s in pool if landmark(s) not in shown] or pool  # a landmark once, whatever the slot
        # the slots a reel is remembered by (its opening, its turn, its last frame) never go to a grey shot
        new = [s for s in new if grey.get(s["id"], 0.0) < 0.5] or new
        if role == "peak":  # liveliness, people and a learned taste choose among the best, not instead of them
            near = max([_q(s) for s in new if not used_pen(s)] or [0.0]) - PEAK_Q * (0.5 if tease else 1.0)
            fit = {s["id"]: _q(s) >= near for s in new}
        else:
            near = max(base[s["id"]] for s in new) - LEAD_SLACK.get(role, 1.5)
            fit = {s["id"]: base[s["id"]] >= near for s in new}
        fit = {s["id"]: fit.get(s["id"], False) for s in pool}
        ranked = sorted(pool, reverse=True, key=lambda s: (
            fit[s["id"]], base[s["id"]] - 4.0 * mark_down(style, s, lead=True)))
        pick = ranked[min(variant, len(ranked) - 1)] if role == "hook" and variant else ranked[0]
        order[idx] = pick
        pool.remove(pick)
    roles = [s.get("role", "release") for s in segs]
    if "hook" in roles and hold:  # a long hold: one unbroken clip that lasts, never a photo
        i = roles.index("hook")
        pick = hold[min(variant, len(hold) - 1)][0]
        order[i] = pick
        t_a, t_b = pick["t0"] - 2.0, pick["t0"] + float(segs[i]["dur"]) + 2.0
        pool = [s for s in pool if s["id"] != pick["id"]  # and none of the same stretch again later
                and not (s.get("src") == pick["src"] and s.get("t0", 0) < t_b and s.get("t1", 0) > t_a)]
        # nor the view it held for seconds from another clip of that day, while other shots can fill the slots
        other = [s for s in pool if not same_view(pick, s)]
        if len(other) >= len(segs) - 1:
            pool = other
    elif "hook" in roles:
        measure_openers(pool, ctx)
        take(roles.index("hook"), "hook", open_bonus if open_kind else None)
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
    if fmt == "list" and places:
        # chapters: one place after another, the best place last. The whole reel, not only the free slots: the
        # opening's place is the first chapter and the ending's the last, so no place comes back half way
        from .formats import list_order, short_place
        last = len(segs) - 1
        keep = [i for i in (hook_i, last) if order[i] is not None and len(segs) > 2]
        free = [i for i in range(len(segs)) if i not in keep]

        def at(s):
            return short_place(places.get(s["id"])) or "?"
        mid = sorted([order[i] for i in free if order[i] is not None] + pool, key=_q, reverse=True)
        a = at(order[hook_i]) if hook_i in keep else None
        b = at(order[last]) if last in keep else None
        # someone in the first seconds: the opening chapter's shot with a person follows a hook without one
        face = a if (a and st.get("people_first", True) and not has_people(order[hook_i])) else None
        if style.get("_named") is not None:
            # a name on every shot: each place gets about as many shots as the next (the best of each)
            have = Counter(at(order[i]) for i in keep)
            left, mid = mid, []
            while left and len(mid) < len(free):
                pl = min({at(s) for s in left}, key=lambda p: (have[p], -max(_q(s) for s in left if at(s) == p)))
                s = next(s for s in left if at(s) == pl)
                if pl == face:
                    s = next((x for x in left if at(x) == pl and has_people(x) and _q(x) >= _q(s) - 2.0), s)
                    face = None
                mid.append(s)
                left.remove(s)
                have[pl] += 1
        mid = mid[:len(free)]
        for i in free:
            order[i] = None
        seq = list_order(mid, places)
        head = [s for s in seq if a not in (None, "?") and at(s) == a]
        if a and st.get("people_first", True) and not has_people(order[hook_i]):
            head.sort(key=lambda s: not has_people(s))  # (stable: the rest keep their order)
        tail = [s for s in seq if b not in (None, "?") and at(s) == b]
        if a == b and head:  # out and back: the place is shared between the two ends
            body = [s for s in seq if at(s) != a]
            cut = (len(head) + 1) // 2 if body else len(head)
            head, tail = head[:cut], head[cut:]
        else:
            body = [s for s in seq if at(s) not in {x for x in (a, b) if x not in (None, "?")}]
        for i, sh in zip(free, _apart(head, where) + _apart(body, where, at) + _apart(tail, where)):
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
                nxt = order[i + 1] if i + 1 < len(order) else None
                for o in (prev, nxt):  # the same place on both sides of a cut reads as one shot that stutters
                    if o is not None and where and where.get(s["id"], s["id"]) == where.get(o["id"], o["id"]):
                        pen -= 2.5
                if grammar_on and prev is not None and size(s) == size(prev):
                    # shot sizes alternate (a run of wide views reads as one long establishing shot)
                    pen -= 0.8 if i > 1 and order[i - 2] is not None and size(order[i - 2]) == size(s) else 0.4
                return (pen + seen(s, 0.8) + again(s, 0.7)
                        + (_rand("mix", variant, s["id"], i) - 0.5) * (1.2 if variant else 0.3))
            ranked = sorted(pool, key=lambda s: role_score(s, role, ctx) + 0.5 * taste.get(s["id"], 0.0) + adj(s)
                            + used_pen(s) + mix_bonus(s), reverse=True)
            order[i] = ranked[0]
            counts[shot_kind(ranked[0])] += 1
            pool.remove(ranked[0])
        _long_slots_first(order, rest, segs)
        _part_places(order, rest, where)
        if st.get("grammar", True):
            style["_grammar"] = grammar(order, rest, segs, where)
    # footage thinner than the slots: repeat the best (planner merged most of these away)
    best = sorted(chosen, key=_q, reverse=True)
    for i in range(len(order)):
        if order[i] is None:
            order[i] = best[i % len(best)]
    return order


def _long_slots_first(order: list, free: list[int], segs: list[dict]) -> None:
    """Among slots that play the same part, the one that stays on screen much longer shows the clearly better
    shot: a view worth a second isn't spent on a flash while a lesser one lingers."""
    for i in sorted(free, key=lambda i: -float(segs[i]["dur"])):
        if order[i] is None:
            continue
        short = [j for j in free if order[j] is not None and segs[j].get("role") == segs[i].get("role")
                 and float(segs[i]["dur"]) >= 1.8 * float(segs[j]["dur"]) and _q(order[j]) >= _q(order[i]) + 0.6]
        if short:
            j = max(short, key=lambda j: (_q(order[j]), -float(segs[j]["dur"])))
            order[i], order[j] = order[j], order[i]


def _apart(run: list[dict], where: dict | None, chapter=None) -> list[dict]:
    """A chapter's shots in their order, but one stop never on both sides of a cut when another shot of the
    chapter can go between. `chapter`: shot -> chapter name, for a run of several chapters (each kept whole)."""
    if not where or len(run) < 3:
        return run
    out: list[dict] = []
    left = list(run)
    while left:
        ch = chapter(left[0]) if chapter else None
        prev = where.get(out[-1]["id"], out[-1]["id"]) if out else None
        pick = next((s for s in left if (not chapter or chapter(s) == ch) and where.get(s["id"], s["id"]) != prev),
                    left[0])
        out.append(pick)
        left.remove(pick)
    return out


def _part_places(order: list, free: list[int], where: dict | None) -> None:
    """Casting slot by slot can leave one place for the last slots, side by side: swap middle shots (never the
    hook, the payoff or the ending) until no place sits on both sides of a cut, as far as the footage allows."""
    if not where:
        return

    def key(i):
        return where.get(order[i]["id"], order[i]["id"]) if 0 <= i < len(order) and order[i] is not None else None

    def clashes():
        return sum(1 for i in range(1, len(order)) if key(i) is not None and key(i) == key(i - 1))
    free = [i for i in free if order[i] is not None]
    for _ in range(len(free)):
        now = clashes()
        if not now:
            return
        bad = [i for i in free if key(i) in (key(i - 1), key(i + 1))]
        best = None
        for i in bad:
            for j in free:
                if j == i:
                    continue
                order[i], order[j] = order[j], order[i]
                gain = now - clashes()
                order[i], order[j] = order[j], order[i]
                if gain > 0 and (best is None or (gain, -abs(i - j)) > best[0]):
                    best = ((gain, -abs(i - j)), i, j)
        if best is None:
            return
        _, i, j = best
        order[i], order[j] = order[j], order[i]


# ------------------------------------------------------------- story grammar
# How neighbouring shots should differ, after editors' rules of thumb: a cut changes something the eye can see
# (size, light, colour, subject), shot sizes alternate rather than repeat, each new place opens wide before its
# details, and the camera doesn't make the same move three shots running (three pushes in a row read as a slideshow).
def size(s: dict) -> str:
    """wide | medium | close: how big the subject is in the frame (the AI's shot size when it gave one)."""
    ss = _ai(s).get("shot_size")
    if ss in ("wide", "medium", "close", "detail"):
        return "close" if ss == "detail" else ss
    from .framing import person_box
    if _ai(s).get("scene") in DETAIL_SCENES and _ai(s).get("scene") != "portrait":
        return "close"
    pb = person_box(s)
    if pb:
        area = (pb["x1"] - pb["x0"]) * (pb["y1"] - pb["y0"])
        return "close" if area >= 0.22 else "medium" if area >= 0.05 else "wide"
    return "medium" if has_people(s) else "wide"


def move(s: dict) -> str | None:
    """The camera's own move in a clip (push, pan, tilt, drone, walk), None when it holds still or it's a photo."""
    if s.get("kind") != "video":
        return None
    m = str((_ai(s).get("watch") or {}).get("motion") or _ai(s).get("motion") or "").lower()
    return m if m in ("push", "pan", "tilt", "drone", "walk") else None


def _pair_cost(a: dict, b: dict, looks: dict) -> float:
    if a is None or b is None or a["id"] == b["id"]:
        return 0.0
    v = 0.0
    same = size(a) == size(b)
    v += 0.6 * same
    la, lb = looks.get(a["id"]), looks.get(b["id"])
    if same and shot_kind(a) == shot_kind(b) and la is not None and lb is not None:
        from .diversity import look_similarity
        if look_similarity(la, lb) > 0.82:
            v += 1.5  # nothing changes at the cut: the same size, subject, light and colour
    return v


def grammar_cost(order: list, where: dict | None, looks: dict) -> float:
    v = 0.0
    for i in range(1, len(order)):
        v += _pair_cost(order[i - 1], order[i], looks)
    for i in range(2, len(order)):  # the same camera move three times running
        m = [move(o) if o is not None else None for o in order[i - 2:i + 1]]
        if m[0] and m[0] == m[1] == m[2]:
            v += 1.2
    if where:  # a new place opens on a wide view when the place has one in the reel
        for i in range(1, len(order)):
            o, p = order[i], order[i - 1]
            if o is None or p is None or where.get(o["id"], o["id"]) == where.get(p["id"], p["id"]):
                continue
            k = where.get(o["id"], o["id"])
            if size(o) == "close" and any(x is not None and where.get(x["id"], x["id"]) == k and size(x) == "wide"
                                          for x in order[i + 1:]):
                v += 0.8
    return v


def grammar(order: list, free: list[int], segs: list[dict], where: dict | None = None) -> dict:
    """Swap middle shots (never the opening, the payoff or the ending; only between slots of the same part and
    about the same length, and never into a place repeat) until neighbouring shots read as a sequence: sizes
    alternate, every cut changes something, new places open wide, no camera move three times running.
    Returns {before, after, swaps} (grammar_cost of the order)."""
    from .diversity import thumb_look
    free = [i for i in free if order[i] is not None and not segs[i].get("hold")]
    looks = {o["id"]: thumb_look(o.get("thumb")) for o in order if o is not None}

    def place_clashes():
        if not where:
            return 0
        k = [where.get(o["id"], o["id"]) if o is not None else None for o in order]
        return sum(1 for i in range(1, len(k)) if k[i] is not None and k[i] == k[i - 1])

    def same_slot(i, j):
        di, dj = float(segs[i]["dur"]), float(segs[j]["dur"])
        return segs[i].get("role") == segs[j].get("role") and max(di, dj) <= 1.35 * min(di, dj)
    before = now = grammar_cost(order, where, looks)
    clash = place_clashes()
    swaps = 0
    for _ in range(2 * len(free)):
        best = None
        for x, i in enumerate(free):
            for j in free[x + 1:]:
                if not same_slot(i, j):
                    continue
                order[i], order[j] = order[j], order[i]
                c, pc = grammar_cost(order, where, looks), place_clashes()
                order[i], order[j] = order[j], order[i]
                if pc <= clash and c < now - 0.05 and (best is None or c < best[0]):
                    best = (c, pc, i, j)
        if best is None:
            break
        now, clash, i, j = best
        order[i], order[j] = order[j], order[i]
        swaps += 1
    return {"before": round(before, 2), "after": round(now, 2), "swaps": swaps}


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
        if s.get("beatless") and segs[i + 1].get("beatless") and tr in ("dissolve", "blur", "fade", "dip"):
            continue  # shots flowing into each other where the music has no beat: these are the edit, not effects
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
    # a reel speaks in two or three kinds of transition, not a catalogue: keep the most used ones
    from collections import Counter
    kinds = Counter(s["trans_out"] for s in segs[:-1] if s.get("trans_out") and not s.get("incam_out"))
    keep = {k for k, _ in kinds.most_common(3)}
    for i, s in enumerate(segs[:-1]):
        if s.get("trans_out") and not s.get("incam_out") and s["trans_out"] not in keep \
                and not (peak is not None and i == peak - 1):
            s.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
            removed += 1
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


# ---------------------------------------------------------------- the first frame
# Most people decide in the first second (Instagram reports the share who skip in the first 3 s). The reels that
# held best showed the promise in big words from the very first frame, over a moving shot with someone in it.
OPEN_MIN_SIZE = 90      # the opening line, at 1080 wide
OPEN_BY = 0.8           # a line starting before this is the opening line


def open_on_words(plan: dict, cfg: dict | None = None) -> str | None:
    """The reel's first line is fully on screen from frame one: it starts at 0, without an entrance (no fade,
    rise or typewriter), at least OPEN_MIN_SIZE big. Sung words keep the song's time; a recipe's tease or title
    keeps its lettering and only loses the entrance. Style `story.open_text: off` leaves the text as planned.
    Returns what changed, or None."""
    if str((cfg or {}).get("open_text", "auto")).lower() in ("off", "false", "0", "none"):
        return None
    ovs = plan.get("overlays") or []
    sung = str((plan.get("recipe") or {}).get("text") or "") in ("lyrics", "subtitles")
    first = None
    for o in sorted(ovs, key=lambda x: float(x.get("start", 0))):
        if float(o.get("start", 0)) >= OPEN_BY:
            break
        if o.get("type") in ("map",) or o.get("recipe") == "label":
            continue
        if o.get("recipe") == "lyric" and sung or o.get("type") == "caption" and not o.get("recipe"):
            continue   # (words heard as well as read stay with the sound)
        first = o
        break
    if first is None:
        return None
    was = float(first.get("start", 0))
    first["start"] = 0.0
    first["duration"] = round(float(first.get("duration", 2.5)) + was, 3)
    st = first.get("style") if isinstance(first.get("style"), dict) else {}
    st = {**st, "anim": "cut"}
    if st.get("size") is not None and float(st["size"]) < OPEN_MIN_SIZE:
        st["size"] = OPEN_MIN_SIZE
    elif st.get("size") is None and first.get("type") != "hook":
        st["size"] = OPEN_MIN_SIZE
    if first.get("type") == "location":
        first["type"] = "text"   # (a styled location is drawn as a line, like planedit does)
    first["style"] = st
    first.pop("motion", None)
    return f"opening line on screen from the first frame: {str(first.get('text') or '')[:40]}"
