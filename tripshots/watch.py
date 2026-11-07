"""Watching clips, not stills.

Two layers:
  * local (always): in-camera transitions found in our own shot analysis. A phone or action-camera
    clip has no edits inside it, so where the picture changes completely within one file AND the
    frames around that point are smeared by motion blur, the camera swung fast: a whip pan. Cutting
    there (from the outgoing clip's swing into the next shot) hides the cut in the motion, with no
    added effect.
  * Gemini (optional, GEMINI_API_KEY): a 480p proxy of each clip is watched and listened to. Gemini
    returns the good moments with their single best instant (peak), the camera's movement, shake,
    tilt, exposure and sound, plus whip pans / wipes / reveals. Cached forever per file (by content),
    so a clip is only ever uploaded once; the upload is deleted right after.
The clip-log approach, prompt and field names follow tripcut (github.com/divyankrahoria/tripcut, MIT).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import library as lib
from .util import ffmpeg_base, log, read_json, write_json

PROMPT_VERSION = 1
WATCH_DIR = lib.LIB_DIR / "watch"
DEFAULT_MODEL = os.environ.get("TRIPSHOTS_GEMINI_MODEL", "gemini-flash-latest")
FALLBACK_MODEL = os.environ.get("TRIPSHOTS_GEMINI_FALLBACK", "gemini-2.5-flash")

MOTIONS = ("static", "pan", "tilt", "zoom", "walking", "handheld", "drone", "timelapse")
FRAMINGS = ("upright", "tilted", "sideways", "upside_down")
STABILITY = ("steady", "slight_shake", "shaky")
EXPOSURES = ("good", "bright", "dark", "backlit")
AUDIO = ("ambient", "plain", "noisy", "speech", "music")
ENERGIES = ("calm", "lively", "intense")
TRANSITIONS = ("whip_pan", "wipe", "reveal")

PROMPT = """You are the assistant editor on a short travel Reel (vertical, cut to music). Watch AND listen to
this whole clip. It is {duration:.1f} seconds long. Timestamps: seconds from the start of THIS clip, one
decimal (12.5). An editor cuts straight from your log, so they must be exact.

