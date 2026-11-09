"""Render a plan.json into a 1080x1920 MP4 with ffmpeg."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import retime
from .config import OUT_FPS, OUT_H, OUT_W
from .fx import color_chain, hdr_chain, seg_color
from .util import ReelError, ffmpeg_base, hwaccel_args, log, short_hash

RENDER_VERSION = "r6"  # bump when shot rendering changes so cached shots are rebuilt

# intermediates: near-lossless and quick; the final pass does the real compression
def _enc() -> list[str]:
    """Encoder args for the intermediate segment files (hardware when available, see encode.py)."""
    from . import encode
    return encode.args("segment") + ["-r", str(OUT_FPS)]


def _frames(sec: float) -> int:
    return max(1, int(round(sec * OUT_FPS)))


def _video_layout(e: dict, length: float, size: tuple[int, int] = (OUT_W, OUT_H)) -> list[str]:
    OW, OH = size
    w, h = e["src_w"], e["src_h"]
    lay = e["layout"]
    if lay == "blur_fill":
        return [f"split[a][b];[a]scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},"
                f"boxblur=40:2,eq=brightness=-0.08[bg];[b]scale={OW}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"]
    # scale to cover the 9:16 frame
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
        ease = f"(0.5-0.5*cos(PI*min(t/{length:.3f}\\,1)))"
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
    return [scale, f"crop={OW}:{OH}"]


def render_video_seg(e: dict, length: float, color: dict, out: Path,
                     size: tuple[int, int] = (OUT_W, OUT_H), rate: float = OUT_FPS) -> None:
    """One video shot at its (constant) speed. Speed-ups average the frames they skip (motion blur);
    `rate` other than 30 renders at that frame rate (the retimer's real-time pass)."""
    speed = float(e.get("speed", 1.0))
    src_need = length * speed + 0.5
    pad = []
    if e.get("_band") and size == (OUT_W, OUT_H):  # cinematic letterbox: the picture in a band, black bars
        size = (OUT_W, int(e["_band"]))
        pad = [f"pad={OUT_W}:{OUT_H}:0:{(OUT_H - size[1]) // 2}:black"]
    if e.get("track") and e.get("layout") == "crop":
        from .framing import track_x
        try:
            e = {**e, "_track_pts": track_x(e["src"], e["in"], length * speed, {**e, "speed": speed},
                                            float(e.get("subject_x", 0.5)))}
        except Exception:
            pass
    pre = []
    pre += hdr_chain({"hdr": e.get("hdr"), "transfer": e.get("transfer")})
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


def _ease(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


def render_photo_seg(e: dict, length: float, color: dict, zoom: float, out: Path,
                     size: tuple[int, int] = (OUT_W, OUT_H)) -> None:
    """Smooth sub-pixel Ken Burns rendered in Python, piped to ffmpeg."""
    pad = []
    if e.get("_band") and size == (OUT_W, OUT_H):  # cinematic letterbox
        size = (OUT_W, int(e["_band"]))
        pad = [f"pad={OUT_W}:{OUT_H}:0:{(OUT_H - size[1]) // 2}:black"]
    OW, OH = size
    im = Image.open(e["still"]).convert("RGB")
    W, H = im.size
    # pre-scale (high quality) so the 9:16 cover area is ~1.1x output: per-frame warps then
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
        p = _ease(lin) if mode in ("in", "out", "in_rot") else 0.35 * lin + 0.65 * _ease(lin)
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
    if e.get("parallax") and (size == (OUT_W, OUT_H) or pad):
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
    cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(OUT_FPS),
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
    cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(OUT_FPS),
                           "-i", "-"] + _enc() + [str(out)]
    wr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    size = OUT_W * OUT_H * 3
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
            last = np.frombuffer(b, np.uint8).reshape(OUT_H, OUT_W, 3)
            buf[read] = last
        for old in [j for j in buf if j < i - 10]:
            del buf[old]
        for old in [j for j in flows if j < i - 1]:
            del flows[old]
        return buf.get(i, last if last is not None else np.zeros((OUT_H, OUT_W, 3), np.uint8))

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

    def __init__(self, path: Path, n_frames: int):
        self.path, self.n = path, n_frames
        self.proc = None
        self.pos = -1
        self.last = None
        self.size = OUT_W * OUT_H * 3

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
            self.last = np.frombuffer(buf, np.uint8).reshape(OUT_H, OUT_W, 3)
            self.pos += 1
        if self.last is None:
            self.last = np.zeros((OUT_H, OUT_W, 3), np.uint8)
        return self.last

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait()
            self.proc = None


class TextTrack:
    """All on-screen text of a plan. Each element is laid out lazily on the first frame it
    appears, so its position can avoid the subject and busy parts of that actual frame."""

    def __init__(self, plan: dict, beats: list[float], native: bool = False):
        from .typo import PRESETS
        self.native = native  # build everything, draw only what an editor can't rebuild (see render)
        tcfg = plan.get("text") or {}
        preset = PRESETS.get(str(tcfg.get("preset", "bold")), PRESETS["bold"])
        self.cfg = {}
        from .typo import CAPTION, legible
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
            self.cfg[kind] = legible(kind, base) if readable else base
        if plan.get("story"):  # a story reel's hook must read inside the first second
            self.cfg["hook"]["fast_in"] = True
        self.cfg["caption"] = legible("caption", {**CAPTION, **{k: v for k, v in (tcfg.get("caption") or {}).items()
                                                               if v is not None}})
        band = int((plan.get("frame") or {}).get("band") or 0)
        self.letterbox = 0 < band < OUT_H
        if 0 < band < OUT_H:  # letterbox: words live in the black bars, never over the picture
            from . import typo
            bar = (OUT_H - band) // 2
            typo.BANDS["bar_top"] = (max(typo.SAFE["top"], bar - 400), bar - 30)
            typo.BANDS["bar_bottom"] = (OUT_H - bar + 40, min(typo.SAFE["bottom"] + 40, OUT_H - bar + 420))
            self.cfg["hook"]["position"] = "bar_top"
            for k in ("label", "cta", "caption", "location"):
                self.cfg[k]["position"] = "bar_bottom"
            self.cfg["location"]["behind"] = "off"
        self.specs = sorted([o for o in plan.get("overlays") or []
                             if o["type"] in ("hook", "location", "cta", "label", "caption")], key=lambda o: o["start"])
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
        from .typo import build_hook, build_location, build_location_behind, format_coords, split_place
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
                    cfg = self.cfg[o["type"] if o["type"] in ("cta", "label", "caption") else "hook"]
                    el = self._clear_of_others(k, lambda pos: build_hook(
                        o["text"], st, du, {**cfg, **({"position": pos} if pos else {})}, frame, self.beats, subj),
                        cfg.get("position"))
                self.built[k] = el
                from .scripts import script_of
                if not self.native and not self.baked(k) and not script_of(o.get("text") or ""):
                    from .hfx import animate, motion_for
                    fx = animate(el, motion_for(o["type"], self.tcfg, o), o["type"])
                    if fx is not None:
                        self.fx[k] = fx
            if self.native and not self.baked(k):
                continue
            frame = (self.fx.get(k) or el).draw(frame, t)
        return frame

    def _clear_of_others(self, k: int, build, preferred: str | None):
        """Build text element k where it doesn't cover another line on screen at the same time (the hook and a
        subtitle, two labels): first where its style wants it, then in the other bands."""
        o = self.specs[k]
        a0, a1 = float(o["start"]), float(o["start"]) + float(o["duration"])
        others = [self.built[j] for j, oj in enumerate(self.specs) if j != k and j in self.built
                  and self.built[j] is not None and float(oj["start"]) < a1 and float(oj["start"]) + float(oj["duration"]) > a0
                  and not self.baked(j)]

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
        d = min(d, 0.9 * min(e["dur"], segs[i + 1]["dur"]))
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
    import time
    t0 = time.time()
    log(f"encoder: {encode.describe()}")
    try:
        out = _render(plan, out_path, work, workers, native_text, info)
    except ReelError as e:
        if not encode.using_hardware():
            raise
        encode.disable(str(e))
        out = _render(plan, out_path, work, workers, native_text, info)
    log(f"render took {time.time() - t0:.0f}s")
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
    bar = (OUT_H - band) // 2 if 0 < band < OUT_H else 0
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
    for i, e in enumerate(segs):
        n = dur_f[i] + lead_f[i] + tail_f[i]
        length = n / fps
        e2 = dict(e)
        band = int((plan.get("frame") or {}).get("band") or 0)
        if band and band < OUT_H and not e.get("panel"):
            e2["_band"] = band
        if e["kind"] == "video":
            lead_speed = retime.speed_at(retime.seg_keys(e), 0.0) if e.get("ramp") else e.get("speed", 1.0)
            e2["in"] = max(0.0, e["in"] - lead_f[i] / fps * lead_speed)
        key = short_hash(repr(sorted((k, str(v)) for k, v in e2.items()
                                    if k not in ("idx", "out_start", "note", "trans_out", "trans_dur", "trans_params",
                                                 "level", "drop", "static", "score")))
                         + f"{n}" + repr(plan.get("color")) + repr(plan.get("grade")) + str(zoom) + RENDER_VERSION, 14)
        f = seg_dir / f"seg_{key}.mp4"
        files.append((f, n))
        if not f.exists():
            jobs.append((e2, length, f, lead_f[i] / fps))
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
    inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(fps), "-i", "-"]
    vfade = min(float(plan.get("fade_out_video") or 0), total_f / fps * 0.5)
    fc, n_in = [f"[0:v]{f'fade=t=out:st={total_f / fps - vfade:.3f}:d={vfade:.3f},' if vfade > 0.05 else ''}"
                "format=yuv420p[vout]"], 1
    music = plan.get("music") or {}
    if music.get("path") and Path(music["path"]).exists():
        inputs += ["-ss", f"{music['start']:.3f}", "-t", f"{total + 0.1:.3f}", "-i", music["path"]]
        fo = float(music.get("fade_out", 0.8))
        fc.append(f"[{n_in}:a]aresample=48000,afade=t=in:d=0.05,afade=t=out:st={max(0, total - fo):.3f}:d={fo:.3f},"
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
        beats = [float(b) for b in plan.get("beats") or []]
        mcfg = plan.get("motion") or {}
        texts = TextTrack(plan, beats, native=native_text)
        if info is not None:
            info["texts"] = texts

        def shot_frame(i: int, n: int) -> np.ndarray:
            local = n - (start_f[i] - lead_f[i])
            fr = readers[i].frame(local)
            sc, ang, tx, ty = shot_motion(n / fps, segs[i], beats, mcfg)
            fr = affine(fr, sc, ang, tx, ty)
            k = pulse_amount(n / fps, segs[i], beats, mcfg)
            return bulge(fr, k) if k > 0.005 else fr

        from .effects import freeze_frame, rgb_split
        fz = plan.get("freeze") or {}
        fz0 = int(round(float(fz.get("t", -1)) * fps)) if fz else -1
        fzn = int(round(float(fz.get("dur", 0)) * fps)) if fz else 0
        frozen = None
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
                if fzn and fz0 <= n < fz0 + fzn:  # hero freeze on the biggest beat
                    if frozen is None:
                        frozen = frame.copy()
                    frame = freeze_frame(frozen, n - fz0, fzn)
                if segs[i].get("rgb") and i > 0 and 0 <= n - start_f[i] < 4:
                    frame = rgb_split(frame, n - start_f[i])
                if plan.get("loop"):  # dissolve the last moments into the first frame: seamless replay
                    if n == 0:
                        first_frame = frame.copy()
                    loop_f = int(0.4 * fps)
                    if n >= total_f - loop_f:
                        q = (n - (total_f - loop_f) + 1) / loop_f
                        frame = cv2.addWeighted(frame, 1 - q * q, first_frame, q * q, 0)
                if bar:  # motion and transitions move the whole frame: keep the letterbox bars clean
                    if not frame.flags.writeable:
                        frame = frame.copy()
                    frame[:bar] = 0
                    frame[OUT_H - bar:] = 0
                if maps is not None:
                    frame = maps.draw(frame, n / fps)
                frame = texts.draw(frame, n / fps, segs[i])
                enc.stdin.write(np.ascontiguousarray(frame).tobytes())
                for r_i in range(0, max(0, i - 1)):  # free decoders we're done with
                    readers[r_i].close()
            enc.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            for r in readers:
                r.close()
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


def export_cover(plan: dict, video: Path, out: Path) -> Path | None:
    """Cover image: middle of the first segment (the hook)."""
    t = plan["segments"][0]["dur"] / 2
    proc = subprocess.run(ffmpeg_base() + ["-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
                          capture_output=True, text=True)
    return out if proc.returncode == 0 else None
