"""Match cuts: let movement carry across the cut.

Editors hide cuts in motion: when the camera is panning right at the end of one shot and the next shot keeps
moving right, the cut feels like one move; a whip transition swipes the way the camera was already going.
`apply(plan, by_id)` measures how the camera moves in every video shot's window (phase correlation on a few
small frames), then
  * reorders neighbouring middle shots (setup / release) so their directions continue where it can,
  * points every whip transition the way the outgoing shot moves,
  * turns a soft dissolve/blur between two shots moving the same way into a clean match cut,
then `carry` looks at each cut itself (the camera in the last moments of one shot, the first moments of the
next) and keeps the movement flowing: no left-then-right "ping-pong", no push-in cut into a pull-out, no dead
stop straight after a fast move. It fixes what it can (a Ken Burns move or a pan follows the camera before it,
a clip starts a moment earlier or later where its camera already moves the right way) and reports the rest in
plan `continuity`.
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


def motion(src: str, t0: float, length: float, w: int = 96) -> tuple[float, float, float] | None:
    """(dx, dy, zoom) per second over a short window: dx/dy in frame widths (+ = the camera moves right / down),
    zoom as the relative growth of the picture (+ = pushing in)."""
    fps = 10
    h = int(w * 9 / 16)
    p = subprocess.run(ffmpeg_base() + ["-ss", f"{max(0, t0):.3f}", "-t", f"{max(0.3, length):.3f}", "-i", src, "-an",
                                        "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    a = np.frombuffer(p.stdout, np.uint8)
    n = len(a) // (w * h)
    if n < 2:
        return None
    fr = a[: n * w * h].reshape(n, h, w)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rx, ry = xx - w / 2, yy - h / 2
    r2 = rx ** 2 + ry ** 2 + 1.0
    dx, dy, zs = [], [], []
    for i in range(n - 1):
        (sx, sy), resp = cv2.phaseCorrelate(fr[i].astype(np.float32), fr[i + 1].astype(np.float32), win)
        f = cv2.calcOpticalFlowFarneback(fr[i], fr[i + 1], None, 0.5, 2, 9, 2, 5, 1.1, 0)
        zs.append(float(np.median((f[..., 0] * rx + f[..., 1] * ry) / r2)) * fps)
        if resp > 0.05:
            dx.append(-sx / w * fps)
            dy.append(-sy / w * fps)
    if not zs:
        return None
    return (float(np.median(dx)) if dx else 0.0, float(np.median(dy)) if dy else 0.0, float(np.median(zs)))


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
    if not sh or seg.get("kind") != "video" or seg.get("ramp") or seg.get("hold"):
        return
    speed = float(seg.get("speed", 1) or 1)
    avail = sh["t1"] - sh["t0"]
    if avail < seg["dur"] * speed:
        speed = max(0.6, avail / seg["dur"])
        seg["speed"] = round(speed, 3)
    seg["in"] = round(_best_window(sh, seg["dur"] * speed), 3)
    seg.pop("flow", None)


SLOT = ("out_start", "dur", "idx", "level", "drop", "role", "trans_out", "trans_dur", "trans_params", "incam_out",
        "incam_in", "hero", "shake", "beats", "line", "beatless", "breath", "colour_in", "black_tail")


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
    carry(plan, by_id)
    return matched


# ------------------------------------------------------------------ continuity at each cut
END = 0.4      # seconds of each side of a cut that are looked at
MOVE = 0.04    # frame widths a second: slower is still
ZOOM = 0.025   # relative zoom a second: slower is still
FAST = 0.22    # a fast move: stopping dead after it jars
KB_V = 0.03    # how fast a Ken Burns drift moves, for comparison


def _ends(s: dict) -> tuple | None:
    """(head, tail) camera motion of a segment as shown, each (dx, dy, zoom) per second of the reel."""
    if s.get("panel"):
        return None
    if s.get("layout") == "kenburns":
        v = {"right": (KB_V, 0, 0), "left": (-KB_V, 0, 0), "in": (0, 0, 0.04), "in_rot": (0, 0, 0.04),
             "out": (0, 0, -0.04), "up": (0, -KB_V, 0), "down": (0, KB_V, 0)}.get(s.get("kb", "in"), (0, 0, 0))
        return v, v
    if s.get("kind") != "video" or not s.get("src"):
        return None
    if "_ends" in s:
        return s["_ends"]
    sp = float(s.get("speed", 1) or 1)
    if s.get("ramp"):
        return None  # a speed ramp's motion changes through the shot: left as the ramp makes it
    inn, used = float(s.get("in", 0)), float(s["dur"]) * sp
    look = min(END, float(s["dur"]) / 2) * sp
    h, t = motion(s["src"], inn, look), motion(s["src"], inn + used - look, look)
    if h is None or t is None:
        return None
    h, t = tuple(v * sp for v in h), tuple(v * sp for v in t)
    if s.get("layout") == "pan":  # the pan adds its own sideways drift
        way = -1 if s.get("pan_reverse") else 1
        h, t = (h[0] + way * KB_V, h[1], h[2]), (t[0] + way * KB_V, t[1], t[2])
    s["_ends"] = (h, t)
    return h, t


def _way(m) -> tuple[str | None, float]:
    """The dominant movement: left/right/up/down/push/pull, and its speed."""
    dx, dy, z = m
    lat = max(abs(dx), abs(dy))
    if lat >= MOVE and lat >= abs(z) * 1.5:
        return ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy > 0 else "up"), lat
    if abs(z) >= ZOOM:
        return ("push" if z > 0 else "pull"), abs(z)
    return None, max(lat, abs(z))


OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up", "push": "pull", "pull": "push"}
SAY = {"left": "moves left", "right": "moves right", "up": "tilts up", "down": "tilts down", "push": "pushes in",
       "pull": "pulls back"}


def clash(a: dict, b: dict) -> str | None:
    """What goes wrong with the movement across the cut from a to b (None if it carries or nothing moves)."""
    if a.get("trans_out") in ("whip", "spin", "zoom_in", "zoom_out", "flash", "glitch") or a.get("incam_out"):
        return None  # the transition is the movement
    ea, eb = _ends(a), _ends(b)
    if not ea or not eb:
        return None
    wa, va = _way(ea[1])
    wb, vb = _way(eb[0])
    if wa and wb and OPPOSITE[wa] == wb:
        return f"{SAY[wa]}, then {SAY[wb]}"
    if wa and not wb and va >= FAST and not a.get("trans_out") and b.get("kind") == "video" and not b.get("breath"):
        return f"{SAY[wa]} fast, then stops dead"
    return None


def speed_note(a: dict, b: dict) -> str | None:
    """Both sides move the same way at very different speeds: noted, not changed (it can be the point)."""
    ea, eb = _ends(a), _ends(b)
    if not ea or not eb:
        return None
    (wa, va), (wb, vb) = _way(ea[1]), _way(eb[0])
    if wa and wa == wb and min(va, vb) > 0 and max(va, vb) / min(va, vb) > 3.0:
        return f"{SAY[wa]} on both sides, at very different speeds"
    return None


def _follow(b: dict, way: str, head: bool = True) -> bool:
    """Point a Ken Burns move or a pan the way the camera next to it moves."""
    if b.get("role") in ("hook", "peak", "ending") or b.get("breath"):
        return False
    if b.get("layout") == "kenburns":
        kb = {"right": "right", "left": "left", "up": "up", "down": "down", "push": "in", "pull": "out"}[way]
        if b.get("kb") == kb:
            return False
        b["kb"] = kb
        return True
    if b.get("layout") == "pan" and way in ("left", "right"):
        b["pan_reverse"] = way == "left"
        b.pop("_ends", None)
        return True
    return False


def _slide(s: dict, sh: dict | None, other, at_head: bool) -> bool:
    """Start a clip up to a second earlier or later, where its camera at the cut moves with (not against) the
    shot on the other side. Only clips with footage to spare; the shot stays almost the same."""
    if not sh or s.get("kind") != "video" or s.get("hold") or s.get("ramp") or s.get("role") in ("hook",):
        return False
    sp = float(s.get("speed", 1) or 1)
    need = float(s["dur"]) * sp
    lo, hi = float(sh["t0"]), float(sh["t1"]) - need
    if hi - lo < 0.4:
        return False
    was = float(s.get("in", 0))
    ow, _ = _way(other)
    for d in (0.4, -0.4, 0.8, -0.8, 1.2, -1.2):
        x = min(hi, max(lo, was + d))
        if abs(x - was) < 0.2:
            continue
        s["in"] = round(x, 3)
        s.pop("_ends", None)
        e = _ends(s)
        if e:
            w, _ = _way(e[0] if at_head else e[1])
            if w is None or w == ow or OPPOSITE.get(w) != ow:
                if not (w is None and ow and _way(other)[1] >= FAST and at_head):
                    return True
    s["in"] = was
    s.pop("_ends", None)
    return False


def carry(plan: dict, by_id: dict) -> dict:
    """Keep the camera's movement flowing across every cut; returns (and stores) plan `continuity`."""
    segs = plan["segments"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:  # each shot's two ends, measured side by side
        list(ex.map(_ends, segs))
    fixed, left, notes, carried = [], [], [], 0
    for i, (a, b) in enumerate(zip(segs, segs[1:])):
        why = clash(a, b)
        if not why:
            ea, eb = _ends(a), _ends(b)
            if ea and eb and _way(ea[1])[0] and _way(ea[1])[0] == _way(eb[0])[0]:
                carried += 1
            n = speed_note(a, b)
            if n:
                notes.append(f"cut {i + 1}-{i + 2}: {n}")
            continue
        ea, eb = _ends(a), _ends(b)
        wa = _way(ea[1])[0]
        wb = _way(eb[0])[0]
        ok = (wa and _follow(b, wa)) or (wb and _follow(a, wb, head=False)) \
            or _slide(b, by_id.get(b.get("shot_id")), ea[1], True) \
            or _slide(a, by_id.get(a.get("shot_id")), eb[0], False)
        if ok and not clash(a, b):
            fixed.append(f"cut {i + 1}-{i + 2}: {why}")
        else:
            left.append(f"cut {i + 1}-{i + 2}: {why}")
    for s in segs:
        s.pop("_ends", None)
    out = {"cuts": max(0, len(segs) - 1), "carried": carried, "fixed": fixed, "left": left,
           **({"notes": notes} if notes else {})}
    plan["continuity"] = out
    if fixed or left:
        log(f"continuity: {carried} cut(s) carried by the movement"
            + (f"; fixed {len(fixed)} ({'; '.join(fixed[:3])})" if fixed else "")
            + (f"; still jars: {'; '.join(left[:3])}" if left else ""))
    return out