moments: the shots worth cutting to, in time order, never overlapping, 1-8 per clip, each at least 1 s.
Start where the shot settles, end before the camera drifts away. Leave out fumbling, blur and heavy shake.
Keep a good shot even if crooked: report it in framing.
- peak: the single best instant (seconds). An editor using only one second of the shot keeps this instant.
- motion (the camera's): static, pan, tilt, zoom, walking, handheld, drone, timelapse.
- subject: 2-5 words naming what is in frame ("turquoise lake below peaks").
- framing: upright; tilted (horizon visibly crooked); sideways; upside_down.
- stability: steady; slight_shake; shaky (distracting).
- exposure: good; bright (blown sky); dark; backlit.
- audio: ambient (natural sound worth keeping: waves, waterfall, birds, wind in trees, a busy square);
  plain; noisy (wind blasting the mic, handling noise); speech (people talking); music (a song nearby).
- energy: calm, lively, intense.
- score 1-10 against travel footage in general: 9-10 an opening shot (rare), 7-8 strong, 5-6 usable,
  3-4 filler, 1-2 avoid. Most moments are 5-7; at most two 8+ per clip.

transitions: stretches that make good cut points even if unusable as shots: whip_pan (the camera swings
fast and the picture smears), wipe (something passes close and fills the frame), reveal (from a blocked
or dark frame the view opens). start, end and a short note. [] if none. Whip pans go here, not in moments.

Also: summary (1 sentence), location_guess ("" if unknown), time_of_day (dawn, morning, midday, afternoon,
golden_hour, dusk, night, indoors), tags (short lowercase keywords), usable (false only if nothing is
worth cutting to), quality_issues (each with its time range)."""

_T = {"type": "number", "minimum": 0}
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "location_guess": {"type": "string"},
        "time_of_day": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "usable": {"type": "boolean"},
        "quality_issues": {"type": "array", "items": {"type": "string"}},
        "transitions": {"type": "array", "items": {"type": "object", "properties": {
            "start": _T, "end": _T, "type": {"type": "string", "enum": list(TRANSITIONS)},
            "note": {"type": "string"}}, "required": ["start", "end", "type"]}},
        "moments": {"type": "array", "items": {"type": "object", "properties": {
            "start": _T, "end": _T, "peak": _T, "score": {"type": "number"},
            "motion": {"type": "string", "enum": list(MOTIONS)}, "subject": {"type": "string"},
            "framing": {"type": "string", "enum": list(FRAMINGS)},
            "stability": {"type": "string", "enum": list(STABILITY)},
            "exposure": {"type": "string", "enum": list(EXPOSURES)},
            "audio": {"type": "string", "enum": list(AUDIO)},
            "energy": {"type": "string", "enum": list(ENERGIES)}},
            "required": ["start", "end", "peak", "score"]}},
    },
    "required": ["moments", "transitions", "usable"],
}


# ------------------------------------------------------------------ parsing
_TS = re.compile(r"^\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*$")


def to_seconds(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("s")
    m = _TS.match(s)
    if m:
        h, mm, ss = m.groups()
        return int(h or 0) * 3600 + int(mm) * 60 + float(ss)
    return float(s)


def _one_of(v, allowed):
    v = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in allowed else ""


def parse(raw: dict, duration: float) -> dict:
    """Clamp and normalise a model's clip log (models are not always consistent)."""
    def c(t):
        return round(min(max(0.0, to_seconds(t)), duration), 2)
    moments = []
    for m in raw.get("moments") or []:
        try:
            s, e = c(m["start"]), c(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e - s < 0.5:
            continue
        try:
            pk = min(max(s, c(m.get("peak", (s + e) / 2))), e)
        except (TypeError, ValueError):
            pk = (s + e) / 2
        try:
            score = max(1.0, min(10.0, float(m.get("score", 5))))
        except (TypeError, ValueError):
            score = 5.0
        moments.append({"start": s, "end": e, "peak": round(pk, 2), "score": score,
                        "motion": _one_of(m.get("motion"), MOTIONS), "subject": str(m.get("subject") or "")[:60],
                        "framing": _one_of(m.get("framing"), FRAMINGS),
                        "stability": _one_of(m.get("stability"), STABILITY),
                        "exposure": _one_of(m.get("exposure"), EXPOSURES),
                        "audio": _one_of(m.get("audio"), AUDIO), "energy": _one_of(m.get("energy"), ENERGIES)})
    trans = []
    for t in raw.get("transitions") or []:
        try:
            s, e = c(t["start"]), c(t["end"])
        except (KeyError, TypeError, ValueError):
            continue
        k = _one_of(t.get("type"), TRANSITIONS)
        if k:
            trans.append({"start": s, "end": max(s, e), "type": k, "note": str(t.get("note") or "")[:80]})
    return {"moments": sorted(moments, key=lambda m: m["start"]), "transitions": sorted(trans, key=lambda t: t["start"]),
            "summary": str(raw.get("summary") or ""), "location_guess": str(raw.get("location_guess") or ""),
            "time_of_day": str(raw.get("time_of_day") or ""), "tags": [str(t).lower() for t in raw.get("tags") or []][:12],
            "usable": raw.get("usable") is not False, "quality_issues": [str(q) for q in raw.get("quality_issues") or []]}


# ------------------------------------------------------------------ Gemini
def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def available() -> tuple[bool, str]:
    if not api_key():
        return False, "no GEMINI_API_KEY (free key: https://aistudio.google.com/apikey)"
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False, "the Gemini SDK is not installed (pip install google-genai)"
    return True, "ok"


def make_proxy(src: str, dst: Path, height: int = 480) -> Path:
    """Small upload copy with identical timing (480p, 15 fps, mono audio)."""
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".part.mp4")
    subprocess.run(ffmpeg_base() + ["-i", src, "-vf", f"scale=-2:{height}", "-r", "15", "-c:v", "libx264",
                                    "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-ac", "1", "-b:a", "48k",
                                    "-movflags", "+faststart", str(tmp)], check=True, capture_output=True)
    tmp.replace(dst)
    return dst


class Gemini:
    def __init__(self, model: str = DEFAULT_MODEL, fallback: str | None = FALLBACK_MODEL):
        from google import genai
        self.client = genai.Client(api_key=api_key())
        self.model, self.fallback = model, (fallback if fallback != model else None)
        self._busy_until = 0.0
        self._lock = threading.Lock()

    def _active(self, f, timeout=600):
        end = time.time() + timeout
        while getattr(f.state, "name", str(f.state)) in ("PROCESSING", "STATE_UNSPECIFIED", "None"):
            if time.time() > end:
                raise TimeoutError("Gemini took too long to process the upload")
            time.sleep(3)
            f = self.client.files.get(name=f.name)
        if getattr(f.state, "name", str(f.state)) != "ACTIVE":
            raise RuntimeError(f"Gemini could not process the upload ({f.state})")
        return f

    def watch(self, proxy: Path, duration: float) -> tuple[dict, str]:
        from google.genai import types
        up = self._active(self.client.files.upload(file=str(proxy)))
        try:
            cfg = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=SCHEMA)
            last = None
            for attempt in range(3):
                use_fb = self.fallback and time.time() < self._busy_until
                model = self.fallback if use_fb else self.model
                try:
                    r = self.client.models.generate_content(model=model, contents=[up, PROMPT.format(duration=duration)],
                                                            config=cfg)
                    from .ai import extract_json
                    return extract_json(r.text or ""), model
                except Exception as e:  # rate limits, overload, bad JSON
                    last = e
                    if getattr(e, "code", None) == 503 and self.fallback and not use_fb:
                        with self._lock:
                            self._busy_until = time.time() + 300  # overloaded: use the older Flash for a while
                        continue
                    time.sleep(min(60, 5 * 2 ** attempt))
            raise RuntimeError(f"Gemini failed: {last}")
        finally:
            try:
                self.client.files.delete(name=up.name)  # nothing stays uploaded
            except Exception:
                pass


