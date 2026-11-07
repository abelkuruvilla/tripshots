"""Multi-panel moments: split screens and grids whose panels appear, and keep cutting to new
clips, on the beat.

A panel segment in plan.json looks like
  {"panel": "grid4", "dur": 4.0, ..., "clips": [
      {"rect": [x, y, w, h], "t0": 0.0, "t1": 4.0, "intro": "pop", <shot fields: kind, src, in, ...>}, ...]}
Times are relative to the segment start. Each clip is rendered at its panel size (cropped around
its subject), then the panels are composited into one 1080x1920 segment, so transitions, beat
punch and text work on top exactly as for a single shot.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .config import OUT_FPS, OUT_H, OUT_W
from .motion import ease_out
from .util import ffmpeg_base

GUTTER = 10


def _even(v: float) -> int:
    return int(v) // 2 * 2


def layout_rects(kind: str) -> list[tuple[int, int, int, int]]:
    """Panel rectangles (even sizes: H.264 needs them)."""
    g = GUTTER
    if kind == "split2":  # two stacked
        h = _even((OUT_H - g) / 2)
        return [(0, 0, OUT_W, h), (0, h + g, OUT_W, OUT_H - h - g)]
    if kind == "split3":  # three horizontal strips
        h = _even((OUT_H - 2 * g) / 3)
        return [(0, i * (h + g), OUT_W, h if i < 2 else OUT_H - 2 * (h + g)) for i in range(3)]
    if kind == "grid4":  # 2x2
        w, h = _even((OUT_W - g) / 2), _even((OUT_H - g) / 2)
        return [(0, 0, w, h), (w + g, 0, OUT_W - w - g, h), (0, h + g, w, OUT_H - h - g),
                (w + g, h + g, OUT_W - w - g, OUT_H - h - g)]
    if kind == "columns3":  # three tall columns
        w = _even((OUT_W - 2 * g) / 3)
        return [(i * (w + g), 0, w if i < 2 else OUT_W - 2 * (w + g), OUT_H) for i in range(3)]
    raise ValueError(kind)


INTRO_FOR = {"split2": ["slide_left", "slide_right"], "split3": ["slide_left", "slide_right", "slide_left"],
             "grid4": ["pop", "pop", "pop", "pop"], "columns3": ["wipe_down", "wipe_up", "wipe_down"]}
INTRO_DUR = 0.24


class _Clip:
    def __init__(self, spec: dict, path: Path, n: int, u0: int):
        self.spec, self.path, self.n, self.u0 = spec, path, n, u0
        x, y, w, h = spec["rect"]
        self.rect = (int(x), int(y), int(w), int(h))
        self.proc = None
        self.pos = -1
        self.buf = None

    def frame(self, k: int) -> np.ndarray:
        x, y, w, h = self.rect
        k = max(0, min(k, self.n - 1))
        if self.proc is None:
            self.proc = subprocess.Popen(ffmpeg_base() + ["-i", str(self.path), "-f", "rawvideo", "-pix_fmt", "rgb24",
                                                          "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        size = w * h * 3
        while self.pos < k:
            b = self.proc.stdout.read(size)
            if len(b) < size:
                self.pos = k
                break
            self.buf = np.frombuffer(b, np.uint8).reshape(h, w, 3)
            self.pos += 1
        if self.buf is None:
            self.buf = np.zeros((h, w, 3), np.uint8)
        return self.buf

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait()
            self.proc = None


def _place(canvas: np.ndarray, img: np.ndarray, rect, intro: str, q: float) -> None:
    """Draw a panel frame into its rect with its entrance animation (q: 0..1 progress)."""
    x, y, w, h = rect
    e = ease_out(min(1.0, max(0.0, q)))
    if q >= 1 or intro == "cut":
        canvas[y:y + h, x:x + w] = img
        return
    region = canvas[y:y + h, x:x + w]
    if intro in ("slide_left", "slide_right"):
        off = int(round((1 - e) * w)) * (-1 if intro == "slide_left" else 1)
        if off < 0:   # coming in from the left edge
            region[:, : w + off] = img[:, -off:]
        elif off > 0:
            region[:, off:] = img[:, : w - off]
        else:
            region[:] = img
    elif intro in ("wipe_down", "wipe_up"):
        rows = int(round(e * h))
        if intro == "wipe_down":
            region[:rows] = img[:rows]
        else:
            region[h - rows:] = img[h - rows:]
    elif intro == "pop":
        import cv2
        s = 0.72 + 0.28 * e
        nw, nh = max(2, int(w * s)), max(2, int(h * s))
        small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        ox, oy = (w - nw) // 2, (h - nh) // 2
        alpha = min(1.0, q / 0.5)
        sub = region[oy:oy + nh, ox:ox + nw]
        sub[:] = (sub.astype(np.float32) * (1 - alpha) + small.astype(np.float32) * alpha).astype(np.uint8)
    else:
        region[:] = img


def composite_panel_segment(e: dict, clip_files: list[tuple[dict, Path, int]], length: float, lead: float,
                            out: Path, enc: list[str], bg: tuple[int, int, int] = (12, 12, 12)) -> None:
    """clip_files: (clip spec, rendered file, n_frames) in the same order as e['clips']."""
    n = max(1, int(round(length * OUT_FPS)))
    clips = []
    for spec, path, nf in clip_files:
        u0 = int(round((lead + float(spec["t0"])) * OUT_FPS))
        clips.append(_Clip(spec, path, nf, u0))
    ends = {}
    for c in clips:
        t1 = float(c.spec["t1"])
        ends[id(c)] = n if t1 >= float(e["dur"]) - 1e-3 else int(round((lead + t1) * OUT_FPS))
    cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(OUT_FPS),
                           "-i", "-"] + enc + [str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for k in range(n):
            canvas = np.empty((OUT_H, OUT_W, 3), np.uint8)
            canvas[:] = bg
            first = min(clips, key=lambda c: c.u0)
            for c in sorted(clips, key=lambda c: c.u0):  # later clips on top (they slide over)
                if c.u0 - (0 if c is not first else 10 ** 6) > k or k >= ends[id(c)]:
                    continue
                q = (k - c.u0) / (INTRO_DUR * OUT_FPS) if c is not first else 1.0
                _place(canvas, c.frame(max(0, k - c.u0)), c.rect, c.spec.get("intro", "cut"), q)
            proc.stdin.write(canvas.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        for c in clips:
            c.close()
    err = proc.stderr.read().decode(errors="ignore")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"panel render failed: {err[-400:]}")


# ------------------------------------------------------------- planning
def plan_panel_clips(kind: str, dur: float, beats_rel: list[float], shots: list[dict], mode: str,
                     beat_len: float) -> list[dict]:
    """Assign shots to panels and times. reveal: one panel appears per step;
    cycle: after all are shown, panels keep cutting to new shots on each step."""
    rects = layout_rects(kind)
    intros = INTRO_FOR[kind]
    step_beats = 1 if beat_len >= 0.38 else 2
    steps = [b for b in beats_rel[::step_beats] if b < dur - 0.25]
    if not steps or steps[0] > 0.05:
        steps = [0.0] + steps
    clips = []
    shot_iter = iter(shots)
    current: dict[int, dict] = {}
    for si, t in enumerate(steps):
        if si < len(rects):
            r = si
        elif mode == "cycle":
            r = si % len(rects)
        else:
            break
        sh = next(shot_iter, None)
        if sh is None:
            break
        prev = current.get(r)
        if prev is not None:
            prev["t1"] = round(t + INTRO_DUR, 4)  # stays underneath while the new one slides in
        c = {"rect": list(rects[r]), "t0": round(t, 4), "t1": round(dur, 4),
             "intro": intros[r] if si < len(rects) else intros[r], "shot": sh}
        clips.append(c)
        current[r] = c
    return clips
