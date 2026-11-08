"""Hype effects chosen at plan time, and a beat-accuracy check after rendering.

- freeze: on the biggest drop the picture freezes for ~0.5 s with a white flash, a push-in and a
  little shake, then the clip carries on (plan["freeze"] = {t, dur})
- rgb: a colour-split glitch on the first frames of some hard cuts (segment["rgb"] = true)
"""
from __future__ import annotations

import numpy as np

from .config import OUT_FPS
from .util import log


def _rand(*parts) -> float:
    from .planner import _stable_rand
    return _stable_rand(*parts)


def mark_effects(plan: dict, style: dict) -> None:
    m = style.get("motion") or {}
    segs = plan["segments"]
    total = float(plan["duration"])
    plan.pop("freeze", None)
    if m.get("freeze"):
        drops = [d for d in plan.get("drops") or [] if 0.25 * total <= d <= 0.8 * total]
        beats = plan.get("beats") or []
        if not drops and beats:  # no clear drop: the beat nearest the middle
            drops = [min(beats, key=lambda b: abs(b - total * 0.5))]
        best = None
        for d in drops:
            for i, s in enumerate(segs):
                a, b = s["out_start"], s["out_start"] + s["dur"]
                if s.get("panel") or not (a - 0.01 <= d < b):
                    continue
                at_cut = abs(d - a) < 0.08 and i > 0
                if at_cut:
                    d = a  # freeze the very first frame of the new shot, after a hard cut
                elif i > 0 and segs[i - 1].get("trans_out") and d - a < segs[i - 1].get("trans_dur", 0.3) / 2 + 0.05:
                    break  # still inside the incoming transition: the frame would be a blend
                tail = (s.get("trans_dur") or 0.3) / 2 if s.get("trans_out") else 0.0
                fd = min(0.55, b - d - tail - 0.1)
                if fd >= 0.3:
                    best = (round(int(round(d * OUT_FPS)) / OUT_FPS, 4), round(fd, 3), i if at_cut else None)
                break
            if best:
                break
        if best and best[2] is not None:  # the classic hype move: hard cut -> flash -> freeze
            segs[best[2] - 1].update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
        if best:
            plan["freeze"] = {"t": best[0], "dur": best[1]}
            for s in segs:  # no beat punch / bulge fighting the freeze's own push-in
                if s["out_start"] - 0.01 <= best[0] < s["out_start"] + s["dur"]:
                    s["hero"] = True
    share = float(m.get("rgb_split", 0) or 0)
    n = 0
    for i, s in enumerate(segs):
        s.pop("rgb", None)
        if i == 0 or share <= 0 or segs[i - 1].get("trans_out") or segs[i - 1].get("incam_out") \
                or s.get("level") == "calm":
            continue
        if _rand("rgb", s.get("shot_id", ""), i, style.get("shots", {}).get("variant", 0)) < share:
            s["rgb"] = True
            n += 1
    n_shake = mark_shakes(plan, m)
    if plan.get("freeze") or n or n_shake:
        log("hype: " + ", ".join(x for x in (f"freeze-frame at {plan['freeze']['t']:.2f}s" if plan.get("freeze")
                                            else "", f"colour-split on {n} cut(s)" if n else "",
                                            f"camera shake on {n_shake} drop(s)" if n_shake else "") if x))


SLOW_RAMPS = {"slam", "bullet", "impact"}


def mark_shakes(plan: dict, m: dict) -> int:
    """Camera shake on a drop is a hype move: it suits a hard-hitting drop in a busy part of an energetic reel,
    and jars everywhere else. A segment gets `shake: true` only when
      * the style asks for it (motion.shake_on_drop), and the reel isn't mostly calm,
      * the cut lands on a drop in an intense section,
      * the shot plays at real speed or faster (shaking slow motion looks like a mistake),
      * no freeze-frame already hits there (it has its own jolt).
    A clone shakes only where the reference itself shakes (`ref_shake`, measured from the reference)."""
    segs = plan["segments"]
    for s in segs:
        s.pop("shake", None)
    n = 0
    if plan.get("clone") is not None:
        for s in segs:
            if s.get("ref_shake"):
                s["shake"] = True
                n += 1
        if not m.get("freeze"):  # --hype adds the usual drop shakes on top
            return n
    if not m.get("shake_on_drop") or not segs:
        return n
    calm = sum(1 for s in segs if s.get("level") == "calm") / len(segs)
    if calm >= 0.6:
        return n
    for s in segs:
        if (s.get("drop") and s.get("level") == "intense" and not s.get("hero") and not s.get("panel")
                and s.get("ramp") not in SLOW_RAMPS and float(s.get("speed", 1) or 1) >= 0.95 and not s.get("shake")):
            s["shake"] = True
            n += 1
    return n


# --------------------------------------------------------------- compositor helpers
def freeze_frame(frozen: np.ndarray, k: int, n: int) -> np.ndarray:
    import cv2
    from .motion import affine
    q = k / max(1, n - 1)
    ease = 1 - (1 - q) ** 3
    sx = int(round(10 * np.sin(k * 2.1) * (1 - q)))
    sy = int(round(7 * np.cos(k * 1.7) * (1 - q)))
    fr = affine(frozen, 1.0 + 0.09 * ease, 0.0, sx, sy)
    a = 0.85 * max(0.0, 1 - k / 4)
    if a > 0:
        fr = cv2.addWeighted(fr, 1 - a, np.full_like(fr, 255), a, 0)
    return fr


def rgb_split(frame: np.ndarray, k: int, frames: int = 4, px: int = 18) -> np.ndarray:
    d = int(round(px * (1 - k / frames)))
    if d <= 0:
        return frame
    out = frame.copy()
    out[:, d:, 0] = frame[:, :-d, 0]      # red to the right
    out[:, :-d, 2] = frame[:, d:, 2]      # blue to the left
    return out


# --------------------------------------------------------------- QC
def check_beats(video, plan: dict) -> dict:
    """Find every hard cut in the rendered file and compare it with the plan and the beat."""
    from .clone import _luma_track
    _, diff = _luma_track(video, w=64)
    segs = plan["segments"]
    beats = np.array(plan.get("beats") or [])
    starts = [int(round(s["out_start"] * OUT_FPS)) for s in segs]
    checked, found, exact, within1, on_beat, worst = 0, 0, 0, 0, 0, 0
    for i in range(1, len(segs)):
        if segs[i - 1].get("trans_out"):
            continue
        f = starts[i]
        if f >= len(diff) - 1:
            continue
        checked += 1
        if len(beats) and float(np.min(np.abs(beats - f / OUT_FPS))) <= 1.0 / OUT_FPS + 1e-3:
            on_beat += 1
        lo, hi = max(1, f - 3), min(len(diff) - 1, f + 3)
        local = diff[lo:hi + 1]
        base = np.median(diff[max(1, f - 15):min(len(diff), f + 15)]) + 1e-3
        k = int(np.argmax(local))
        if local[k] < 2.5 * base or local[k] < 4:
            continue  # two similar shots: the cut can't be seen, so it can't be measured
        found += 1
        off = lo + k - f
        exact += off == 0
        within1 += abs(off) <= 1
        worst = max(worst, abs(off))
    res = {"hard_cuts": checked, "measured": found, "exact": exact, "within_1_frame": within1,
           "worst_frames": worst, "planned_on_beat": on_beat}
    if checked:
        log(f"beat check: {within1}/{found} measurable cuts land within 1 frame of the plan "
            f"(worst {worst} frame{'s' if worst != 1 else ''}); {on_beat}/{checked} cuts sit on a beat")
    return res