def _cache(sig: str) -> Path:
    return WATCH_DIR / f"{sig}-v{PROMPT_VERSION}.json"


def watch_media(media: list[dict], work: Path, workers: int = 4, model: str | None = None) -> dict[str, dict]:
    """Clip logs for every video (cached per file content). Returns {sig: log}."""
    out = {}
    todo = []
    for m in media:
        if m.get("kind") != "video":
            continue
        c = read_json(_cache(m["sig"]))
        if c:
            out[m["sig"]] = c
        else:
            todo.append(m)
    if not todo:
        if out:
            log(f"watch: all {len(out)} clips already watched (cached)")
        return out
    ok, why = available()
    if not ok:
        log(f"watch: Gemini off ({why}); using local motion analysis only")
        return out
    g = Gemini(model or DEFAULT_MODEL)
    log(f"watch: Gemini watches {len(todo)} new clip(s) as 480p proxies ({len(out)} cached)")

    def one(m):
        try:
            proxy = make_proxy(m["path"], work / "proxies" / f"{m['sig']}.mp4")
            raw, used = g.watch(proxy, float(m.get("duration") or 0))
            res = {**parse(raw, float(m.get("duration") or 0)), "model": used, "name": m["name"]}
            WATCH_DIR.mkdir(parents=True, exist_ok=True)
            write_json(_cache(m["sig"]), res)
            proxy.unlink(missing_ok=True)
            return m["sig"], res
        except Exception as e:
            log(f"  watch failed for {m['name']}: {e}")
            return m["sig"], None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, (sig, res) in enumerate(ex.map(one, todo), 1):
            if res:
                out[sig] = res
            if n % 5 == 0 or n == len(todo):
                log(f"  watched {n}/{len(todo)}")
    return out


