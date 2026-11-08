"""Match cuts: let movement carry across the cut.

Editors hide cuts in motion: when the camera is panning right at the end of one shot and the next shot keeps
moving right, the cut feels like one move; a whip transition swipes the way the camera was already going.
`apply(plan, by_id)` measures how the camera moves in every video shot's window (phase correlation on a few
small frames), then
  * reorders neighbouring middle shots (setup / release) so their directions continue where it can,
  * points every whip transition the way the outgoing shot moves,
  * turns a soft dissolve/blur between two shots moving the same way into a clean match cut.
"""
from __future__ import annotations

import subprocess

import cv2
import numpy as np

from .util import ffmpeg_base, log

MOVABLE = ("setup", "release")


def flow(src: str, t0: float, length: float, w: int = 96) -> tuple[float, float] | None:
    """Camera movement in a window: (dx, dy) in frame widths per second, + = moving right / down."""
    fps = 6
    h = int(w * 9 / 16)
    p = subprocess.run(ffmpeg_base() + ["-ss", f"{max(0, t0):.3f}", "-t", f"{max(0.4, length):.3f}", "-i", src, "-an",
                                        "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    a = np.frombuffer(p.stdout, np.uint8)
    n = len(a) // (w * h)
    if n < 3:
        return None
    fr = a[: n * w * h].reshape(n, h, w).astype(np.float32)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    dx, dy = [], []
    for i in range(n - 1):
        (sx, sy), resp = cv2.phaseCorrelate(fr[i], fr[i + 1], win)
        if resp > 0.05:
            dx.append(-sx / w * fps)
            dy.append(-sy / w * fps)
    if not dx:
        return None
    return float(np.median(dx)), float(np.median(dy))


def direction(f: tuple[float, float] | None, thr: float = 0.04) -> str | None:
    if not f:
        return None
    dx, dy = f
    if max(abs(dx), abs(dy)) < thr:
        return None
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _measure(plan: dict) -> None:
    for s in plan["segments"]:
        if s.get("kind") != "video" or s.get("panel") or "flow" in s:
            continue
        f = flow(s["src"], float(s.get("in", 0)), float(s["dur"]) * float(s.get("speed", 1) or 1))
        s["flow"] = [round(f[0], 4), round(f[1], 4)] if f else None


def _continuity(a: dict, b: dict) -> float:
    da, db = direction(a.get("flow")), direction(b.get("flow"))
    if da and db:
        return 2.0 if da == db else (-1.0 if {da, db} in ({"left", "right"}, {"up", "down"}) else 0.0)
    return 0.0


def _refit(seg: dict, by_id: dict) -> None:
    from .planner import _best_window
    sh = by_id.get(seg.get("shot_id"))
    if not sh or seg.get("kind") != "video" or seg.get("ramp"):
        return
    speed = float(seg.get("speed", 1) or 1)
    avail = sh["t1"] - sh["t0"]
    if avail < seg["dur"] * speed:
        speed = max(0.6, avail / seg["dur"])
        seg["speed"] = round(speed, 3)
    seg["in"] = round(_best_window(sh, seg["dur"] * speed), 3)
    seg.pop("flow", None)


SLOT = ("out_start", "dur", "idx", "level", "drop", "role", "trans_out", "trans_dur", "trans_params", "incam_out",
        "incam_in", "hero", "shake", "beats", "line")


def apply(plan: dict, by_id: dict) -> int:
    segs = plan["segments"]
    _measure(plan)
    # reorder runs of movable slots so motion continues across cuts
    swaps = 0
    i = 0
    while i < len(segs):
        if segs[i].get("role") not in MOVABLE or segs[i].get("panel"):
            i += 1
            continue
        j = i
        while j < len(segs) and segs[j].get("role") in MOVABLE and not segs[j].get("panel"):
            j += 1
        run = list(range(i, j))
        if len(run) >= 3:
            contents = [{k: v for k, v in segs[k].items() if k not in SLOT} for k in run]
            prev = segs[i - 1] if i > 0 else None
            order, left = [], list(range(len(contents)))
            while left:
                if prev is None:
                    pick = left[0]
                else:
                    pick = max(left, key=lambda c: (_continuity(prev, contents[c]), -left.index(c)))
                order.append(pick)
                left.remove(pick)
                prev = contents[pick]
            if order != sorted(order):
                for k, c in zip(run, order):
                    slot = {kk: segs[k][kk] for kk in SLOT if kk in segs[k]}
                    moved = c != run.index(k)
                    segs[k].clear()
                    segs[k].update({**contents[c], **slot})
                    if moved:
                        _refit(segs[k], by_id)
                        swaps += 1
                _measure(plan)
        i = j
    # transitions follow the motion
    matched = 0
    for a, b in zip(segs, segs[1:]):
        da, db = direction(a.get("flow")), direction(b.get("flow"))
        if a.get("trans_out") == "whip" and da:
            a["trans_params"] = {**(a.get("trans_params") or {}),
                                 "direction": {"right": "left", "left": "right", "down": "up", "up": "down"}[da]}
        if da and da == db:
            if a.get("trans_out") in ("dissolve", "blur"):
                a.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
            if not a.get("trans_out"):
                a["match"] = "motion"
                matched += 1
    if swaps or matched:
        log(f"match cuts: {matched} cut(s) carried by the camera's motion" + (f", {swaps} shot(s) reordered" if swaps else ""))
    return matched
