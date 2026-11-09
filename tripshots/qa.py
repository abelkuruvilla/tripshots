"""Quality checks on a rendered reel, run after every render (and by `tripshots qa NAME.mp4`).

What a careful editor checks before posting, measured on the file itself:
  format      1080x1920, about 30 fps, H.264 video with AAC sound
  length      3-90 s (Reels longer than 90 s are shown less)
  loudness    integrated loudness about -14 LUFS (-16..-12) and true peak at or under -1 dBTP
  black       no stretch of black picture over 0.4 s (fades on purpose excluded)
  frozen      no frozen picture over 1.2 s, except a freeze frame the plan asks for
  silence     no silent stretch over 1 s while music should be playing
  text_safe   every title inside the part of the screen Instagram's buttons and caption don't cover
  text_size   the main words big enough to read on a phone at arm's length
  text_time   each line on screen long enough to read (about 3.5 words a second, plus half a second)
Writes NAME.qa.json and NAME.qa.jpg (a contact sheet: 12 frames with their times). The idea and the
set of checks follow the one-take skill's QA pass (KaranO-Dev/one-take-skill, MIT).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import OUT_FPS, OUT_H, OUT_W
from .util import ffprobe, log, parse_rate, read_json, write_json

MAX_LEN = 90.0
WORDS_PER_S = 3.5


def _detect(path: Path, vf: str | None, af: str | None, pattern: str) -> list[tuple[float, float]]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path)]
    cmd += (["-vf", vf, "-an"] if vf else ["-af", af, "-vn"]) + ["-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = []
    if pattern == "black":
        for m in re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)", p.stderr):
            out.append((float(m.group(1)), float(m.group(2))))
    else:
        starts = [float(x) for x in re.findall(rf"{pattern}_start: ?([\d.]+)", p.stderr)]
        ends = [float(x) for x in re.findall(rf"{pattern}_end: ?([\d.]+)", p.stderr)]
        for i, s in enumerate(starts):
            out.append((s, ends[i] if i < len(ends) else None))
    return out


def _overlaps(a: tuple, windows: list[tuple]) -> bool:
    return any(a[0] < w[1] + 0.05 and (a[1] if a[1] is not None else 1e9) > w[0] - 0.05 for w in windows)


def check(video: Path, plan: dict | None = None, texts: list[dict] | None = None) -> dict:
    video = Path(video)
    plan = plan or read_json(video.with_name(video.stem + ".plan.json"), {}) or {}
    if texts is None:
        texts = read_json(video.with_name(video.stem + ".text.json"), None)
    res: list[dict] = []

    def add(key, ok, value, want, why):
        res.append({"check": key, "ok": bool(ok), "value": value, "want": want, "why": why})

    info = ffprobe(video)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    aus = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = parse_rate(vs.get("avg_frame_rate") or vs.get("r_frame_rate"))
    dur = float(info.get("format", {}).get("duration") or 0)
    fmt_ok = vs.get("width") == OUT_W and vs.get("height") == OUT_H and abs(fps - OUT_FPS) < 0.6 \
        and vs.get("codec_name") == "h264" and (aus is None or aus.get("codec_name") == "aac")
    add("format", fmt_ok, f"{vs.get('width')}x{vs.get('height')} {fps:.2f} fps {vs.get('codec_name')}"
        f"{'/' + aus.get('codec_name') if aus else ' (no sound)'}", f"{OUT_W}x{OUT_H} {OUT_FPS} fps h264/aac",
        "the size and codecs Instagram expects")
    add("length", 3.0 <= dur <= MAX_LEN, round(dur, 2), f"3-{MAX_LEN:.0f} s", "reels over 90 s are shown less")
    if aus is not None:
        from .sound import loudness
        m = loudness(video)
        if m:
            ok = -16.0 <= m["I"] <= -12.0 and m["TP"] <= -1.0
            add("loudness", ok, f"{m['I']:.1f} LUFS, {m['TP']:.1f} dBTP", "-14 LUFS (±2), ≤ -1 dBTP",
                "Instagram turns loud reels down and quiet ones sound weak; peaks over -1 dBTP distort on phones")
    # intended dark or still moments: dips, fades out, the freeze frame, the end of a loop
    segs = plan.get("segments") or []
    dark = []
    for s in segs:
        if s.get("trans_out") in ("dip",) or s.get("kind") == "fade_out_video" or s.get("fade_out"):
            end = float(s.get("out_start", 0)) + float(s.get("dur", 0))
            dark.append((end - 0.8, end + 0.8))
    blacks = [b for b in _detect(video, "blackdetect=d=0.4:pic_th=0.98:pix_th=0.08", None, "black")
              if not _overlaps(b, dark)]
    add("black", not blacks, [[round(a, 2), round(b, 2)] for a, b in blacks][:6], "none over 0.4 s",
        "a black stretch reads as a broken video")
    fz = plan.get("freeze") or {}
    still = [(float(fz["t"]), float(fz["t"]) + float(fz.get("dur", 0)))] if fz.get("t") is not None else []
    frozen = [f for f in _detect(video, "freezedetect=n=0.002:d=1.2", None, "freeze")
              if not _overlaps(f, still)]
    add("frozen", not frozen, [[round(a, 2), round(b, 2) if b else None] for a, b in frozen][:6],
        "nothing still over 1.2 s", "a frozen picture looks like the video stalled")
    if aus is not None and (plan.get("music") or {}).get("path"):
        sil = [s for s in _detect(video, None, "silencedetect=n=-45dB:d=1.0", "silence")
               if (s[1] or dur) - s[0] >= 1.0 and s[0] < dur - 1.0]
        add("silence", not sil, [[round(a, 2), round(b, 2) if b else None] for a, b in sil][:6],
            "no gap over 1 s", "a silent gap under music sounds like a mistake")
    if texts:
        from .typo import MIN_SIZE, SAFE
        # a giant title behind the skyline is scenery, partly hidden on purpose: only its middle must stay clear
        def low(t):
            return (t["box"][1] + t["box"][3]) / 2 if t.get("behind") else t["box"][3]
        out_of = [t for t in texts if t["box"][1] < SAFE["top"] - 20 and not t.get("bar")
                  or low(t) > SAFE["bottom"] + 40 and not t.get("bar")
                  or t["box"][0] < SAFE["left"] - 40 or t["box"][2] > SAFE["right"] + 40]
        add("text_safe", not out_of, [f"{t['kind']}: {t['text'][:30]}" for t in out_of][:6],
            "inside the safe area", "Instagram's buttons, name and caption cover the edges of the screen")
        small = [t for t in texts if t.get("size") and t["kind"] in MIN_SIZE
                 and t["size"] < 0.9 * MIN_SIZE[t["kind"]]]
        add("text_size", not small, [f"{t['kind']} {t['size']}px: {t['text'][:30]}" for t in small][:6],
            "hook ≥ 88 px, labels ≥ 64, captions ≥ 54 (at 1080 wide)", "small words don't read on a phone")
        short = [t for t in texts if t["duration"] < len(t["text"].split()) / WORDS_PER_S + 0.5]
        add("text_time", not short, [f"{t['kind']} {t['duration']:.1f}s: {t['text'][:30]}" for t in short][:6],
            f"{WORDS_PER_S:g} words a second + 0.5 s", "people need time to read a line before it goes")
    passed = sum(1 for r in res if r["ok"])
    rep = {"video": str(video), "duration": round(dur, 2), "passed": passed, "total": len(res), "checks": res}
    try:
        rep["sheet"] = str(contact_sheet(video, video.with_name(video.stem + ".qa.jpg"), dur))
    except Exception as e:
        log(f"qa: contact sheet skipped ({e})")
    write_json(video.with_name(video.stem + ".qa.json"), rep)
    log(f"qa: {passed}/{len(res)} checks passed" + "".join(
        f"\n  ✗ {r['check']}: {r['value']} (want {r['want']}): {r['why']}" for r in res if not r["ok"]))
    return rep


def contact_sheet(video: Path, out: Path, dur: float, n: int = 12) -> Path:
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    cells = []
    for i in range(n):
        t = (i + 0.5) * dur / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            fr = np.zeros((OUT_H, OUT_W, 3), np.uint8)
        c = cv2.resize(fr, (270, 480))
        cv2.rectangle(c, (0, 0), (74, 26), (0, 0, 0), -1)
        cv2.putText(c, f"{t:4.1f}s", (5, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(c)
    cap.release()
    rows = [np.hstack(cells[r * 6:(r + 1) * 6]) for r in range(n // 6)]
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


def text_report(track) -> list[dict]:
    """The text a TextTrack actually laid out (render.py writes it to NAME.text.json)."""
    out = []
    for k, el in sorted(getattr(track, "built", {}).items()):
        if el is None:
            continue
        o = track.specs[k]
        main = [l for l in (el.lines or []) if l.get("role", "main") == "main"] or el.lines or []
        size = min((int(l["size"]) for l in main), default=None)
        box = [round(float(v), 1) for v in el.box]
        out.append({"kind": o["type"], "text": o.get("text") or " ".join(l["text"] for l in main),
                    "start": round(float(o["start"]), 3), "duration": round(float(o["duration"]), 3),
                    "box": box, "size": size, "motion": getattr(track.fx.get(k), "motion", None)
                    if hasattr(track, "fx") else None, "behind": track.baked(k),
                    "bar": bool(getattr(track, "letterbox", False))})
    return out


def save_text_report(track, video: Path) -> Path:
    p = Path(video).with_name(Path(video).stem + ".text.json")
    p.write_text(json.dumps(text_report(track), indent=1))
    return p
