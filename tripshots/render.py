"""Render a plan.json into a 1080x1920 MP4 with ffmpeg."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import retime
from .config import CANVAS, OUT_FPS
from .fx import color_chain, hdr_chain, seg_color
from .util import ReelError, ffmpeg_base, hwaccel_args, log, short_hash

RENDER_VERSION = "r7"  # bump when shot rendering changes so cached shots are rebuilt

# intermediates: near-lossless and quick; the final pass does the real compression
def _enc() -> list[str]:
    """Encoder args for the intermediate segment files (hardware when available, see encode.py)."""
    from . import encode
    return encode.args("segment") + ["-r", str(OUT_FPS)]


def _frames(sec: float) -> int:
    return max(1, int(round(sec * OUT_FPS)))


def _video_layout(e: dict, length: float, size: tuple[int, int] | None = None) -> list[str]:
    OW, OH = size or CANVAS.size
    w, h = e["src_w"], e["src_h"]
    lay = e["layout"]
    if lay == "blur_fill":
        return [f"split[a][b];[a]scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},"
                f"boxblur=40:2,eq=brightness=-0.08[bg];[b]scale={OW}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"]
    # scale to cover the frame
    scale = f"scale=-2:{OH}:flags=lanczos" if w / h > OW / OH else f"scale={OW}:-2:flags=lanczos"
    sw = (w * OH / h) if w / h > OW / OH else OW
    excess = max(0.0, sw - OW)
    if lay == "pan" and excess > 4:
        # travel across the subject: window centre goes from its left edge to its right edge
        # (or the reverse, to match the camera's own movement when it pans right-to-left)
        a = float(e.get("pan_from", 0.15)) * sw - OW / 2
        b = float(e.get("pan_to", 0.85)) * sw - OW / 2
        from .framing import PAN_SPEED
        half = min(abs(b - a) / 2, float(e.get("pan_speed", PAN_SPEED)) * sw * length / 2)  # slow, around the middle
        mid = (a + b) / 2
        a, b = mid - half, mid + half
        if e.get("pan_reverse"):
            a, b = b, a
        x0, x1 = max(0.0, min(excess, a)), max(0.0, min(excess, b))
        from .motion import EASE_EXPR  # the learned style's way of moving (learn: camera `ease`), else gentle
        ease = EASE_EXPR.get(e.get("ease") or "sine", EASE_EXPR["sine"]).format(x=f"min(t/{length:.3f}\\,1)")
        return [scale, f"crop={OW}:{OH}:x='{x0:.1f}+({x1 - x0:.1f})*{ease}':y='(ih-{OH})/2'"]
    if lay == "crop" and excess > 4:
        track = e.get("_track_pts")
        if track:
            from .framing import piecewise_expr
            pts = [(t, cx * sw - OW / 2) for t, cx in track]
            return [scale, f"crop={OW}:{OH}:x='{piecewise_expr(pts, 0.0, excess)}':y='(ih-{OH})/2'"]
        cx = float(e.get("subject_x", 0.5)) * sw
        x = max(0.0, min(excess, cx - OW / 2))
        return [scale, f"crop={OW}:{OH}:{x:.0f}:(ih-{OH})/2"]
    sh = h * OW / w
    if excess <= 4 and sh - OH > 4 and (e.get("subject") or {}).get("cy") is not None:
        # an upright clip in a wide frame: the window sits on the subject, not on the middle of the picture
        y = max(0.0, min(sh - OH, float(e["subject"]["cy"]) * sh - OH / 2))
        return [scale, f"crop={OW}:{OH}:0:{y:.0f}"]
    return [scale, f"crop={OW}:{OH}"]


def render_video_seg(e: dict, length: float, color: dict, out: Path,
                     size: tuple[int, int] | None = None, rate: float = OUT_FPS) -> None:
    """One video shot at its (constant) speed. Speed-ups average the frames they skip (motion blur);
    `rate` other than 30 renders at that frame rate (the retimer's real-time pass)."""
    speed = float(e.get("speed", 1.0))
    src_need = length * speed + 0.5
    if e.get("stabilize") and not e.get("_stabilized"):  # a shaky clip: from its stabilised window (stabilize.py)
        from . import stabilize
        e = stabilize.apply(e, src_need)
    pad = []
    size = size or CANVAS.size
    if e.get("_band") and size == CANVAS.size:  # cinematic letterbox: the picture in a band, black bars
        size = (CANVAS.w, int(e["_band"]))
        pad = [f"pad={CANVAS.w}:{CANVAS.h}:0:{(CANVAS.h - size[1]) // 2}:black"]
    from . import compose   # the window placed on the frames that actually play (people kept whole, looking room)
    e = compose.apply(e, length * speed, size)
    if e.get("track") and e.get("layout") == "crop" and not e.get("_framed"):
        from .framing import track_x
        try:
            e = {**e, "_track_pts": track_x(e["src"], e["in"], length * speed, {**e, "speed": speed},
                                            float(e.get("subject_x", 0.5)))}
        except Exception:
            pass
    pre = []
    pre += hdr_chain({"hdr": e.get("hdr"), "transfer": e.get("transfer")})
    if e.get("log"):  # flat log footage made normal before anything colours it (camlog.py)
        from .camlog import chain as log_chain
        pre += log_chain(e)
    if e.get("freeze"):  # one frame held for the whole slot
        speed, src_need = 1.0, 0.5
        pre += ["trim=end_frame=1", f"tpad=stop_mode=clone:stop_duration={length + 1:.3f}"]
    elif e.get("reverse"):  # exactly the window, played backwards (ffmpeg buffers it: slots are short)
        src_need = length * speed + 1.0 / rate
        pre.append("reverse")
    if abs(speed - 1.0) > 1e-3:
        pre.append(f"setpts=PTS/{speed:.4f}")
    blur = int(round(float(e.get("fps") or 30) * speed / rate * 0.7)) if speed >= 1.3 else 0
    if blur >= 2:  # fast: blend the frames in between, like a slow shutter, then keep 30 a second
        mid = _video_layout(e, length, size) + [f"tmix=frames={min(blur, 8)}", f"fps={rate}"]
    else:
        mid = [f"fps={rate}"] + _video_layout(e, length, size)
    vf = ",".join(pre + mid + color_chain(seg_color(color, e)) + pad
                  + ["tpad=stop_mode=clone:stop_duration=3", "setsar=1", "format=yuv420p"])
    base = ffmpeg_base()
    nf = max(1, int(round(length * rate)))
    enc = _enc() if rate == OUT_FPS else _enc()[:-2] + ["-r", f"{rate:g}"]
    cmd = base + hwaccel_args() + ["-ss", f"{e['in']:.3f}", "-t", f"{src_need:.3f}", "-i", e["src"],
                                   "-an", "-filter_complex", vf, "-frames:v", str(nf)] + enc + [str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 and hwaccel_args():
        proc = subprocess.run(base + ["-ss", f"{e['in']:.3f}", "-t", f"{src_need:.3f}", "-i", e["src"], "-an",
                                      "-filter_complex", vf, "-frames:v", str(nf)] + enc + [str(out)],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReelError(f"segment render failed for {Path(e['src']).name}: {proc.stderr[-600:]}")


def _ease(x: float, name: str | None = None) -> float:
    from .motion import ease
    return ease(name, x)


def render_photo_seg(e: dict, length: float, color: dict, zoom: float, out: Path,
                     size: tuple[int, int] | None = None) -> None:
    """Smooth sub-pixel Ken Burns rendered in Python, piped to ffmpeg."""
    pad = []
    size = size or CANVAS.size
    if e.get("_band") and size == CANVAS.size:  # cinematic letterbox
        size = (CANVAS.w, int(e["_band"]))
        pad = [f"pad={CANVAS.w}:{CANVAS.h}:0:{(CANVAS.h - size[1]) // 2}:black"]
    OW, OH = size
    im = Image.open(e["still"]).convert("RGB")
    W, H = im.size
    # pre-scale (high quality) so the cover area is ~1.1x output: per-frame warps then
    # stay close to 1:1, which keeps them sharp, alias-free and fast
    target_h = OH * 1.1 if W / H > OW / OH else (OW * 1.1) * H / W
    if H > target_h * 1.02:
        f = target_h / H
        im = im.resize((int(W * f), int(H * f)), Image.Resampling.LANCZOS)
        W, H = im.size
    src = np.asarray(im)
    ar = OW / OH
    if W / H > ar:
        ch, cw = H, H * ar
    else:
        cw, ch = W, W / ar
    excess = W - cw
    sb = e.get("subject") or {}
    sx = float(sb.get("cx", e.get("subject_x", 0.5)))
    sy = float(sb.get("cy", 0.5))
    cx_sub = max(cw / 2, min(W - cw / 2, sx * W))
    cy_sub = sy * H
    mode = e.get("kb", "in")
    if W / H > 2.2 and not e.get("focus") and mode in ("in", "out", "in_rot", "up", "down"):
        mode = "left" if sx > 0.5 else "right"  # a panorama with no one subject: travel across it instead
    from .framing import PAN_SPEED
    max_travel = float(e.get("pan_speed", PAN_SPEED)) * W * length
    if sb:  # never zoom so far that the subject is cut off
        bw_px = max(1.0, (sb["x1"] - sb["x0"]) * W * 1.12)
        bh_px = max(1.0, (sb["y1"] - sb["y0"]) * H * 1.12)
        zoom = max(1.04, min(zoom, cw / bw_px, ch / bh_px)) if zoom > 1.04 else zoom
    n = _frames(length)
    frames_kw = []
    rots = []
    for k in range(n):
        lin = k / max(1, n - 1)
        p = _ease(lin, e.get("ease")) if mode in ("in", "out", "in_rot") else 0.35 * lin + 0.65 * _ease(lin, e.get("ease"))
        rot = 0.0
        if mode in ("in", "in_rot"):
            z = 1 + (zoom - 1) * p
            # drift towards the subject as we push in
            cx, cy = cx_sub, H / 2 + (cy_sub - H / 2) * p
            if mode == "in_rot":
                rot = 2.5 * p
        elif mode == "out":
            z = zoom - (zoom - 1) * p
            cx, cy = cx_sub, cy_sub + (H / 2 - cy_sub) * p
        elif mode in ("up", "down"):
            z = 1 + (zoom - 1) * 0.6
            span = max(0.0, H - ch / z)
            a, b = (0.75, 0.25) if mode == "up" else (0.25, 0.75)
            cy = ch / z / 2 + (a + (b - a) * p) * span
            cx = cx_sub
        else:
            z = 1.04 + 0.03 * p
            win = cw / z
            if sb and (sb["x1"] - sb["x0"]) * W > win and not e.get("focus"):
                # a wide subject: travel along it, slowly, around its middle
                half = min(((sb["x1"] - sb["x0"]) * W - win) / 2, max_travel / 2)
                mid = (sb["x0"] + sb["x1"]) / 2 * W
                a_c, b_c = mid - half, mid + half
            else:  # subject fits: drift gently past it, passing through its centre mid-shot
                half = min(0.12 * win, max_travel / 2)
                a_c, b_c = cx_sub - half, cx_sub + half
            if mode == "left":
                a_c, b_c = b_c, a_c
            cx = a_c + (b_c - a_c) * p
            cy = H / 2
        bw, bh = cw / z, ch / z
        x0 = max(0.0, min(W - bw, cx - bw / 2))
        y0 = max(0.0, min(H - bh, cy - bh / 2))
        frames_kw.append((x0, y0, x0 + bw, y0 + bh))
        rots.append(rot)
    mover = None
    if e.get("parallax") and (size == CANVAS.size or pad):
        from . import parallax
        d = parallax.depth(src, e.get("depth_key"))
        if parallax.worth_it(d):
            # drift the way the Ken Burns moves (or left to right), about 2.5 % of the frame for the nearest things
            way = -1.0 if mode in ("left", "out") else 1.0
            mover = parallax.Mover(src, d, 0.025 * OW, way)
    vf = ",".join(color_chain(seg_color(color, e)) + pad + ["setsar=1", "format=yuv420p"]) or "null"
    cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", str(OUT_FPS),
                           "-i", "-", "-vf", vf] + _enc() + [str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for k_f, ((x0, y0, x1, y1), rot) in enumerate(zip(frames_kw, rots)):
            sx_, sy_ = OW / (x1 - x0), OH / (y1 - y0)
            M = np.array([[sx_, 0, -x0 * sx_], [0, sy_, -y0 * sy_]], dtype=np.float64)
            if rot:
                # rotate about the frame centre, scaled just enough that no corner shows
                r = np.deg2rad(rot)
                cover = abs(np.cos(r)) + abs(np.sin(r)) * max(OW / OH, OH / OW)
                R = cv2.getRotationMatrix2D((OW / 2, OH / 2), rot, cover)
                M = R @ np.vstack([M, [0, 0, 1]])
            fr = cv2.warpAffine(src, M, (OW, OH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            if mover is not None:
                fr = mover.frame(fr, M[:2], k_f / max(1, len(frames_kw) - 1))
            proc.stdin.write(np.ascontiguousarray(fr).tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="ignore")
    proc.wait()
    if proc.returncode != 0:
        raise ReelError(f"photo render failed: {err[-400:]}")


def render_panel_seg(e: dict, length: float, lead: float, color: dict, zoom: float, out: Path,
                     seg_dir: Path) -> None:
    """Render each panel clip at its own size, then composite them with their beat-timed entrances."""
    from .panels import composite_panel_segment
    dur = float(e["dur"])
    parts = []
    if color.get("grade"):  # one vignette per tile looks wrong
        color = {**color, "vignette": False, "grade": {**color["grade"], "vignette": False}}
    for c in e["clips"]:
        x, y, w, h = [int(v) for v in c["rect"]]
        t0 = float(c["t0"])
        L = (length - lead - t0) if float(c["t1"]) >= dur - 1e-3 else (float(c["t1"]) - t0)
        L = max(2 / OUT_FPS, L)
        key = short_hash(repr(sorted((k, str(v)) for k, v in c.items())) + f"{L:.4f}{w}x{h}" + repr(color)
                         + RENDER_VERSION, 14)
        f = seg_dir / f"panel_{key}.mp4"
        if not f.exists():
            tmp = f.with_name(f.stem + ".part.mp4")
            if c["kind"] == "video":
                render_video_seg(c, L, color, tmp, size=(w, h))
            else:
                render_photo_seg(c, L, color, min(zoom, 1.1), tmp, size=(w, h))
            tmp.replace(f)
        parts.append((c, f, _frames(L)))
    composite_panel_segment(e, parts, length, lead, out, _enc())


def render_popout_seg(e: dict, length: float, color: dict, out: Path) -> bool:
    """Photo in a frame with the subject stepping out of it. False -> caller falls back to Ken Burns."""
    from .popout import animate_frames
    try:
        frames = animate_frames(e.get("src") or e["still"], _frames(length), OUT_FPS,
                                bg=e.get("popout_bg", "paper"), variant=e.get("popout_variant", "auto"),
                                lut=e.get("lut"))
    except Exception as ex:
        log(f"pop-out frame skipped for {Path(e.get('src', '')).name}: {ex}")
        return False
    if frames is None:
        return False
    vf = ",".join(color_chain({**seg_color(color, e), **({"lut": None, "vignette": False} if e.get("lut") else {})}) + ["setsar=1", "format=yuv420p"]) or "null"
    cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{CANVAS.w}x{CANVAS.h}", "-r", str(OUT_FPS),
                           "-i", "-", "-vf", vf] + _enc() + [str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for fr in frames:
            proc.stdin.write(np.ascontiguousarray(fr).tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="ignore")
    proc.wait()
    if proc.returncode != 0:
        raise ReelError(f"pop-out render failed: {err[-400:]}")
    return True


def render_retimed_seg(e: dict, length: float, color: dict, out: Path, lead: float = 0.0) -> None:
    """Speed ramps and smooth slow motion (retime.py): render the source at real time (at its own frame
    rate, up to 60, so 60 fps clips give real slow motion), then pick the frame for every output frame:
    fast parts average the frames they pass (motion blur), slow parts are made of in-between frames
    (optical flow, or a cross-fade with smooth: blend)."""
    from . import retime
    n = _frames(length)
    rate = float(min(60.0, max(OUT_FPS, round(float(e.get("fps") or OUT_FPS)))))
    k = retime.seg_keys(e, length, lead)
    pos = retime.positions(k, n, rate, OUT_FPS)
    src_frames = int(math.ceil(pos[-1])) + 3
    smooth = e.get("smooth", "flow")
    tmp = out.with_name(out.stem + ".src.mp4")
    render_video_seg({**e, "speed": 1.0, "ramp": None}, src_frames / rate, color, tmp, rate=rate)
    rd = subprocess.Popen(ffmpeg_base() + ["-i", str(tmp), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{CANVAS.w}x{CANVAS.h}", "-r", str(OUT_FPS),
                           "-i", "-"] + _enc() + [str(out)]
    wr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    size = CANVAS.w * CANVAS.h * 3
    buf: dict[int, np.ndarray] = {}
    flows: dict = {}
    read = -1
    last = None

    def get(i: int) -> np.ndarray:
        nonlocal read, last
        while read < i:
            b = rd.stdout.read(size)
            if len(b) < size:
                break
            read += 1
            last = np.frombuffer(b, np.uint8).reshape(CANVAS.h, CANVAS.w, 3)
            buf[read] = last
        for old in [j for j in buf if j < i - 10]:
            del buf[old]
        for old in [j for j in flows if j < i - 1]:
            del flows[old]
        return buf.get(i, last if last is not None else np.zeros((CANVAS.h, CANVAS.w, 3), np.uint8))

    try:
        prev = 0.0
        for kk in range(n):
            p = pos[kk]
            spd = p - prev if kk else 1.0
            if spd > 1.5:  # fast: average the frames we pass over -> motion blur
                i0, i1 = int(prev), int(p)
                frames = [get(j).astype(np.float32) for j in range(max(i0 + 1, i1 - 5), i1 + 1)]
                fr = (sum(frames) / len(frames)).astype(np.uint8)
            else:  # real time or slow: the frame itself, or one made in between
                i = int(p)
                a = p - i
                fa = get(i)
                if a < 0.04 or smooth == "off":
                    fr = fa
                elif a > 0.96:
                    fr = get(i + 1)
                elif smooth == "blend":
                    fr = cv2.addWeighted(fa, 1 - a, get(i + 1), a, 0)
                else:
                    fb = get(i + 1)
                    fr = fa if fb is fa else retime.interp_flow(fa, fb, a, flows, i)
            wr.stdin.write(np.ascontiguousarray(fr).tobytes())
            prev = p
        wr.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        rd.stdout.close()
        rd.kill()
        rd.wait()
        tmp.unlink(missing_ok=True)
    err = wr.stderr.read().decode(errors="ignore")
    wr.wait()
    if wr.returncode != 0:
        raise ReelError(f"speed ramp render failed: {err[-400:]}")


class _SegReader:
    """Streams one rendered segment's frames in order (one ffmpeg decode process)."""

    def __init__(self, path: Path, n_frames: int, size: tuple[int, int] | None = None):
        self.path, self.n = path, n_frames
        self.proc = None
        self.pos = -1
        self.last = None
        self.w, self.h = size or CANVAS.size
        self.size = self.w * self.h * 3

    def frame(self, k: int) -> np.ndarray:
        k = max(0, min(k, self.n - 1))
        if self.proc is None:
            self.proc = subprocess.Popen(ffmpeg_base() + ["-i", str(self.path), "-f", "rawvideo", "-pix_fmt", "rgb24",
                                                          "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        while self.pos < k:
            buf = self.proc.stdout.read(self.size)
            if len(buf) < self.size:  # ran out (rounding): hold the last frame
                self.pos = k
                break
            self.last = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
            self.pos += 1
        if self.last is None:
            self.last = np.zeros((self.h, self.w, 3), np.uint8)
        return self.last

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait()
            self.proc = None


# what an overlay's own `style` may set (the rest comes from the plan's text preset)
OVERLAY_STYLE = ("font", "size", "uppercase", "anim", "position", "color", "line_gap", "exit", "legible",
                 "colors", "fit", "fixed", "lead_font", "lead_size", "y", "x", "fill", "lead_color", "shadow")


class TextTrack:
    """All on-screen text of a plan. Each element is laid out lazily on the first frame it
    appears, so its position can avoid the subject and busy parts of that actual frame."""

    def __init__(self, plan: dict, beats: list[float], native: bool = False, fx: bool = True):
        from .typo import PRESETS
        self.native = native  # build everything, draw only what an editor can't rebuild (see render)
        self.use_fx = fx      # motion text (HyperFrames); off for a quick still
        tcfg = plan.get("text") or {}
        preset = PRESETS.get(str(tcfg.get("preset", "bold")), PRESETS["bold"])
        self.cfg = {}
        from .typo import CAPTION, legible, scaled
        readable = bool(tcfg.get("legible", True))
        for kind in ("hook", "location", "cta", "label"):
            base = dict(preset[kind])
            own = dict(tcfg.get(kind) or {})
            if "font" not in own:
                own.pop("size", None)  # sizes only make sense with the font they were chosen for
            own = {k: v for k, v in own.items() if v is not None and k not in ("mode", "duration", "start", "text")}
            if own.get("position") in ("upper", "center", "lower", "auto", "lower_left", "upper_left"):
                pass
            else:
                own.pop("position", None)
            base.update(own)
            self.cfg[kind] = scaled(legible(kind, base) if readable else base)
        self.cfg["text"] = dict(self.cfg["hook"])  # a line someone added in the editor: the hook's lettering
        if plan.get("story"):  # a story reel's hook must read inside the first second
            self.cfg["hook"]["fast_in"] = True
        self.cfg["caption"] = scaled(legible("caption", {**CAPTION, **{k: v for k, v in (tcfg.get("caption") or {}).items()
                                                                      if v is not None}}))
        band = int((plan.get("frame") or {}).get("band") or 0)
        self.letterbox = 0 < band < CANVAS.h
        self.band = band
        if 0 < band < CANVAS.h:  # letterbox: words live in the black bars, never over the picture
            from . import typo
            bar = (CANVAS.h - band) // 2
            typo.BANDS["bar_top"] = (max(typo.SAFE["top"], bar - 400), bar - 30)
            typo.BANDS["bar_bottom"] = (CANVAS.h - bar + 40, min(typo.SAFE["bottom"] + 40, CANVAS.h - bar + 420))
            self.cfg["hook"]["position"] = "bar_top"
            for k in ("label", "cta", "caption", "location"):
                self.cfg[k]["position"] = "bar_bottom"
            self.cfg["location"]["behind"] = "off"
        self.specs = sorted([o for o in plan.get("overlays") or []
                             if o["type"] in ("hook", "location", "cta", "label", "caption", "text")], key=lambda o: o["start"])
        caps = [o for o in self.specs if o["type"] == "caption"]
        for h in (o for o in self.specs if o["type"] == "hook"):
            h0, h1 = float(h["start"]), float(h["start"]) + float(h["duration"])
            if any(float(c["start"]) < h1 and float(c["start"]) + float(c["duration"]) > h0 for c in caps) \
                    and self.cfg["hook"].get("position", "auto") in ("auto", "center", "lower") and not self.letterbox:
                self.cfg["hook"]["position"] = "upper"  # subtitles sit low: the hook goes up, out of their way
        self.built: dict[int, object] = {}
        self.fx: dict[int, object] = {}  # motion text drawn with HyperFrames (hfx.py)
        self.tcfg = tcfg
        self.beats = beats

    def draw(self, frame, t: float, seg: dict):
        from .typo import build_hook, build_location, build_location_behind, format_coords, scaled, split_place
        for k, o in enumerate(self.specs):
            st, du = float(o["start"]), float(o["duration"])
            if not (st <= t <= st + du):
                continue
            el = self.built.get(k)
            if el is None:
                subj = seg.get("subject_out")
                if o["type"] == "location":
                    main, sub = (o.get("main"), o.get("sub")) if o.get("main") else split_place(o["text"])
                    coords = o.get("coords") or format_coords(o.get("gps"))
                    el = None
                    seg_left = seg["out_start"] + seg["dur"] - st
                    if (str(self.cfg["location"].get("behind", "auto")) in ("auto", "on", "True", "true")
                            and seg_left >= 1.4 and not seg.get("panel")):
                        # only within one full-screen shot: a new skyline mid-title looks like a glitch
                        el = build_location_behind(main, sub, coords, st, min(du, seg_left),
                                                   self.cfg["location"], frame)
                    if el is None:
                        el = self._clear_of_others(k, lambda pos: build_location(
                            main, sub, coords, st, du, {**self.cfg["location"], **({"position": pos} if pos else {})},
                            frame, subj), self.cfg["location"].get("position"))
                else:
                    cfg = self.cfg[o["type"] if o["type"] in ("cta", "label", "caption", "text") else "hook"]
                    if isinstance(o.get("style"), dict):
                        # this line's own lettering (a recipe's words look and sit like its reference's)
                        cfg = {**cfg, **scaled({kk: v for kk, v in o["style"].items()
                                                if kk in OVERLAY_STYLE and v is not None})}
                    # lettering set on the picture keeps off the shot's subject (same line for every word of a shot)
                    # a line held across several shots sits where the plan put it (recipes.held_position): the
                    # subject of the shot it starts on isn't the subject of the others
                    own = isinstance(o.get("style"), dict) and o["style"].get("position") in ("upper", "center", "lower")
                    one_shot = st + du <= float(seg.get("out_start", 0.0)) + float(seg.get("dur", du)) + 0.05
                    avoid = self._subject_rows(seg) if own and one_shot and not cfg.get("fixed") else None
                    el = self._clear_of_others(k, lambda pos: build_hook(
                        o["text"], st, du, {**cfg, **({"position": pos, "y": None} if pos else {})}, frame,
                        self.beats, subj, avoid=None if pos else avoid, lead=o.get("lead")), cfg.get("position"))
                self.built[k] = el
                from .scripts import script_of
                if self.use_fx and not self.native and not self.baked(k) and not script_of(o.get("text") or ""):
                    from .hfx import animate, motion_for
                    fx = animate(el, motion_for(o["type"], self.tcfg, o), o["type"])
                    if fx is not None:
                        self.fx[k] = fx
            if self.native and not self.baked(k):
                continue
            frame = (self.fx.get(k) or el).draw(frame, t)
        return frame

    def _subject_rows(self, seg: dict):
        """(subject top, subject bottom, top and bottom of where words may go) in output pixels, or None. Words
        stay on the picture and inside the part of the screen the app's own buttons and caption leave free."""
        from .typo import SAFE
        subj = seg.get("subject_out") or {}
        if seg.get("panel") or "y0" not in subj or "y1" not in subj:
            return None
        top, h = ((CANVAS.h - self.band) // 2, self.band) if self.letterbox else (0, CANVAS.h)
        y0, y1 = top + float(subj["y0"]) * h, top + float(subj["y1"]) * h
        if y1 - y0 > 0.6 * h:   # the subject is the whole view: nowhere to move to
            return None
        return y0, y1, max(top, SAFE["top"] - 18), min(top + h, SAFE["bottom"] + 18)

    def _clear_of_others(self, k: int, build, preferred: str | None):
        """Build text element k where it doesn't cover another line on screen at the same time (the hook and a
        subtitle, two labels): first where its style wants it, then in the other bands."""
        o = self.specs[k]
        a0, a1 = float(o["start"]), float(o["start"]) + float(o["duration"])
        # sharing the screen = overlapping by more than a frame: a word that replaces the last one stays put
        eps = 1.0 / OUT_FPS
        others = [self.built[j] for j, oj in enumerate(self.specs) if j != k and j in self.built
                  and self.built[j] is not None and float(oj["start"]) < a1 - eps
                  and float(oj["start"]) + float(oj["duration"]) > a0 + eps and not self.baked(j)]

        def clash(el) -> bool:
            x0, y0, x1, y1 = el.box
            return any(x0 < b[2] + 10 and b[0] < x1 + 10 and y0 < b[3] + 24 and b[1] < y1 + 24
                       for b in (e.box for e in others))
        el = build(None)
        if not others or not clash(el):
            return el
        from .typo import BANDS
        bars = [b for b in ("bar_top", "bar_bottom") if b in BANDS] if self.letterbox else []
        order = bars + [b for b in ("lower", "upper", "center") if b != preferred] if o["type"] == "caption" \
            else bars + [b for b in ("upper", "lower", "center") if b != preferred]
        for pos in order:
            alt = build(pos)
            if not clash(alt):
                return alt
        return el

    def baked(self, k: int) -> bool:
        """Is overlay k part of the picture (not native text)? Titles behind the skyline are."""
        el = self.built.get(k)
        return bool(el is not None and any(getattr(sp, "behind", False) for sp in el.sprites))


def _prepare_transitions(plan: dict) -> None:
    """Normalise transition names/durations (also upgrades plans made by older versions)."""
    from .motion import NATURAL, normalize
    segs = plan["segments"]
    legacy_d = float(plan.get("transition_duration", 0.3))
    for i, e in enumerate(segs):
        name = normalize(e.get("trans_out")) if i < len(segs) - 1 else None
        e["trans_out"] = name
        if not name:
            e["trans_dur"] = 0.0
            continue
        d = float(e.get("trans_dur") or NATURAL.get(name, legacy_d))
        from .motion import MASKS  # a masked reveal may take its shots whole: one reveal runs into the next
        d = min(d, (1.0 if name in MASKS else 0.9) * min(e["dur"], segs[i + 1]["dur"]))
        e["trans_dur"] = max(2, int(round(d * OUT_FPS / 2)) * 2) / OUT_FPS
        e.setdefault("trans_params", {})


def render(plan: dict, out_path: Path, work: Path, workers: int = 2, native_text: bool = False,
           info: dict | None = None) -> Path:
    """Render a plan. With a hardware encoder, a failed encode falls back to libx264 once (segments
    that already rendered are kept: only what failed is redone).

    native_text: lay out the hook / cta / labels / plain location titles but don't draw them (for
    editors that add them as their own, editable text; edits.py). Titles behind the skyline and maps
    are still drawn, because no editor can rebuild them. `info["texts"]` receives the TextTrack."""
    from . import encode
    from .framing import use_plan
    import time
    t0 = time.time()
    use_plan(plan)  # an upright or a horizontal frame, and the picture's shape in it
    log(f"encoder: {encode.describe()}" + (f" · horizontal {CANVAS.w}x{CANVAS.h}" if CANVAS.horizontal else ""))
    try:
        out = _render(plan, out_path, work, workers, native_text, info)
    except ReelError as e:
        if not encode.using_hardware():
            raise
        encode.disable(str(e))
        out = _render(plan, out_path, work, workers, native_text, info)
    # a render that "succeeds" without writing a new file would hand back the previous video: never
    p = Path(out)
    if not p.exists() or p.stat().st_size == 0 or p.stat().st_mtime < t0 - 2:
        raise ReelError(f"the render wrote no new video ({p.name}): the previous file is still there")
    log(f"render took {time.time() - t0:.0f}s")
    return out


class Backdrops:
    """Backdrop swaps (segment `backdrop` {items, every}): on each beat the person is set in front of another place
    (a picture) or a flat colour, and the last beat shows their real background again. The person is cut out of
    every other frame (rembg u2netp) and the mask is smoothed over time, so the edge doesn't boil."""

    def __init__(self):
        self.masks: dict = {}
        self.bgs: dict = {}

    def _bg(self, item, w: int, h: int) -> np.ndarray:
        key = (str(item), w, h)
        if key not in self.bgs:
            if isinstance(item, (list, tuple)):
                self.bgs[key] = np.full((h, w, 3), [int(v) for v in item[:3]], np.uint8)
            else:
                im = cv2.imread(str(item))
                if im is None:
                    self.bgs[key] = None
                else:
                    im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
                    s = max(w / im.shape[1], h / im.shape[0])
                    im = cv2.resize(im, (int(im.shape[1] * s + 1), int(im.shape[0] * s + 1)), interpolation=cv2.INTER_AREA)
                    y, x = (im.shape[0] - h) // 2, (im.shape[1] - w) // 2
                    self.bgs[key] = np.ascontiguousarray(im[y:y + h, x:x + w])
        return self.bgs[key]

    def frame(self, i: int, seg: dict, fr: np.ndarray, t: float) -> np.ndarray:
        bd = seg["backdrop"]
        items = bd.get("items") or []
        k = int((t - float(seg["out_start"])) / max(0.1, float(bd.get("every") or 0.5)))
        if t < float(seg["out_start"]) or k >= len(items):
            return fr  # (on the way in, and the last beat: the real place)
        h, w = fr.shape[:2]
        bg = self._bg(items[k], w, h)
        if bg is None:
            return fr
        n = int(round(t * OUT_FPS))
        last = self.masks.get(i)
        if last is not None and last[1] is None:
            return fr  # no person to keep in front: the shot plays as it is
        if last is None or n - last[0] >= 2:
            from . import nodes
            m = nodes.people_mask(fr, width=320)  # the person only (upright figures), never a truck or a road
            if m is None:
                if last is None:
                    self.masks[i] = (n, None)
                    return fr
                m = last[1]
            elif last is not None:
                m = 0.55 * m + 0.45 * last[1]
            self.masks[i] = last = (n, m)
        return cv2.blendLinear(fr, bg, last[1], 1.0 - last[1])


class People:
    """The people in a shot as a soft mask, followed over time (cut out every other frame, smoothed so the edge
    doesn't boil), for the moves that keep the person and change the world round them (segment `isolate`), and
    single masks for a frozen pose or a clone (`at`)."""

    def __init__(self):
        self.track: dict = {}

    def at(self, fr: np.ndarray) -> np.ndarray | None:
        from . import nodes
        return nodes.people_mask(fr, width=360)

    def follow(self, i: int, fr: np.ndarray, n: int) -> np.ndarray | None:
        last = self.track.get(i)
        if last is not None and last[1] is None and n - last[0] < 6:
            return None   # nobody found a moment ago: look again in a few frames
        if last is None or last[1] is None or n - last[0] >= 2:
            m = self.at(fr)
            if m is None:
                if last is None or last[1] is None:
                    self.track[i] = (n, None)
                    return None
                m = last[1]
            elif last is not None and last[1] is not None:
                m = 0.55 * m + 0.45 * last[1]
            self.track[i] = last = (n, m)
        return last[1]


def zoom_focus(seg: dict, focus: str = "face") -> tuple[float, float]:
    """Where the flash zoom aims when the cut-out finds nobody: the planner's subject box as it sits in the frame
    (a crop or pan centres it across, an upright clip or a photo keeps it where it is)."""
    b = seg.get("subject") or {}
    try:
        x0, x1, y0, y1 = (float(b[k]) for k in ("x0", "x1", "y0", "y1"))
    except (KeyError, TypeError, ValueError):
        return 0.5, 0.42
    x = (x0 + x1) / 2 if seg.get("layout") in ("fill", "kenburns", None) else 0.5
    y = y0 + (0.15 if focus == "face" and seg.get("people") else 0.5) * (y1 - y0)
    return x, y


def _flash_zoom(fr: np.ndarray, seg: dict, t: float, people: "People", i: int, n: int, zfocus: dict) -> np.ndarray:
    from .motion import flash_zoom, flash_zoom_at, subject_point
    zp = seg["zoompunch"]
    z, fl, bl = flash_zoom_at(zp, t)
    if z <= 1.001 and fl <= 0.01:
        return fr
    focus = str(zp.get("focus", "face"))
    pt = subject_point(people.follow(i, fr, n), focus) if seg.get("people") else None
    last = zfocus.get(i)
    if pt is None:
        pt = last or zoom_focus(seg, focus)
    elif last is not None:   # follow the person smoothly: a jumpy cut-out shouldn't shake the frame
        pt = (0.8 * last[0] + 0.2 * pt[0], 0.8 * last[1] + 0.2 * pt[1])
    zfocus[i] = pt
    flash = str(zp.get("flash", "white"))
    return flash_zoom(fr, pt, z, 0.0 if flash == "none" else fl, bl, flash)


def _thumb_squares(paths: list, size: int = 360) -> list[np.ndarray]:
    out = []
    for path in paths or []:
        im = cv2.imread(str(path))
        if im is None:
            continue
        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        s = min(im.shape[:2])
        y, x = (im.shape[0] - s) // 2, (im.shape[1] - s) // 2
        out.append(cv2.resize(im[y:y + s, x:x + s], (size, size), interpolation=cv2.INTER_AREA))
    return out


def _wall_tiles(mo: dict, w: int, h: int, shot: np.ndarray | None = None) -> dict:
    """The photo wall's pictures, each cut to its cell's shape: {cell index: RGB array}. With the shot's own frame,
    the cells its subject stands in are left clear (found with the cut-out; the plan only guessed)."""
    from .motion import grid_shape
    c, r = grid_shape(w, h, int(mo.get("cols", 8)))
    cw, ch = max(2, w // c), max(2, h // r)
    clear = set()
    if shot is not None:
        from . import nodes
        m = nodes.cutout(cv2.resize(shot, (c * 24, r * 24), interpolation=cv2.INTER_AREA))
        if m is not None and 0.01 < float((m > 0.5).mean()) < 0.5:
            cover = cv2.resize((m > 0.5).astype(np.float32), (c, r), interpolation=cv2.INTER_AREA)
            clear = {int(k) for k in np.nonzero(cover.ravel() > 0.06)[0]}
    out = {}
    for k, path in (mo.get("cells") or {}).items():
        if int(k) in clear:
            continue
        im = cv2.imread(str(path))
        if im is None:
            continue
        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        s = max(cw / im.shape[1], ch / im.shape[0])
        im = cv2.resize(im, (max(cw, int(im.shape[1] * s + 0.5)), max(ch, int(im.shape[0] * s + 0.5))),
                        interpolation=cv2.INTER_AREA)
        y, x = (im.shape[0] - ch) // 2, (im.shape[1] - cw) // 2
        out[int(k)] = np.ascontiguousarray(im[y:y + ch, x:x + cw])
    return out


# ------------------------------------------------------------------ picture in picture
def pip_box(p: dict) -> tuple[int, int, int, int]:
    """(x, y, w, h) on the canvas of a picture-in-picture: `x`, `y` its centre (0..1), `scale` its width as a share
    of the frame's, its height from the source's shape (kept inside the frame)."""
    w = max(32, int(round(CANVAS.w * max(0.1, min(1.0, float(p.get("scale", 0.4))))) // 2 * 2))
    ar = float(p.get("src_h") or 9) / float(p.get("src_w") or 16)
    h = max(32, min(CANVAS.h, int(round(w * ar)) // 2 * 2))
    x = int(round(float(p.get("x", 0.7)) * CANVAS.w - w / 2))
    y = int(round(float(p.get("y", 0.3)) * CANVAS.h - h / 2))
    return max(0, min(CANVAS.w - w, x)), max(0, min(CANVAS.h - h, y)), w, h


def _pip_mask(w: int, h: int, radius: int) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    r = max(0, min(radius, w // 2, h // 2))
    cv2.rectangle(m, (r, 0), (w - r - 1, h - 1), 255, -1)
    cv2.rectangle(m, (0, r), (w - 1, h - r - 1), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(m, (cx, cy), r, 255, -1, lineType=cv2.LINE_AA)
    return cv2.GaussianBlur(m, (3, 3), 0).astype(np.float32)[..., None] / 255.0


def paste_pip(frame: np.ndarray, pic: np.ndarray, p: dict, u: float = 1.0) -> np.ndarray:
    """A picture-in-picture over the frame: rounded corners, a soft shadow, a quick fade and grow in/out (u 0..1)."""
    x, y, w, h = pip_box(p)
    if pic.shape[:2] != (h, w):
        pic = cv2.resize(pic, (w, h), interpolation=cv2.INTER_AREA)
    a = _pip_mask(w, h, int(float(p.get("round", 0.06)) * w)) * max(0.0, min(1.0, u))
    out = frame if frame.flags.writeable else frame.copy()
    sh = max(4, w // 40)   # the shadow, below and to the right
    y0, y1, x0, x1 = y + sh, min(CANVAS.h, y + h + sh), x + sh, min(CANVAS.w, x + w + sh)
    if y1 > y0 and x1 > x0:
        region = out[y0:y1, x0:x1].astype(np.float32)
        out[y0:y1, x0:x1] = (region * (1 - 0.35 * a[:y1 - y0, :x1 - x0])).astype(np.uint8)
    roi = out[y:y + h, x:x + w].astype(np.float32)
    out[y:y + h, x:x + w] = (roi * (1 - a) + pic.astype(np.float32) * a).astype(np.uint8)
    return out


def pip_file(p: dict, work: Path, color: dict) -> tuple[Path, int]:
    """A picture-in-picture rendered at its size (cached by everything that changes its picture)."""
    x, y, w, h = pip_box(p)
    n = max(1, int(round(float(p["dur"]) * OUT_FPS)))
    key = short_hash(repr(sorted((k, str(v)) for k, v in p.items() if k not in ("x", "y", "start", "id")))
                     + f"{w}x{h}{n}" + repr(color) + RENDER_VERSION, 14)
    f = work / "segments" / f"pip_{key}.mp4"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.stem + ".part.mp4")
        e = {**p, "layout": "fill", "speed": float(p.get("speed", 1.0))}
        if p.get("kind") == "video":
            render_video_seg(e, n / OUT_FPS, color, tmp, size=(w, h))
        else:
            render_photo_seg({**e, "layout": "kenburns", "kb": p.get("kb", "in")}, n / OUT_FPS, color, 1.06, tmp,
                             size=(w, h))
        tmp.replace(f)
    return f, n


class Pips:
    """The plan's pictures-in-picture (plan `pips`), read frame by frame while the reel is composited."""

    def __init__(self, plan: dict, work: Path):
        self.items = []
        color = {**(plan.get("color") or {}), "grade": plan.get("grade")}
        for p in plan.get("pips") or []:
            try:
                f, n = pip_file(p, work, color)
            except ReelError as e:
                log(f"picture in picture left out ({str(e)[:80]})")
                continue
            s0 = int(round(float(p.get("start", 0)) * OUT_FPS))
            _, _, pw, ph = pip_box(p)
            self.items.append((p, s0, n, _SegReader(f, n, (pw, ph))))

    def __bool__(self):
        return bool(self.items)

    def draw(self, frame: np.ndarray, n: int) -> np.ndarray:
        fade = int(0.2 * OUT_FPS)
        for p, s0, cnt, rd in self.items:
            k = n - s0
            if 0 <= k < cnt:
                u = min(1.0, (k + 1) / fade, (cnt - k) / fade)
                frame = paste_pip(frame, rd.frame(k), p, u)
        return frame

    def close(self):
        for *_, rd in self.items:
            rd.close()


def segment_files(plan: dict, work: Path) -> list[tuple[dict, Path, int, int]]:
    """Per slot: (render fields, cached clip file, frames in it, frames of lead-in before the slot starts). The
    file is named by everything that changes its picture, so an unchanged shot is never rendered twice."""
    segs = plan["segments"]
    fps = OUT_FPS
    dur_f = [int(round(e["dur"] * fps)) for e in segs]
    half = [int(round(float(e.get("trans_dur") or 0) * fps)) // 2 for e in segs]
    lead_f = [0] + half[:-1]
    tail_f = half[:-1] + [0]
    zoom = float(plan.get("photo_zoom", 1.12))
    band = int((plan.get("frame") or {}).get("band") or 0)
    out = []
    for i, e in enumerate(segs):
        n = dur_f[i] + lead_f[i] + tail_f[i]
        e2 = dict(e)
        if band and band < CANVAS.h and not e.get("panel"):
            e2["_band"] = band
        if e["kind"] == "video":
            lead_speed = retime.speed_at(retime.seg_keys(e), 0.0) if e.get("ramp") else e.get("speed", 1.0)
            e2["in"] = max(0.0, e["in"] - lead_f[i] / fps * lead_speed)
        key = short_hash(repr(sorted((k, str(v)) for k, v in e2.items()
                                    if k not in ("idx", "out_start", "note", "trans_out", "trans_dur", "trans_params",
                                                 "level", "drop", "static", "score")))
                         + f"{n}" + repr(plan.get("color")) + repr(plan.get("grade")) + str(zoom) + RENDER_VERSION
                         + (f"{CANVAS.w}x{CANVAS.h}" if CANVAS.horizontal else ""), 14)
        out.append((e2, work / "segments" / f"seg_{key}.mp4", n, lead_f[i]))
    return out


def _source_frame(e: dict, local: float, color: dict, size: tuple[int, int]):
    """One frame of a shot straight from its source, framed and coloured as its segment would be (the editor's
    preview of a shot whose clip isn't rendered yet). None when it can't be had."""
    W, H = size
    if e.get("panel"):
        return None
    vf = []
    if e.get("kind") == "video" and e.get("src_w") and e.get("src"):
        if e.get("freeze"):
            local = 0.0
        elif e.get("reverse"):
            local = max(0.0, float(e.get("dur", local)) - local)
        at = float(e.get("in", 0.0)) + local * float(e.get("speed", 1.0))
        from .camlog import chain as log_chain
        from . import compose
        win = float(e.get("dur", 1.0)) * float(e.get("speed", 1.0))
        e = compose.apply(e, win, size)
        if e.get("_track_pts"):   # the follow at this moment, as one still crop
            pts = e["_track_pts"]
            e = {**e, "subject_x": float(np.interp(local, [p[0] for p in pts], [p[1] for p in pts])), "_track_pts": None}
        vf = hdr_chain({"hdr": e.get("hdr"), "transfer": e.get("transfer")}) + log_chain(e) + _video_layout(e, 1.0, size)
        inp = ["-ss", f"{max(0.0, at):.3f}", "-i", str(e["src"])]
    elif e.get("still") or e.get("src"):
        sx = float(e.get("subject_x", 0.5))
        vf = [f"scale={W}:{H}:force_original_aspect_ratio=increase",
              f"crop={W}:{H}:'(iw-{W})*{sx:.3f}':'(ih-{H})/2'"]
        inp = ["-i", str(e.get("still") or e["src"])]
    else:
        return None
    vf = vf + color_chain(seg_color(color, e)) + ["format=rgb24"]
    try:
        raw = subprocess.run(ffmpeg_base() + inp + ["-frames:v", "1", "-filter_complex", ",".join(vf),
                                                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, timeout=40).stdout
    except subprocess.TimeoutExpired:
        return None
    if len(raw) < W * H * 3:
        return None
    return np.frombuffer(raw[: W * H * 3], np.uint8).reshape(H, W, 3)


def still(plan: dict, t: float, out: Path, raw: bool = False, mask: str | None = None) -> Path:
    """One frame of the reel at t with its text, quickly, for the editor: the shot's picture from its cached clip
    (else straight from its source, coloured the same way; else its thumbnail), and every line of text on screen
    then, laid out as render does. Motion graphics, transitions and beat punches are left out. `raw`: the shot as
    filmed, without the grade or its own colour corrections (the editor's before/after)."""
    import numpy as np
    from PIL import Image
    from .framing import use_plan
    use_plan(plan)
    _prepare_transitions(plan)
    t0 = 0.0
    for e in plan["segments"]:
        e["out_start"] = round(t0, 4)
        t0 += float(e["dur"])
    t = max(0.0, min(float(t), t0 - 1.0 / OUT_FPS))
    work = Path(plan.get("work") or out.parent)
    files = segment_files(plan, work)
    i = max(k for k, e in enumerate(plan["segments"]) if e["out_start"] <= t + 1e-6)
    seg = plan["segments"][i]
    _e2, f, n, lead = files[i]
    frame = None
    band = int((plan.get("frame") or {}).get("band") or 0)
    size = (CANVAS.w, band) if 0 < band < CANVAS.h and not seg.get("panel") else CANVAS.size
    if raw:
        e = {k: v for k, v in seg.items() if k not in ("lut", "adjust")}
        frame = _source_frame({**e, "no_grade": True}, t - seg["out_start"], dict(plan.get("color") or {}), size)
    elif not f.exists():
        frame = _source_frame(seg, t - seg["out_start"], {**(plan.get("color") or {}), "grade": plan.get("grade")}, size)
    if frame is None and f.exists():
        local = min(n - 1, lead + int(round((t - seg["out_start"]) * OUT_FPS)))
        try:
            buf = subprocess.run(ffmpeg_base() + ["-ss", f"{local / OUT_FPS:.3f}", "-i", str(f), "-frames:v", "1",
                                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, timeout=30).stdout
            w, h = CANVAS.w, len(buf) // (CANVAS.w * 3) if buf else 0
            if h:
                frame = np.frombuffer(buf[: w * h * 3], np.uint8).reshape(h, w, 3)
        except (subprocess.TimeoutExpired, ValueError):
            frame = None
    if frame is None:  # not rendered yet: the shot's thumbnail, filling the frame
        frame = np.zeros((CANVAS.h, CANVAS.w, 3), np.uint8)
        if seg.get("thumb") and Path(seg["thumb"]).exists():
            with Image.open(seg["thumb"]) as im:
                im = im.convert("RGB")
                k = max(CANVAS.w / im.width, CANVAS.h / im.height)
                im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1))
                cx = int(float(seg.get("subject_x", 0.5)) * im.width - CANVAS.w / 2)
                cx = max(0, min(im.width - CANVAS.w, cx))
                cy = (im.height - CANVAS.h) // 2
                frame = np.asarray(im.crop((cx, cy, cx + CANVAS.w, cy + CANVAS.h)))
    if frame.shape[0] != CANVAS.h:  # a letterboxed slot: the picture sits in its band
        pad = np.zeros((CANVAS.h, CANVAS.w, 3), np.uint8)
        y = (CANVAS.h - frame.shape[0]) // 2
        pad[y:y + frame.shape[0]] = frame
        frame = pad
    if seg.get("layers") and not raw and not seg.get("panel"):   # the shot's colour layers, as the render has them
        from . import nodes
        frame = nodes.apply(np.ascontiguousarray(frame), seg["layers"], nodes.Masks(seg, CANVAS.size), still=True)
    if seg.get("keys") and not raw:   # zoom and position keyframes
        from .motion import apply_keys
        frame = apply_keys(np.ascontiguousarray(frame), seg["keys"], t - seg["out_start"])
    if seg.get("isolate") and not raw and not seg.get("panel"):   # colour pop / spotlight, as the render has it
        m = People().at(np.ascontiguousarray(frame))
        if m is not None:
            from .motion import isolate
            frame = isolate(np.ascontiguousarray(frame), m, str(seg["isolate"].get("kind", "pop")),
                            float(seg["isolate"].get("amount", 1.0)))
    if seg.get("effect") and not raw and not seg.get("panel"):   # the shot's video effect, as the render has it
        from . import vfx
        frame = vfx.apply(np.ascontiguousarray(frame), seg["effect"], t - seg["out_start"],
                          [float(b) - seg["out_start"] for b in plan.get("beats") or []])
    if seg.get("zoompunch") and not raw and not seg.get("panel"):   # the flash zoom's framing at t (no flash)
        from .motion import flash_zoom, flash_zoom_at, subject_point
        z, _, _ = flash_zoom_at(seg["zoompunch"], t - seg["out_start"])
        if z > 1.001:
            focus = str(seg["zoompunch"].get("focus", "face"))
            frame = np.ascontiguousarray(frame)
            pt = (subject_point(People().at(frame), focus) if seg.get("people") else None) or zoom_focus(seg, focus)
            frame = flash_zoom(frame, pt, z, 0.0, 0.0)
    if mask:   # the editor's mask view: one region lit, the rest dimmed, no words
        from . import nodes
        Image.fromarray(nodes.mask_view(np.ascontiguousarray(frame), mask, seg)).save(out, quality=88)
        return out
    if plan.get("grid") and not raw:  # the reel's grid, as the render draws it
        from .motion import grid_overlay
        frame = grid_overlay(np.ascontiguousarray(frame), int(plan["grid"].get("cols", 8)),
                             float(plan["grid"].get("alpha", 0.3)))
    color = {**(plan.get("color") or {}), "grade": plan.get("grade")}
    for p in plan.get("pips") or []:   # pictures in picture on screen now
        local = t - float(p.get("start", 0))
        if 0 <= local < float(p.get("dur", 0)) and not raw:
            _, _, pw, ph = pip_box(p)
            pic = _source_frame({**p, "layout": "fill"}, local, color, (pw, ph))
            if pic is not None:
                frame = paste_pip(np.ascontiguousarray(frame).copy(), pic, p)
    texts = TextTrack(plan, [float(b) for b in plan.get("beats") or []], fx=False)
    frame = texts.draw(np.ascontiguousarray(frame).copy(), t, seg)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(out, quality=88)
    return out


def _render(plan: dict, out_path: Path, work: Path, workers: int = 2, native_text: bool = False,
            info: dict | None = None) -> Path:
    from . import encode
    from .motion import affine, apply_transition, bulge, pulse_amount, shot_motion
    segs = plan["segments"]
    if not segs:
        raise ReelError("plan has no segments")
    _prepare_transitions(plan)
    band = int((plan.get("frame") or {}).get("band") or 0)
    bar = (CANVAS.h - band) // 2 if 0 < band < CANVAS.h else 0
    fps = OUT_FPS
    start_f = [int(round(e["out_start"] * fps)) for e in segs]
    dur_f = [int(round(e["dur"] * fps)) for e in segs]
    total_f = start_f[-1] + dur_f[-1]
    half = [int(round(e["trans_dur"] * fps)) // 2 for e in segs]  # half-window of the cut after seg i
    lead_f = [0] + half[:-1]
    tail_f = half[:-1] + [0]

    seg_dir = work / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    zoom = float(plan.get("photo_zoom", 1.12))
    files, jobs = [], []
    for e2, f, n, lead in segment_files(plan, work):
        files.append((f, n))
        if not f.exists():
            jobs.append((e2, n / fps, f, lead / fps))
    if jobs:
        log(f"rendering {len(jobs)} shots...")
        from concurrent.futures import ThreadPoolExecutor

        color = {**plan["color"], "grade": plan.get("grade")}

        def do(job):
            e2, length, f, lead = job
            tmp = f.with_name(f.stem + ".part.mp4")
            if e2.get("panel"):
                render_panel_seg(e2, length, lead, color, zoom, tmp, seg_dir)
            elif e2["kind"] == "video" and retime.needs_retime(e2, e2.get("fps")):
                render_retimed_seg(e2, length, color, tmp, lead)
            elif e2["kind"] == "video":
                render_video_seg(e2, length, color, tmp)
            elif e2.get("layout") == "popout" and render_popout_seg(e2, length, color, tmp):
                pass
            else:
                render_photo_seg(e2, length, color, zoom, tmp)
            tmp.replace(f)
            return f
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for n_done, _ in enumerate(ex.map(do, jobs), 1):
                if n_done % 4 == 0 or n_done == len(jobs):
                    log(f"  {n_done}/{len(jobs)}")

    # ---- final encode: frames from the compositor + text overlays + music
    total = total_f / fps
    # a sideways reel (frame `rotate`: "turn your phone"): made widescreen, written on its side in an upright file
    turn = int((plan.get("frame") or {}).get("rotate") or 0) % 360
    fw, fh = (CANVAS.h, CANVAS.w) if turn in (90, 270) else (CANVAS.w, CANVAS.h)
    inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{fw}x{fh}", "-r", str(fps), "-i", "-"]
    vfade = min(float(plan.get("fade_out_video") or 0), total_f / fps * 0.5)
    fc, n_in = [f"[0:v]{f'fade=t=out:st={total_f / fps - vfade:.3f}:d={vfade:.3f},' if vfade > 0.05 else ''}"
                "format=yuv420p[vout]"], 1
    music = plan.get("music") or {}
    if music.get("path") and Path(music["path"]).exists():
        inputs += ["-ss", f"{music['start']:.3f}", "-t", f"{total + 0.1:.3f}", "-i", music["path"]]
        fo = float(music.get("fade_out", 0.8))
        gain = float(music.get("gain_db") or 0.0)  # the editor's music level
        fc.append(f"[{n_in}:a]aresample=48000,{f'volume={gain:.1f}dB,' if gain else ''}afade=t=in:d=0.05,"
                  f"afade=t=out:st={max(0, total - fo):.3f}:d={fo:.3f},"
                  f"atrim=duration={total:.4f}[aout]")
    else:
        inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fc.append(f"[{n_in}:a]anull[aout]")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    errlog = work / "final_encode.log"
    cmd = ffmpeg_base() + inputs + ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
                                    *encode.args("final"),
                                    "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                                    "-movflags", "+faststart", "-t", f"{total:.4f}", str(out_path)]
    maps = None
    if any(o.get("type") == "map" for o in plan.get("overlays") or []):
        from .routemap import MapLayer
        maps = MapLayer(plan)  # rendered (or taken from cache) before encoding starts
    log("compositing transitions + motion and encoding...")
    with open(errlog, "w") as ef:
        enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=ef)
        readers = [_SegReader(f, n) for f, n in files]
        pips = Pips(plan, work)
        beats = [float(b) for b in plan.get("beats") or []]
        mcfg = plan.get("motion") or {}
        texts = TextTrack(plan, beats, native=native_text)
        if info is not None:
            info["texts"] = texts

        from . import nodes
        masks = {i: nodes.Masks(e, CANVAS.size) for i, e in enumerate(segs) if e.get("layers") and not e.get("panel")}
        graded: dict[tuple[int, int], np.ndarray] = {}

        def shot_frame(i: int, n: int) -> np.ndarray:
            local = n - (start_f[i] - lead_f[i])
            fr = readers[i].frame(local)
            if i in masks:   # the shot's colour layers (secondary grading), once per source frame
                key = (i, local)
                if key not in graded:
                    if len(graded) > 4:
                        graded.clear()
                    graded[key] = nodes.apply(fr, segs[i]["layers"], masks[i])
                fr = graded[key]
            if segs[i].get("backdrop"):  # the person stays, the world behind them changes on the beat
                fr = backdrop.frame(i, segs[i], fr, n / fps)
            if segs[i].get("isolate"):  # colour pop or spotlight: the person stays, the world round them changes
                iso = segs[i]["isolate"]
                m = people.follow(i, fr, n)
                if m is not None:
                    from .motion import ease_out, isolate
                    k = ease_out(max(0.0, min(1.0, (n / fps - segs[i]["out_start"]) / 0.3)))
                    fr = isolate(fr, m, str(iso.get("kind", "pop")), k * float(iso.get("amount", 1.0)))
            if segs[i].get("clones"):  # a clone trail: the person left behind where they stood on earlier beats
                cl = segs[i]["clones"]
                got = clones.setdefault(i, [])
                t_in = n / fps - segs[i]["out_start"]
                for k, tc in enumerate(cl.get("times") or []):
                    if k >= len(got) and t_in >= float(tc):   # (frames come in order: the first one at or after it)
                        got.append((n, np.array(fr), people.at(fr)))
                a_ = float(cl.get("alpha", 0.9))
                for n_k, snap, m in got:
                    if m is not None and n_k < n:   # earlier poses only, oldest first
                        fr = cv2.blendLinear(snap, fr, m * a_, 1.0 - m * a_)
            ci = float(segs[i].get("colour_in") or 0)
            if ci > 0:  # arrives in black and white (through the transition too), then its colour blooms
                from .motion import colour_in, ease_in_out
                fr = colour_in(fr, ease_in_out(max(0.0, min(1.0, (n / fps - segs[i]["out_start"] - 0.15) / ci))))
            if segs[i].get("effect"):  # the shot's video effect (vfx.py, chosen by the effects director)
                from . import vfx
                t_in = n / fps - segs[i]["out_start"]
                fr = vfx.apply(fr, segs[i]["effect"], t_in, [b - segs[i]["out_start"] for b in beats])
            if segs[i].get("keys"):  # the editor's zoom and position keyframes
                from .motion import apply_keys
                fr = apply_keys(fr, segs[i]["keys"], n / fps - segs[i]["out_start"])
            if segs[i].get("zoompunch"):  # flash zoom: on the beats the picture snaps closer to the person
                fr = _flash_zoom(fr, segs[i], n / fps - segs[i]["out_start"], people, i, n, zfocus)
            sc, ang, tx, ty = shot_motion(n / fps, segs[i], beats, mcfg)
            fr = affine(fr, sc, ang, tx, ty)
            k = pulse_amount(n / fps, segs[i], beats, mcfg)
            return bulge(fr, k) if k > 0.005 else fr

        from .effects import freeze_frame, rgb_split
        fz = plan.get("freeze") or {}
        fz0 = int(round(float(fz.get("t", -1)) * fps)) if fz else -1
        fzn = int(round(float(fz.get("dur", 0)) * fps)) if fz else 0
        frozen = None
        sil: dict = {}  # each shot's people mask for its silhouette flash, found once
        backdrop = Backdrops()
        people = People()
        clones: dict = {}   # each clone trail's captured poses
        zfocus: dict = {}   # each flash zoom's point on the person, followed and smoothed
        poses: dict = {}    # each freeze-frame intro's styled still
        rolls: dict = {}    # each camera roll's little pictures
        walls: dict = {}  # each photo wall's little pictures, loaded once
        grid = plan.get("grid")
        try:
            i = 0
            for n in range(total_f):
                while i < len(segs) - 1 and n >= start_f[i + 1] + 0:
                    i += 1
                # are we inside the transition window around a cut?
                frame = None
                for j in (i, i + 1):  # j = incoming segment of the cut at start_f[j]
                    if 1 <= j < len(segs) and half[j - 1] and start_f[j] - half[j - 1] <= n < start_f[j] + half[j - 1]:
                        h = half[j - 1]
                        p = (n - (start_f[j] - h) + 0.5) / (2 * h)
                        a = shot_frame(j - 1, n)
                        b = shot_frame(j, n)
                        frame = apply_transition(segs[j - 1]["trans_out"], a, b, p, segs[j - 1].get("trans_params"))
                        break
                if frame is None:
                    frame = shot_frame(i, n)
                if segs[i].get("silhouette") and not segs[i].get("panel"):
                    # the people flash paper-white for two frames, as the shot snaps whole (after its way in)
                    snap = start_f[i] + (half[i - 1] if i else 0)
                    at = snap - 2 if i and half[i - 1] else start_f[i] + 9
                    if at <= n < at + 2:
                        if i not in sil:
                            sil[i] = nodes.people_mask(shot_frame(i, at))
                        if sil[i] is not None:
                            from .motion import silhouette
                            frame = silhouette(frame, sil[i])
                pz = segs[i].get("pose")
                if pz and not segs[i].get("panel"):  # freeze-frame intro: the moment stops, the person outlined
                    t0 = float(segs[i]["out_start"]) + float(pz.get("at", 0))
                    q = (n / fps - t0) / max(0.1, float(pz.get("dur", 0.6)))
                    if 0 <= q < 1:
                        if i not in poses:
                            m = people.at(frame)
                            from .motion import sticker
                            poses[i] = sticker(frame, m, bool(pz.get("outline", True))) if m is not None else None
                        if poses[i] is not None:
                            from .motion import ease_out
                            frame = affine(poses[i], 1.0 + 0.05 * ease_out(min(1.0, q * 3)))
                rl = segs[i].get("roll")
                if rl and not segs[i].get("panel"):  # the camera roll scrolls, then opens into this shot
                    u = (n / fps - float(segs[i]["out_start"])) / max(0.2, float(rl.get("dur", 1.2)))
                    if 0 <= u < 1:
                        if i not in rolls:
                            rolls[i] = _thumb_squares(rl.get("cells"))
                        from .motion import camera_roll
                        frame = camera_roll(frame, rolls[i], int(rl.get("target", 4)), u, int(rl.get("cols", 3)),
                                            bool(rl.get("light")))
                if fzn and fz0 <= n < fz0 + fzn:  # hero freeze on the biggest beat
                    if frozen is None:
                        frozen = frame.copy()
                    frame = freeze_frame(frozen, n - fz0, fzn)
                if segs[i].get("rgb") and i > 0 and 0 <= n - start_f[i] < 4:
                    frame = rgb_split(frame, n - start_f[i])
                bt = int(segs[i].get("black_tail") or 0)
                if bt and i < len(segs) - 1 and start_f[i + 1] - bt <= n < start_f[i + 1]:
                    frame = np.zeros_like(frame)  # the pre-hit black: the payoff lands out of nothing
                if plan.get("loop"):  # dissolve the last moments into the first frame: seamless replay
                    if n == 0:
                        first_frame = frame.copy()
                    loop_f = int(0.4 * fps)
                    if n >= total_f - loop_f:
                        q = (n - (total_f - loop_f) + 1) / loop_f
                        frame = cv2.addWeighted(frame, 1 - q * q, first_frame, q * q, 0)
                if segs[i].get("mosaic"):  # the photo wall round the subject
                    mo = segs[i]["mosaic"]
                    if i not in walls:
                        walls[i] = _wall_tiles(mo, frame.shape[1], frame.shape[0], shot_frame(i, n))
                    u = (n / fps - float(segs[i]["out_start"])) / max(0.1, float(segs[i]["dur"]))
                    from .motion import mosaic as _mosaic
                    frame = _mosaic(frame, walls[i], int(mo.get("cols", 8)), u, int(mo.get("seed", 0)))
                if grid:  # the fine grid over everything
                    from .motion import grid_overlay
                    frame = grid_overlay(frame, int(grid.get("cols", 8)), float(grid.get("alpha", 0.3)))
                if bar:  # motion and transitions move the whole frame: keep the letterbox bars clean
                    if not frame.flags.writeable:
                        frame = frame.copy()
                    frame[:bar] = 0
                    frame[CANVAS.h - bar:] = 0
                if pips:
                    frame = pips.draw(frame, n)
                if maps is not None:
                    frame = maps.draw(frame, n / fps)
                frame = texts.draw(frame, n / fps, segs[i])
                if turn:
                    frame = np.rot90(frame, {90: -1, 180: 2, 270: 1}[turn])  # (90 = the top of the picture to the right)
                enc.stdin.write(np.ascontiguousarray(frame).tobytes())
                for r_i in range(0, max(0, i - 1)):  # free decoders we're done with
                    readers[r_i].close()
            enc.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            for r in readers:
                r.close()
            pips.close()
        enc.wait()
    if enc.returncode != 0:
        raise ReelError(f"final encode failed: {errlog.read_text()[-1200:]}")
    try:
        from .qa import save_text_report
        save_text_report(texts, out_path)
    except Exception as e:
        log(f"text report skipped ({e})")
    snd = plan.get("sound") or {}
    if snd and (str(snd.get("sfx", "off")) != "off" or str(snd.get("ambience", "off")) != "off"):
        from . import sound
        try:
            sound.mix_into(out_path, plan, sound.text_events_from(texts), work)
        except Exception as e:  # sound design must never cost the user the reel
            log(f"sound design skipped ({e})")
    return out_path


def cover_time(plan: dict) -> float:
    """The moment of the opening shot that makes the cover: with the title up if the reel has one, never in the
    middle of a sentence (one word of a lyric, a subtitle or half a tease says nothing as a still)."""
    d = float(plan["segments"][0]["dur"])

    def spans(pick):
        return [(float(o.get("start", 0)), float(o.get("start", 0)) + float(o.get("duration", 0)))
                for o in plan.get("overlays") or [] if pick(o)]
    passing = spans(lambda o: o.get("type") == "caption" or o.get("recipe") in ("lyric", "tease"))
    titles = spans(lambda o: o.get("type") == "hook" and o.get("recipe") not in ("lyric", "tease"))
    free = [t for t in (d * k / 24 for k in range(2, 23)) if not any(a - 0.1 <= t <= b + 0.2 for a, b in passing)]
    if not free:
        return d / 2
    titled = [t for t in free if any(a + 0.6 <= t <= b - 0.3 for a, b in titles)]  # in and settled, not on its way out
    return min(titled or free, key=lambda t: abs(t - d / 2))


def export_cover(plan: dict, video: Path, out: Path) -> Path | None:
    """Cover image: a still of the first segment (the hook), see cover_time."""
    t = cover_time(plan)
    proc = subprocess.run(ffmpeg_base() + ["-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
                          capture_output=True, text=True)
    return out if proc.returncode == 0 else None
