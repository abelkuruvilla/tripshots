"""Motion text drawn with HyperFrames: the reel's words animated in a real browser (GSAP), so they can
rise out of a blur, pull focus, open their letter-spacing, write themselves on or slam in with a shake,
which the frame-by-frame sprite engine in typo.py can't do well.

typo.py still decides everything about a text element (what it says, its font, size, where it sits so
it avoids the subject, the scrim behind it); this module takes that layout and animates it. Each
element becomes a small HyperFrames page at 1080x1920, rendered once to transparent PNG frames
(cached by content in ~/.tripshots/cache/text) and blended over the reel by render.py. Without the
HyperFrames runtime (Node 22+, `tripshots maps --setup`) nothing changes: typo.py draws the text.

Motions (style text.motion: auto | off | one of these; per overlay "motion"):
  rise        words rise into place out of a blur, one after another (editorial, bold locations)
  focus       each line resolves from a soft focus pull (minimal hooks)
  tracking    letters open from wide spacing out of a haze (minimal locations)
  typewriter  typed character by character behind a caret
  slam        words drop in from large with a three-frame landing shake (bold hooks, labels)
  write       written on left to right with a soft pen edge (handwritten)
  cinema      title fades up and drifts, the line under it tracks in (cinematic location titles)
The ideas come from the HyperFrames registry's text primitives (per-word-rise, focus-blur-resolve,
tracking-in, typewriter, headline-slam, hw-write-title, titlecard-calm; Apache-2.0); the pages here are
written for TripShots so the words land exactly where typo.py put them.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np

from .config import HOME, OUT_FPS, OUT_H, OUT_W
from .util import ReelError, log

CACHE = HOME / "cache" / "text"
VERSION = "t1"
MOTIONS = ("rise", "focus", "tracking", "typewriter", "slam", "write", "cinema")
# what "auto" means for each text preset and kind of text
PRESET_MOTION = {
    "bold": {"hook": "slam", "location": "rise", "cta": "rise", "label": "slam"},
    "editorial": {"hook": "rise", "location": "cinema", "cta": "rise", "label": "rise"},
    "minimal": {"hook": "focus", "location": "tracking", "cta": "focus", "label": "tracking"},
    "handwritten": {"hook": "write", "location": "write", "cta": "write", "label": "write"},
    "typewriter": {"hook": "typewriter", "location": "typewriter", "cta": "typewriter", "label": "typewriter"},
}
_status: dict = {}


def available() -> bool:
    """Is the HyperFrames runtime installed (no install is started from here)?"""
    if "ok" not in _status:
        from .routemap import runtime_status
        st = runtime_status()
        _status["ok"] = bool(st.get("node") and st.get("installed"))
    return _status["ok"]


def motion_for(kind: str, text_cfg: dict, overlay: dict | None = None) -> str | None:
    """The motion for one overlay, or None (typo.py draws it). Captions stay with typo.py: there are
    many, they change fast and must never lag the words."""
    if kind not in ("hook", "location", "cta", "label"):
        return None
    want = str((overlay or {}).get("motion") or text_cfg.get("motion") or "auto").lower()
    if want in ("off", "none", "false", "0"):
        return None
    if want in MOTIONS:
        return want if available() else None
    preset = str(text_cfg.get("preset", "bold"))
    m = PRESET_MOTION.get(preset, PRESET_MOTION["bold"]).get(kind)
    return m if m and available() else None


# ---------------------------------------------------------------- page
def _font_css(lines: list[dict]) -> tuple[str, list[str]]:
    from .typo import FONTS
    css, files = [], []
    for name in sorted({str(l.get("font") or "montserrat").lower() for l in lines}):
        file, weight = FONTS.get(name, FONTS["montserrat"])
        if file not in files:
            files.append(file)
        css.append(f"@font-face{{font-family:'f-{name}';src:url('assets/fonts/{file}');font-weight:100 900}}"
                   f".f-{name}{{font-family:'f-{name}';" + (f"font-variation-settings:'wght' {weight};" if weight
                                                           else "") + "}")
    return "".join(css), files


def _metrics(name: str, size: int) -> tuple[int, int]:
    from .typo import font
    a, d = font(name, int(size)).getmetrics()
    return a, d


def _cues(el, n_units: int, motion: str, kind: str) -> list[float]:
    """When each animated unit lands (seconds from the element's start)."""
    times = [s.t_in for s in el.sprites if not s.behind]
    if motion in ("rise", "slam") and len(times) == n_units and max(times or [0]) > 0:
        return [float(t) for t in times]  # typo.py's timing (on the beat, or all in by 0.5 s for a hook)
    if motion == "typewriter":
        cps = max(16.0, n_units / max(0.6, el.duration * 0.4))
        return [i / cps for i in range(n_units)]
    step = min(0.09, 0.55 / max(1, n_units)) if kind == "hook" else 0.09
    return [step * i for i in range(n_units)]


def text_page(el, motion: str, kind: str) -> tuple[str, list[str]]:
    """HyperFrames page that animates a laid-out typo.TextElement. Returns (html, font files)."""
    D = round(float(el.duration), 3)
    lines = el.lines
    font_css, files = _font_css(lines)
    centered = kind in ("hook", "cta", "label")
    divs, units = [], 0
    for li, ln in enumerate(lines):
        name = str(ln.get("font") or "montserrat").lower()
        size = int(ln["size"])
        a, d = _metrics(name, size)
        from .typo import font
        w = font(name, size).getlength(ln["text"]) + float(ln.get("tracking") or 0) * max(0, len(ln["text"]) - 1)
        if motion in ("typewriter", "tracking"):
            parts = [f'<span class="u">{html.escape(c) if c != " " else "&nbsp;"}</span>' for c in ln["text"]]
            units += len(ln["text"])
        else:
            words = ln["text"].split(" ")
            parts = [f'<span class="u">{html.escape(wd)}</span>' for wd in words]
            units += len(words)
            parts = [p + ('<span class="sp"> </span>' if i < len(parts) - 1 else "") for i, p in enumerate(parts)]
        pad = 80 if centered else 0
        left = float(ln["x"]) - pad
        style = (f"left:{left:.1f}px;top:{float(ln['y']):.1f}px;width:{w + 2 * pad:.1f}px;font-size:{size}px;"
                 f"line-height:{a + d}px;letter-spacing:{float(ln.get('tracking') or 0):.2f}px;"
                 f"text-align:{'center' if centered else 'left'}")
        role = ln.get("role", "main")
        divs.append(f'<div class="ln f-{name} r-{role}" id="l{li}" data-track="{float(ln.get("tracking") or 0):.2f}" '
                    f'style="{style}">{"".join(parts)}</div>')
    cues = _cues(el, units, motion, kind)
    page = f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>{font_css}
html,body{{margin:0;padding:0;background:transparent;width:{OUT_W}px;height:{OUT_H}px;overflow:hidden}}
#root{{position:relative;width:{OUT_W}px;height:{OUT_H}px;overflow:hidden}}
.ln{{position:absolute;white-space:pre;color:#fff;text-shadow:0 3px 16px rgba(0,0,0,0.55),0 1px 3px rgba(0,0,0,0.5)}}
.u{{display:inline-block;white-space:pre;will-change:transform,filter,opacity}}
.sp{{white-space:pre}}
.u{{position:relative}}
.cur::after{{content:"";position:absolute;left:100%;top:0.12em;width:0.08em;height:0.9em;margin-left:0.04em;background:#fff}}
.blink .cur::after{{opacity:0}}
</style>
<script src="assets/gsap.min.js"></script>
</head><body>
<div id="root" data-composition-id="root" data-start="0" data-duration="{D}" data-width="{OUT_W}" data-height="{OUT_H}">
{"".join(divs)}
<script>
const D = {D}, CUES = {json.dumps([round(c, 3) for c in cues])}, MOTION = "{motion}";
const tl = gsap.timeline({{paused: true}});
const units = Array.from(document.querySelectorAll(".u"));
const lines = Array.from(document.querySelectorAll(".ln"));
const cue = i => Math.min(CUES[Math.min(i, CUES.length - 1)] || 0, Math.max(0, D - 0.6));
const lineCue = l => {{ const u = l.querySelector(".u"); return cue(units.indexOf(u)); }};
if (MOTION === "rise") {{
  units.forEach((u, i) => tl.fromTo(u, {{opacity: 0, yPercent: 42, filter: "blur(14px)"}},
    {{opacity: 1, yPercent: 0, filter: "blur(0px)", duration: 0.55, ease: "power3.out", immediateRender: true}}, cue(i)));
}} else if (MOTION === "focus") {{
  lines.forEach((l, j) => tl.fromTo(l, {{opacity: 0, scale: 1.08, filter: "blur(22px)"}},
    {{opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.8, ease: "power2.out", immediateRender: true}}, lineCue(l) + 0.08 * j));
}} else if (MOTION === "tracking") {{
  lines.forEach((l, j) => {{ const tr = parseFloat(l.dataset.track) || 0, fs = parseFloat(l.style.fontSize);
    tl.fromTo(l, {{opacity: 0, letterSpacing: (tr + 0.42 * fs) + "px", filter: "blur(6px)"}},
      {{opacity: 1, letterSpacing: tr + "px", filter: "blur(0px)", duration: 1.0, ease: "expo.out", immediateRender: true}}, 0.18 * j); }});
}} else if (MOTION === "typewriter") {{
  // the caret rides on the newest letter (letters keep their final places, so nothing shifts)
  units.forEach((u, i) => {{ gsap.set(u, {{opacity: 0}}); tl.set(u, {{opacity: 1}}, cue(i));
    tl.set(u, {{className: "u cur"}}, cue(i)); if (i > 0) tl.set(units[i - 1], {{className: "u"}}, cue(i)); }});
  const root = document.getElementById("root");
  for (let t = 0; t < D; t += 0.5) tl.set(root, {{className: (Math.round(t / 0.5) % 2) ? "blink" : ""}}, t);
}} else if (MOTION === "slam") {{
  units.forEach((u, i) => {{ const t = cue(i);
    tl.fromTo(u, {{opacity: 0, scale: 2.3}}, {{opacity: 1, scale: 1, duration: 0.16, ease: "power4.in", immediateRender: true}}, t);
    const l = u.closest(".ln");
    [[7, -4], [-5, 3], [2, -1], [0, 0]].forEach((p, k) => tl.set(l, {{x: p[0], y: p[1]}}, t + 0.16 + k / {OUT_FPS})); }});
}} else if (MOTION === "write") {{
  lines.forEach((l, j) => {{ const n = l.textContent.length, d = Math.min(1.3, 0.25 + 0.06 * n);
    l.style.setProperty("--p", "-6");
    l.style.webkitMaskImage = l.style.maskImage = "linear-gradient(90deg, #000 calc(var(--p) * 1%), transparent calc(var(--p) * 1% + 6%))";
    tl.fromTo(l, {{"--p": -6}}, {{"--p": 100, duration: d, ease: "sine.inOut", immediateRender: true}}, lineCue(l) + 0.12 * j); }});
}} else if (MOTION === "cinema") {{
  lines.forEach((l, j) => {{ if (j === 0 || l.classList.contains("r-main")) {{
      tl.fromTo(l, {{opacity: 0, y: 26, filter: "blur(8px)"}}, {{opacity: 1, y: 0, filter: "blur(0px)", duration: 1.1, ease: "power2.out", immediateRender: true}}, 0);
      tl.to(l, {{y: -8, duration: Math.max(0.1, D - 1.1), ease: "none"}}, 1.1);
    }} else {{ const tr = parseFloat(l.dataset.track) || 0, fs = parseFloat(l.style.fontSize);
      tl.fromTo(l, {{opacity: 0, letterSpacing: (tr + 0.5 * fs) + "px"}}, {{opacity: 1, letterSpacing: tr + "px", duration: 1.2, ease: "expo.out", immediateRender: true}}, 0.35 + 0.15 * j); }} }});
}}
const OUT = Math.min(0.32, D * 0.2);
tl.to(lines, {{opacity: 0, filter: "blur(8px)", y: "-=10", duration: OUT, ease: "power2.in"}}, D - OUT);
tl.set({{}}, {{}}, D);
window.__timelines = window.__timelines || {{}}; window.__timelines["root"] = tl;
</script>
</div></body></html>"""
    return page, files


# ---------------------------------------------------------------- layer
class TextFx:
    """One animated text element: scrim from typo.py, words from HyperFrames frames."""

    def __init__(self, el, motion: str, kind: str):
        from .routemap import render_page
        if not el.lines:
            raise ReelError("nothing laid out")
        self.el = el
        self.motion = motion
        page, fonts = text_page(el, motion, kind)
        frames = render_page(page, el.duration, fonts=tuple(fonts), cache=CACHE, version=VERSION, quiet=True,
                             label=f"the {kind} text ({motion})")
        self.files = sorted(Path(frames).glob("*.png"))
        self._k, self._img = -1, None

    def draw(self, frame: np.ndarray, t_abs: float) -> np.ndarray:
        import cv2
        from .typo import _scrim
        el = self.el
        t = t_abs - el.start
        if t < 0 or t > el.duration:
            return frame
        if el.scrim > 0:
            frame = _scrim(frame, el.box, el.scrim * min(1.0, t / 0.3, (el.duration - t) / 0.3))
        k = min(len(self.files) - 1, int(t * OUT_FPS + 1e-6))
        if k < 0:
            return frame
        if k != self._k:
            self._k, self._img = k, cv2.imread(str(self.files[k]), cv2.IMREAD_UNCHANGED)
        im = self._img
        if im is None or im.ndim < 3 or im.shape[2] < 4:
            return frame
        ys, xs = np.nonzero(im[..., 3] > 0)
        if not len(ys):
            return frame
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        src = im[y0:y1, x0:x1]
        a = src[..., 3:4].astype(np.float32) / 255.0
        rgb = src[..., 2::-1].astype(np.float32)
        if not frame.flags.writeable:
            frame = frame.copy()
        roi = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = (roi * (1 - a) + rgb * a + 0.5).astype(np.uint8)
        return frame


def animate(el, motion: str | None, kind: str):
    """TextFx for a laid-out element, or None when it can't be drawn (typo.py draws it then)."""
    if not motion or not getattr(el, "lines", None):
        return None
    try:
        return TextFx(el, motion, kind)
    except Exception as e:  # never lose the words over an effect
        if not _status.get("warned"):
            log(f"motion text unavailable, drawing plain text instead ({str(e)[:160]})")
            _status["warned"] = True
        return None