# ------------------------------------------------------------------ apply to shots
def local_whips(shots: list[dict]) -> dict[str, list[dict]]:
    """In-camera swings from our own analysis: a picture change inside one file with blurred frames
    around it (consecutive shots of one clip that meet at a blurry boundary)."""
    by_sig: dict[str, list[dict]] = {}
    for s in shots:
        if s["kind"] == "video":
            by_sig.setdefault(s["sig"], []).append(s)
    out: dict[str, list[dict]] = {}
    for sig, lst in by_sig.items():
        lst.sort(key=lambda s: s["t0"])
        for sh in lst:  # inside a shot: a spike of fast camera movement with smeared frames
            sm = sh.get("samples") or {}
            t, sharp, jit = sm.get("t") or [], sm.get("sharp") or [], sm.get("jitter") or []
            if len(t) < 5:
                continue
            jit_a, sharp_a = np.array(jit, float), np.array(sharp, float)
            base = max(float(np.median(jit_a)), 1e-4)
            hot = np.nonzero(jit_a > max(0.08, 6 * base))[0]
            for grp in np.split(hot, np.nonzero(np.diff(hot) > 1)[0] + 1) if len(hot) else []:
                i0, i1 = int(grp[0]), int(grp[-1])
                if i1 - i0 > 3:  # a long stretch of movement is a pan or a walk, not a whip
                    continue
                before = sharp_a[max(0, i0 - 3):i0]
                after = sharp_a[i1 + 1:i1 + 4]
                dip = sharp_a[i0:i1 + 1].min()
                if not len(before) or not len(after):
                    continue
                ref = min(np.median(before), np.median(after))
                changed = max(np.median(before), np.median(after)) / max(1e-6, ref) > 1.5
                if dip < 0.8 * ref or changed:
                    w = jit_a[i0:i1 + 1]
                    mid = float(np.sum(np.array(t[i0:i1 + 1]) * w) / np.sum(w))
                    out.setdefault(sig, []).append({"start": round(mid - 0.15, 2), "end": round(mid + 0.15, 2),
                                                    "type": "whip_pan", "note": "fast swing (motion spike + blur)",
                                                    "src": "local"})
        for a, b in zip(lst, lst[1:]):
            if abs(a["t1"] - b["t0"]) > 0.3:
                continue
            sa, sb = a.get("samples") or {}, b.get("samples") or {}
            ta, tb = sa.get("t") or [], sb.get("t") or []
            if len(ta) < 2 or len(tb) < 2:
                continue
            edge = [v for t, v in zip(ta, sa["sharp"]) if t >= a["t1"] - 0.5] + \
                   [v for t, v in zip(tb, sb["sharp"]) if t <= b["t0"] + 0.5]
            body = list(sa["sharp"]) + list(sb["sharp"])
            if edge and np.median(body) > 0 and min(edge) < 0.55 * float(np.median(body)):
                out.setdefault(sig, []).append({"start": round(a["t1"] - 0.25, 2), "end": round(b["t0"] + 0.25, 2),
                                                "type": "whip_pan", "note": "fast swing (motion blur)", "src": "local"})
    return out


def apply(shots: list[dict], logs: dict[str, dict]) -> int:
    """Attach the watch results to our shots and fold them into the score. Returns how many shots changed."""
    whips = local_whips(shots)
    n = 0
    for s in shots:
        if s["kind"] != "video":
            continue
        lg = logs.get(s["sig"]) or {}
        trans = list(lg.get("transitions") or []) + whips.get(s["sig"], [])
        s["incam"] = [t for t in trans if s["t0"] - 1.0 <= (t["start"] + t["end"]) / 2 <= s["t1"] + 1.0]
        moms = [m for m in lg.get("moments") or [] if m["end"] > s["t0"] and m["start"] < s["t1"]]
        if not lg:
            continue
        a = dict(s.get("ai") or {})
        if not moms:
            a["score"] = round(max(1.0, float(a.get("score", 5)) - 1.0), 1)  # Gemini found nothing good here
            a["watch"] = {"none": True}
        else:
            best = max(moms, key=lambda m: (min(m["end"], s["t1"]) - max(m["start"], s["t0"])) * m["score"])
            w = {k: best[k] for k in ("peak", "score", "motion", "framing", "stability", "exposure", "audio", "energy",
                                      "subject")}
            w["moment"] = [best["start"], best["end"]]
            score = 0.6 * float(a.get("score", 5)) + 0.4 * best["score"]
            score -= 2.0 if best["stability"] == "shaky" else 0.0
            score -= 1.5 if best["framing"] in ("tilted", "sideways", "upside_down") else 0.0
            score -= 0.5 if best["exposure"] in ("dark", "bright") else 0.0
            a["score"] = round(max(1.0, min(10.0, score)), 1)
            a["watch"] = w
            if best.get("subject") and not a.get("note"):
                a["note"] = best["subject"]
            if lg.get("tags"):
                a["tags"] = list(dict.fromkeys(list(a.get("tags") or []) + lg["tags"][:4]))
        s["ai"] = a
        n += 1
    return n
