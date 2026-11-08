"""Sound design: real sound effects and ambience, placed on the picture's exact frames.

Built on the rules of earshot's `real-sound` skill (Leonxlnx/earshot) and Clipwing's Real SFX: every sound
has a visible cause, the music carries the reel, and effects punctuate it.

Cues come from the plan and the rendered text, so they are frame exact:
  transition whip/zoom/spin      whoosh, loudest point on the cut (the motion's velocity peak)
  speed ramp                     whoosh, loudest point where the clip slams into slow motion (or
                                 into the cut, when it speeds up into one)
  freeze-frame on the drop       riser ending 120 ms before it, then one impact on the frame
  flash cut                      camera shutter          glitch cut / colour split   short glitch
  text popping in word by word   soft pops, pitch climbing across the line
  location title                 a short swish           map pins / tracker moves    pops / ticks
  pop-out photo, split-screen    pop / tick when the subject breaks out / each panel enters
  hard cuts                      nothing (about 85 % of cuts in pro edits have no sound of their own)
plus a quiet ambience bed per location zone (waves on the beach, wind on the ridge, birds in the forest),
cut with the picture.

Where sounds come from (first that has the role):
  1. your own library: ~/.tripshots/sfx/library/<role>/ (or any file whose name says whoosh, impact, ...)
  2. Openverse (api.openverse.org): real CC0 / public-domain recordings, fetched once and cached
  3. earshot's sound bank (optional, `./install.sh --sound`): sounds built in code, rendered offline
  4. a small built-in synthesizer, only as a last resort (and the report says so)

Mixing: each take is analysed (attack, peak, end), aligned by its role (attack / peak / end), levelled
by role, varied (take rotation, +-1.5 dB, pitch ramps for runs), limited to about 6 effects per 10 s,
mixed under the music and mastered to -14 LUFS / -1.5 dBTP. Outputs: the reel, NAME.sfx.wav
(effects + ambience stem), NAME.sound.json (every cue, its take, source and licence) and credits
when a licence asks for them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

from .config import HOME, OUT_FPS
from .util import ReelError, ffmpeg_base, log, read_json, run, write_json

SR = 48000
SFX_HOME = HOME / "sfx"
LIBRARY = SFX_HOME / "library"
OV_DIR = SFX_HOME / "openverse"
ES_DIR = SFX_HOME / "earshot"
SYN_DIR = SFX_HOME / "synth"
INDEX = SFX_HOME / "index.json"
OPENVERSE = os.environ.get("OPENVERSE_API", "https://api.openverse.org/v1")
UA = "tripshots/0.2 (personal travel reels; sound effects search)"

# role -> how it is found, aligned and levelled. peak_db: sample peak of the take before the master.
ROLES = {
    "whoosh":    {"q": ["whoosh", "swoosh", "swish"], "dur": (0.25, 2.5), "align": "peak", "peak_db": -10,
                  "es": ["whoosh_fast", "swish", "fit/whoosh.short"], "pri": 3, "words": ["whoosh", "swoosh", "swish", "woosh"],
                  "desc": "a fast airy whoosh"},
    "whoosh_big": {"q": ["big whoosh", "transition whoosh", "deep whoosh"], "dur": (0.6, 3.5), "align": "peak",
                   "peak_db": -8, "es": ["whoosh_big", "pro_whoosh_big"], "pri": 3, "words": ["whoosh", "swoosh"],
                   "desc": "a big deep whoosh"},
    "impact":    {"q": ["cinematic impact", "boom hit", "bass hit"], "dur": (0.3, 4.0), "align": "attack",
                  "peak_db": -4, "es": ["pro_impact", "cut_hit", "impact", "sub_drop"], "pri": 5,
                  "words": ["impact", "hit", "boom", "thud"], "desc": "a deep cinematic impact"},
    "riser":     {"q": ["riser", "uplifter", "rising whoosh"], "dur": (0.8, 6.0), "align": "end", "peak_db": -12,
                  "es": ["riser", "pro_riser", "reverse_swell"], "pri": 4, "words": ["riser", "rise", "uplift", "swell"],
                  "desc": "a rising swell building tension"},
    "pop":       {"q": ["pop", "bubble pop", "cork pop"], "dur": (0.04, 0.8), "align": "attack", "peak_db": -15,
                  "es": ["pro_pop", "ui_pop", "pop", "fit/pop"], "pri": 1, "words": ["pop", "bubble", "cork"],
                  "desc": "a soft short pop"},
    "tick":      {"q": ["tick", "soft click"], "dur": (0.02, 0.5), "align": "attack", "peak_db": -19,
                  "es": ["pro_tap", "tap", "fit/tick", "click"], "pri": 0, "words": ["tick", "click", "tap"],
                  "desc": "a soft tick"},
    "shutter":   {"q": ["camera shutter"], "dur": (0.05, 1.2), "align": "attack", "peak_db": -12,
                  "es": ["shutter"], "pri": 2, "words": ["shutter", "camera"], "desc": "a camera shutter click"},
    "glitch":    {"q": ["glitch", "digital glitch"], "dur": (0.05, 1.0), "align": "attack", "peak_db": -16,
                  "es": ["glitch", "pro_glitch"], "pri": 2, "words": ["glitch", "digital"], "desc": "a short digital glitch"},
}
AMBIENCE = {   # zone -> (shot tags that point to it, Openverse queries)
    "ocean":  (["beach", "ocean", "sea", "coast", "wave", "surf", "shore", "bay"], ["ocean waves", "beach waves"]),
    "water":  (["waterfall", "river", "stream", "creek", "rapids", "fountain"], ["waterfall", "river stream"]),
    "lake":   (["lake", "pond", "lagoon", "reflection"], ["lake water lapping", "lakeside birds"]),
    "forest": (["forest", "jungle", "tree", "woods", "trail", "garden", "park", "green"], ["forest birds", "jungle ambience"]),
    "wind":   (["mountain", "peak", "summit", "glacier", "desert", "dune", "valley", "cliff", "snow", "ridge"],
               ["mountain wind", "wind ambience"]),
    "city":   (["city", "street", "town", "market", "building", "architecture", "castle", "harbor", "traffic"],
               ["city street ambience", "town square ambience"]),
    "rain":   (["rain", "storm", "fog", "mist"], ["rain ambience"]),
    "night":  (["night", "stars", "milky way", "aurora", "dusk"], ["night crickets", "night ambience"]),
}
AMB_RMS_DB = -34.0
LICENSES_DEFAULT = "cc0,pdm"
DENSITY_PER_10S = 6


# ================================================================ audio helpers
def decode(path: Path, sr: int = SR) -> np.ndarray:
    """Any audio file -> float32 stereo [n, 2] at sr (via ffmpeg)."""
    p = subprocess.run(ffmpeg_base() + ["-i", str(path), "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise ReelError(f"could not decode {Path(path).name}")
    return np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(x, -1, 1).astype(np.float32), sr, subtype="PCM_24")
    return path


def _env(x: np.ndarray, win: float = 0.01) -> np.ndarray:
    m = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    n = max(1, int(win * SR))
    return np.sqrt(np.convolve(m.astype(np.float64) ** 2, np.ones(n) / n, mode="same"))


def analyze_take(x: np.ndarray) -> dict:
    """Trim silence; find attack (first transient), peak (loudest 10 ms) and end."""
    env = _env(x)
    pk = float(env.max()) if len(env) else 0.0
    if pk <= 1e-6:
        return {"ok": False, "why": "silent"}
    thr = pk * 10 ** (-40 / 20)
    live = np.nonzero(env > thr)[0]
    a, b = int(live[0]), int(live[-1])
    attack = int(np.nonzero(env > pk * 0.25)[0][0])
    peak = int(np.argmax(env))
    clipped = float(np.mean(np.abs(x) >= 0.999))
    return {"ok": True, "start": a, "end": b, "attack": attack, "peak": peak, "dur": (b - a) / SR,
            "attack_to_peak_ms": (peak - attack) / SR * 1000, "clipped": clipped, "peak_abs": float(np.abs(x).max())}


def _resample_pitch(x: np.ndarray, semitones: float) -> np.ndarray:
    """Pitch by resampling (like a tape speed change): +st = shorter and higher."""
    if abs(semitones) < 0.01:
        return x
    f = 2 ** (semitones / 12)
    n = int(len(x) / f)
    src = np.arange(n) * f
    return np.stack([np.interp(src, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], 1).astype(np.float32)


def _srand(*parts) -> float:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


# ================================================================ sources
def _index() -> dict:
    return read_json(INDEX, {}) or {}


def _save_index(d: dict) -> None:
    SFX_HOME.mkdir(parents=True, exist_ok=True)
    write_json(INDEX, d)


def library_takes(role: str) -> list[dict]:
    """The user's own sounds: a folder named after the role, or file names containing its words."""
    if not LIBRARY.exists():
        return []
    words = [role] + ROLES.get(role, {}).get("words", []) if role in ROLES else [role]
    out = []
    for p in sorted(LIBRARY.rglob("*")):
        if p.suffix.lower() not in (".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".m4a"):
            continue
        rel = str(p.relative_to(LIBRARY)).lower()
        parts = re.split(r"[^a-z]+", rel)
        if role in parts or any(w in parts for w in words):
            if role == "whoosh" and ("big" in parts or "whoosh_big" in rel):
                continue
            out.append({"file": str(p), "source": "library", "license": "yours", "title": p.stem})
    return out


def _http_json(url: str, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _download(url: str, dst: Path, timeout=30) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dst, "wb") as fh:
        shutil.copyfileobj(r, fh)
    return dst


_ov_last = [0.0]
_ov_offline = [False]


def openverse_search(query: str, licenses: str = LICENSES_DEFAULT, length: str = "short", page_size: int = 20):
    """Search Openverse audio (anonymous: 20 requests/min, 200/day, so callers cache everything)."""
    if _ov_offline[0]:
        return []
    wait = 3.2 - (time.time() - _ov_last[0])
    if wait > 0:
        time.sleep(wait)
    _ov_last[0] = time.time()
    params = {"q": query, "license": licenses, "page_size": page_size, "mature": "false", "filter_dead": "true"}
    if length:
        params["length"] = length
    data = None
    for extra in ({"category": "sound_effect"} if length == "short" else {}, {}):  # category filter if supported
        url = f"{OPENVERSE}/audio/?" + urllib.parse.urlencode({**params, **extra})
        try:
            data = _http_json(url)
            break
        except urllib.error.HTTPError as e:
            if e.code in (400, 422) and extra:
                continue
            if e.code == 429:
                log("Openverse rate limit reached (anonymous: ~200 searches a day); using what's cached")
            else:
                log(f"Openverse error {e.code}; using local / earshot sounds")
            _ov_offline[0] = True
            return []
        except Exception as e:
            _ov_offline[0] = True
            log(f"Openverse unreachable ({e}); using local / earshot sounds")
            return []
    return (data or {}).get("results", []) or []


def _ov_ok(r: dict, dur_range, licenses: str) -> bool:
    lic = str(r.get("license", "")).lower()
    allowed = {x.strip() for x in licenses.split(",")}
    if lic not in allowed or any(bad in lic for bad in ("nc", "nd", "sa", "sampling")):
        return False
    d = (r.get("duration") or 0) / 1000.0
    if d and not (dur_range[0] * 0.5 <= d <= dur_range[1] * 4):
        return False
    ft = str(r.get("filetype") or Path(urllib.parse.urlparse(r.get("url", "")).path).suffix.lstrip(".")).lower()
    return ft in ("mp3", "wav", "ogg", "flac", "oga", "x-wav", "mpeg") and bool(r.get("url"))


def _quality(meta: dict, role: str) -> float:
    """Measured fitness of a take for its role (agents cannot listen: measure)."""
    if not meta.get("ok"):
        return -99
    lo, hi = ROLES[role]["dur"] if role in ROLES else (2.0, 600.0)
    s = 0.0
    s -= 3 * max(0.0, meta["clipped"] - 0.001) * 100
    s -= 2.0 if not (lo <= meta["dur"] <= hi) else 0.0
    a2p = meta["attack_to_peak_ms"]
    align = ROLES.get(role, {}).get("align", "start")
    if align == "attack" and role != "impact" and a2p > 80:
        s -= 2.0  # slow attack: an attack-aligned sound would peak late
    if role == "impact" and (meta["attack"] - meta["start"]) > 0.03 * SR:
        s -= 2.0  # an impact must hit on its first frame (its boom may swell after the transient)
    if align == "peak" and meta["peak"] - meta["start"] < 0.08 * SR:
        s -= 1.5  # a whoosh that starts on its loudest moment is a hit, not a whoosh
    return s


def fetch_openverse(role: str, licenses: str = LICENSES_DEFAULT, want: int = 5, ambience: bool = False) -> list[dict]:
    idx = _index()
    key = f"ov:{role}:{licenses}"
    if key in idx:
        return [t for t in idx[key] if Path(t["file"]).exists()]
    queries = AMBIENCE[role][1] if ambience else ROLES[role]["q"]
    dur_range = (8.0, 600.0) if ambience else ROLES[role]["dur"]
    got, seen = [], set()
    OV_DIR.mkdir(parents=True, exist_ok=True)
    for q in queries:
        for r in openverse_search(q, licenses, "medium" if ambience else "short"):
            rid = r.get("id")
            if not rid or rid in seen or not _ov_ok(r, dur_range, licenses):
                continue
            seen.add(rid)
            ext = (r.get("filetype") or "mp3").replace("x-wav", "wav").replace("mpeg", "mp3")
            dst = OV_DIR / f"{rid}.{ext}"
            try:
                if not dst.exists():
                    _download(r["url"], dst)
                meta = analyze_take(decode(dst))
            except Exception:
                dst.unlink(missing_ok=True)
                continue
            q_score = _quality(meta, role) if not ambience else (0 if meta.get("ok") and meta["dur"] >= 8 else -99)
            if q_score < -1.5:
                continue
            got.append({"file": str(dst), "source": "openverse", "id": rid, "title": r.get("title"),
                        "creator": r.get("creator"), "license": r.get("license"),
                        "license_version": r.get("license_version"), "landing": r.get("foreign_landing_url"),
                        "provider": r.get("provider") or r.get("source"), "score": q_score})
            if len(got) >= want:
                break
        if len(got) >= want:
            break
    if got or not _ov_offline[0]:
        idx[key] = sorted(got, key=lambda t: -t.get("score", 0))
        _save_index(idx)
    return idx.get(key, got)


def _earshot():
    try:
        from earshot.forge import sfx as es  # optional: pip install from github.com/Leonxlnx/earshot
        return es
    except Exception:
        return None


def earshot_takes(role: str, want: int = 4) -> list[dict]:
    es = _earshot()
    if es is None or role not in ROLES:
        return []
    idx = _index()
    key = f"es:{role}"
    if key in idx and all(Path(t["file"]).exists() for t in idx[key]):
        return idx[key]
    try:
        listing = es.sfx_list()
        sounds = listing.get("sounds", listing) if isinstance(listing, dict) else listing
    except Exception:
        return []
    cats = ROLES[role]["es"]
    picks = []
    for c in cats:
        picks += [s["id"] for s in sounds if s["id"].rsplit("/", 1)[0] == c]
    picks = picks[:want]
    out = []
    ES_DIR.mkdir(parents=True, exist_ok=True)
    for sid in picks:
        dst = ES_DIR / (sid.replace("/", "__") + ".wav")
        try:
            if not dst.exists():
                es.sfx_render(sid, str(dst), peak_db=-1.0)
            out.append({"file": str(dst), "source": "earshot", "id": sid, "license": "MIT (earshot, code-made)",
                        "title": sid})
        except Exception as e:
            log(f"earshot could not render {sid}: {e}")
    idx[key] = out
    _save_index(idx)
    return out


def synth_takes(role: str) -> list[dict]:
    """Last resort, clearly labelled: tiny procedural sounds so a reel never ships silent."""
    SYN_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for k in range(3):
        dst = SYN_DIR / f"{role}_{k}.wav"
        if not dst.exists():
            write_wav(dst, _synth(role, k))
        out.append({"file": str(dst), "source": "synth", "license": "generated", "title": f"{role} (synth {k})"})
    return out


def _synth(role: str, k: int) -> np.ndarray:
    rng = np.random.default_rng(100 + k)
    def env_adsr(n, a, r):
        e = np.ones(n)
        na, nr = int(a * SR), int(r * SR)
        e[:na] = np.linspace(0, 1, na) if na else 1
        e[-nr:] = np.linspace(1, 0, nr) ** 2 if nr else 1
        return e
    if role in ("whoosh", "whoosh_big"):
        dur = 0.9 if role == "whoosh_big" else 0.55
        n = int(dur * SR)
        noise = rng.standard_normal(n)
        t = np.arange(n) / n
        out = np.zeros(n)
        # band sweep: one-pole low-pass with a moving cutoff, peaking at 60 % of the length
        cut = 0.02 + 0.25 * np.exp(-((t - 0.6) / 0.2) ** 2)
        y = 0.0
        for i in range(n):
            y += cut[i] * (noise[i] - y)
            out[i] = y
        out *= np.exp(-((t - 0.6) / 0.25) ** 2)
        x = out
    elif role == "impact":
        n = int(1.2 * SR)
        t = np.arange(n) / SR
        x = np.sin(2 * np.pi * (48 + 30 * np.exp(-t * 18)) * t) * np.exp(-t * 4.5)
        x[: int(0.01 * SR)] += rng.standard_normal(int(0.01 * SR)) * np.linspace(1, 0, int(0.01 * SR)) * 0.6
    elif role == "riser":
        n = int(2.0 * SR)
        t = np.arange(n) / SR
        x = rng.standard_normal(n) * (t / 2) ** 2 * 0.6 + np.sin(2 * np.pi * (200 + 500 * (t / 2) ** 2) * t) * (t / 2) ** 3 * 0.4
        x *= env_adsr(n, 0.05, 0.03)
    elif role == "pop":
        n = int(0.12 * SR)
        t = np.arange(n) / SR
        x = np.sin(2 * np.pi * (700 + 300 * k) * (1 - 0.4 * t / 0.12) * t) * np.exp(-t * 45)
    elif role == "tick":
        n = int(0.05 * SR)
        x = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 160)
    elif role == "shutter":
        n = int(0.25 * SR)
        x = np.zeros(n)
        for at in (0.0, 0.11):
            i = int(at * SR)
            m = int(0.03 * SR)
            x[i:i + m] += rng.standard_normal(m) * np.exp(-np.arange(m) / SR * 120)
    else:  # glitch
        n = int(0.22 * SR)
        x = np.sign(np.sin(2 * np.pi * 180 * np.arange(n) / SR)) * (rng.random(n) > 0.4) * 0.5
        x = np.round(x * 6) / 6 * np.exp(-np.arange(n) / SR * 12)
    x = x / (np.abs(x).max() + 1e-9) * 0.9
    return np.stack([x, x], 1).astype(np.float32)


SOURCE_PREF = {"library": 3.0, "openverse": 1.0, "earshot": 0.0, "synth": -5.0}


def takes_for(role: str, licenses: str = LICENSES_DEFAULT, online: bool = True) -> list[dict]:
    """The pool for a role: your library first, then real recordings, then earshot's bank, ranked by
    source and by how well each take measures up for the role (attack, peak position, clipping)."""
    pool = library_takes(role)
    if len(pool) < 4 and online:
        pool += fetch_openverse(role, licenses)
    if len(pool) < 4:
        pool += earshot_takes(role)
    if not pool:
        pool = synth_takes(role)

    def rank(t):
        try:
            q = _quality(_load_take(t)[1], role)
        except Exception:
            q = -99
        return SOURCE_PREF.get(t["source"], 0) + q
    scored = sorted(pool, key=rank, reverse=True)
    return [t for t in scored if rank(t) > -50]


def ambience_takes(zone: str, licenses: str, online: bool) -> list[dict]:
    pool = library_takes(zone)
    if not pool and online:
        pool = fetch_openverse(zone, licenses, want=2, ambience=True)
    return pool  # no synthetic ambience: a fake bed sounds worse than none


# ================================================================ cues
def _seg_tags(plan: dict) -> dict[str, list[str]]:
    shots = read_json(Path(plan.get("work", ".")) / "shots_scored.json", []) or []
    out = {}
    for s in shots:
        a = s.get("ai", {})
        words = [t.lower() for t in a.get("tags", [])] + re.split(r"\W+", str(a.get("note", "")).lower())
        if zone_for(words) is None:  # no AI tags (or none that point to a place): read the picture
            words += _look_tags(s.get("thumb"))
        out[s["id"]] = words
    return out


def _look_tags(thumb: str | None) -> list[str]:
    """Rough place words from the picture's colours, for footage the AI hasn't described."""
    import cv2
    im = cv2.imread(str(thumb)) if thumb else None
    if im is None:
        return []
    hsv = cv2.cvtColor(cv2.resize(im, (96, 54)), cv2.COLOR_BGR2HSV).astype(np.float32)
    h, sat, val = hsv[..., 0], hsv[..., 1] / 255, hsv[..., 2] / 255
    low = slice(int(54 * 0.55), 54)
    if val.mean() < 0.22:
        return ["night"]
    blue_low = float(np.mean((h[low] > 85) & (h[low] < 130) & (sat[low] > 0.2) & (val[low] > 0.25)))
    green = float(np.mean((h > 33) & (h < 85) & (sat > 0.25) & (val > 0.15)))
    sky_top = float(np.mean((h[:20] > 90) & (h[:20] < 130) & (val[:20] > 0.45)))
    if blue_low > 0.3:
        return ["sea"]
    if green > 0.3:
        return ["forest"]
    if sky_top > 0.4:
        return ["mountain"]
    return []


def zone_for(words: list[str]) -> str | None:
    best, hits = None, 0
    for z, (keys, _) in AMBIENCE.items():
        h = sum(1 for w in words for k in keys if k in w)
        if h > hits:
            best, hits = z, h
    return best


def build_cues(plan: dict, text_events: list[dict] | None = None) -> list[dict]:
    """Every picture event that earns a sound, with its exact time and role."""
    segs = plan["segments"]
    total = float(plan["duration"])
    cues = []

    def add(t, role, why, run_i=0, gain=0.0, pri=None, group=None):
        if 0 <= t <= total + 0.05:
            cues.append({"t": round(float(t), 4), "role": role, "why": why, "run": run_i, "gain_db": gain,
                         "pri": ROLES[role]["pri"] if pri is None else pri,
                         "group": group or f"{role}@{t:.3f}"})

    big = {"zoom_in", "zoom_out", "spin"}
    for i, s in enumerate(segs[:-1]):
        tr = s.get("trans_out")
        cut = segs[i + 1]["out_start"]
        if tr == "whip" or tr in big:
            add(cut, "whoosh_big" if tr in big else "whoosh", f"{tr} transition")
        elif tr == "flash":
            add(cut, "shutter", "flash cut")
        elif tr == "glitch":
            add(cut, "glitch", "glitch transition")
    for i, s in enumerate(segs[:-1]):
        if s.get("incam_out"):  # the camera's own swing: a real whoosh where the picture smears
            add(segs[i + 1]["out_start"], "whoosh", "in-camera whip pan", gain=-3, pri=3)
    for i, s in enumerate(segs):
        if s.get("ramp") and not s.get("panel"):
            from .retime import hit_time
            h = hit_time(s)
            if h is not None:  # the slam into slow motion
                add(h, "whoosh", f"{s['ramp']} speed ramp")
            elif s["ramp"] == "rush" and i + 1 < len(segs) and not s.get("trans_out"):
                add(segs[i + 1]["out_start"], "whoosh", "speeds up into the cut", gain=-2)
        if s.get("rgb") and i > 0:
            add(s["out_start"], "glitch", "colour-split cut", gain=-3)
        if s.get("layout") == "popout":
            add(s["out_start"] + 0.3, "pop", "subject steps out of the frame")
        for k, c in enumerate(s.get("clips") or []):
            if float(c.get("t0", 0)) > 0.02:
                add(s["out_start"] + float(c["t0"]), "tick", "panel enters", run_i=k, group=f"panel@{i}")
    fz = plan.get("freeze")
    if fz:
        add(fz["t"], "impact", "freeze-frame on the drop")
        add(fz["t"] - 0.12, "riser", "build into the drop")
    elif plan.get("drops"):
        d = plan["drops"][0]  # no freeze: one impact on the first big drop, if a cut sits on it
        if any(abs(s["out_start"] - d) < 0.05 for s in segs[1:]):
            add(d, "impact", "cut on the drop", gain=-3)
    for o in plan.get("overlays") or []:
        if o.get("type") != "map":
            continue
        st = float(o["start"])
        if o.get("mode") == "intro":
            from .routemap import intro_schedule
            first, arrive = intro_schedule(len(o.get("stops") or []), [float(b) for b in o.get("beats") or []],
                                           float(o["duration"]))
            add(st + 0.05, "whoosh", "map card slides in", gain=-4, pri=1)
            for k, t in enumerate([first] + arrive):
                add(st + t, "pop", "map pin", run_i=k, group=f"map@{st}", pri=2.5)
        else:
            for k, (t, _) in enumerate((o.get("keys") or [])[1:]):
                add(st + float(t), "tick", "tracker moves", run_i=k, group=f"tracker@{st}")
    for ev in text_events or []:
        add(ev["t"], ev["role"], ev["why"], run_i=ev.get("run", 0), gain=ev.get("gain_db", 0.0), pri=ev.get("pri"),
            group=ev.get("group"))
    cues.sort(key=lambda c: c["t"])
    return restrain(cues)


def restrain(cues: list[dict], per_10s: int = DENSITY_PER_10S) -> list[dict]:
    """About 6 designed gestures in any 10 s (a run of word pops or map pins is one gesture, kept or
    dropped whole: half-sounded runs are a cheap tell); the most important win; nothing steps on an
    impact's tail."""
    groups: dict[str, list] = {}
    for c in cues:
        groups.setdefault(c.get("group") or f"{c['role']}@{c['t']}", []).append(c)
    order = sorted(groups.values(), key=lambda g: (-max(c.get("pri", 0) for c in g), g[0]["t"]))
    out: list[dict] = []
    anchors: list[float] = []  # one time per accepted gesture (its first cue)
    for g in order:
        t0 = min(c["t"] for c in g)
        if any(abs(x["t"] - c["t"]) < 0.06 and x["role"] == c["role"] for c in g for x in out):
            continue
        if any(x["role"] == "impact" and 0 < c["t"] - x["t"] < 0.45 and c["role"] != "riser" for c in g for x in out):
            continue
        cand = anchors + [t0]
        if all(sum(1 for a in cand if st <= a <= st + 10) <= per_10s for st in cand):
            out += g
            anchors.append(t0)
    return sorted(out, key=lambda c: c["t"])


def text_events_from(track) -> list[dict]:
    """Entrance times of the rendered text (TextTrack after the frame loop)."""
    evs = []
    for k, el in getattr(track, "built", {}).items():
        if el is None:
            continue
        o = track.specs[k]
        kind = o.get("type")
        times = sorted({round(el.start + s.t_in, 3) for s in el.sprites})
        grp = f"text{k}"
        if kind == "location":
            evs.append({"t": el.start, "role": "whoosh", "why": "location title", "gain_db": -6, "pri": 1})
        elif el.anim in ("pop", "scale"):
            for i, t in enumerate(times[:8]):  # the hook's words landing on the beat: a signature moment
                evs.append({"t": t, "role": "pop", "why": f"{kind} word pops in", "run": i, "group": grp,
                            "pri": 3.5 if kind == "hook" else None})
        elif el.anim == "typewriter":
            for i, t in enumerate(times[::3][:12]):
                evs.append({"t": t, "role": "tick", "why": f"{kind} typed", "run": i, "gain_db": -4, "group": grp})
        elif kind in ("hook", "cta"):
            evs.append({"t": el.start, "role": "whoosh", "why": f"{kind} slides in", "gain_db": -8, "pri": 1})
    return evs


# ================================================================ mixing
_CACHE: dict[str, tuple[np.ndarray, dict]] = {}


def _load_take(take: dict) -> tuple[np.ndarray, dict]:
    f = take["file"]
    if f not in _CACHE:
        x = decode(Path(f))
        _CACHE[f] = (x, analyze_take(x))
    return _CACHE[f]


def _place(stem: np.ndarray, x: np.ndarray, meta: dict, t: float, align: str, gain: float) -> dict:
    a, b = meta["start"], meta["end"] + int(0.02 * SR)
    clip = x[a:b] * gain
    anchor = {"attack": meta["attack"], "peak": meta["peak"], "end": meta["end"]}.get(align, meta["start"]) - a
    pos = int(round(t * SR)) - anchor
    lo, hi = max(0, pos), min(len(stem), pos + len(clip))
    if hi > lo:
        fade = min(int(0.004 * SR), (hi - lo) // 4)
        seg = clip[lo - pos:hi - pos].copy()
        if lo > pos and fade:  # cut into the head: tiny fade so it can't click
            seg[:fade] *= np.linspace(0, 1, fade)[:, None]
        stem[lo:hi] += seg
    return {"placed_at": round((pos + anchor) / SR, 4), "err_ms": round(((pos + anchor) / SR - t) * 1000, 2)}


def design(plan: dict, text_events: list[dict] | None = None, cfg: dict | None = None) -> dict:
    """Build the effects + ambience stem for a plan. Returns {stem, cues, ambience, sources}."""
    cfg = {**(plan.get("sound") or {}), **(cfg or {})}
    licenses = str(cfg.get("licenses") or LICENSES_DEFAULT)
    online = cfg.get("online", True) and os.environ.get("TRIPSHOTS_OFFLINE") != "1"
    total = float(plan["duration"])
    n = int(math.ceil((total + 0.5) * SR))
    stem = np.zeros((n, 2), np.float32)
    report = {"cues": [], "ambience": [], "sources": {}}
    level = float(cfg.get("level_db", 0.0))
    if str(cfg.get("sfx", "on")) != "off":
        cues = build_cues(plan, text_events)
        pools: dict[str, list] = {}
        counter: dict[str, int] = {}
        for c in cues:
            role = c["role"]
            if role not in pools:
                pools[role] = [t for t in takes_for(role, licenses, online) if _load_take(t)[1].get("ok")][:4]
            pool = pools[role]
            if not pool:
                continue
            # cycle the takes (never the same twice in a row); pops in a run share a take and climb
            k = counter.get(role, 0)
            if role in ("pop", "tick") and c["run"] > 0:
                k = max(0, k - 1)
            else:
                counter[role] = k + 1
            take = pool[k % len(pool)]
            x, meta = _load_take(take)
            st = min(3.0, 0.6 * c["run"]) if role in ("pop", "tick") else (_srand(c["t"], role) - 0.5) * 0.6
            if st:
                x = _resample_pitch(x, st)
                meta = analyze_take(x)
            target = ROLES[role]["peak_db"] + c["gain_db"] + level + (_srand("g", c["t"]) - 0.5) * 3
            gain = 10 ** (target / 20) / max(1e-6, meta["peak_abs"])
            if role not in ("whoosh", "whoosh_big", "riser"):  # effects dry and centred
                x = np.repeat(x.mean(axis=1, keepdims=True), 2, axis=1)
            where = _place(stem, x, meta, c["t"], ROLES[role]["align"], gain)
            late = role in ("pop", "tick", "glitch", "shutter") and meta["attack_to_peak_ms"] > 75
            report["cues"].append({**c, **where, "take": Path(take["file"]).name, "source": take["source"],
                                   "license": take.get("license"), "pitch_st": round(st, 2),
                                   "warn": "slow attack: peaks late" if late else None})
            report["sources"][take["file"]] = {k2: take.get(k2) for k2 in ("source", "title", "creator", "license",
                                                                            "license_version", "landing", "provider")}
    if str(cfg.get("ambience", "on")) != "off":
        _ambience(plan, stem, licenses, online, report, level, str(cfg.get("native", "auto")))
    report["stem_peak_db"] = round(20 * math.log10(max(1e-9, float(np.abs(stem).max()))), 1)
    return {"stem": stem, **report}


def ambience_zones(plan: dict) -> list[list]:
    """[zone, from, to] beds: one per place. Shots from the same GPS place share the place's main
    zone; without GPS, each shot takes the main zone of its neighbourhood; beds under 2 s join a neighbour."""
    tags = _seg_tags(plan)
    shots = {s["id"]: s for s in (read_json(Path(plan.get("work", ".")) / "shots_scored.json", []) or [])}
    segs = plan["segments"]
    sids = [s.get("shot_id") or (s.get("clips") or [{}])[0].get("shot_id") for s in segs]
    own = [zone_for(tags.get(i, [])) for i in sids]
    durs = [float(s["dur"]) for s in segs]
    place = [None] * len(segs)
    gps = [shots.get(i, {}).get("gps") for i in sids]
    if sum(1 for g in gps if g) >= len(segs) // 2:
        from .routemap import build_stops, haversine
        stops = build_stops([shots[i] for i in sids if shots.get(i, {}).get("gps")], 12)
        for k, g in enumerate(gps):
            if g and stops:
                place[k] = min(range(len(stops)), key=lambda j: haversine(stops[j]["ll"], g))
    zone = []
    for k in range(len(segs)):
        if place[k] is not None:
            group = [j for j in range(len(segs)) if place[j] == place[k]]
        else:
            group = range(max(0, k - 2), min(len(segs), k + 3))
        votes = {}
        for j in group:
            if own[j]:
                votes[own[j]] = votes.get(own[j], 0) + durs[j]
        zone.append(max(votes, key=votes.get) if votes else None)
    zones = []
    for z, s in zip(zone, segs):
        a, b = float(s["out_start"]), float(s["out_start"]) + float(s["dur"])
        if zones and zones[-1][0] == z:
            zones[-1][2] = b
        else:
            zones.append([z, a, b])
    i = 0
    while len(zones) > 1 and i < len(zones):
        z, a, b = zones[i]
        if b - a >= 2.0:
            i += 1
            continue
        nb = [n for n in (zones[i - 1] if i else None, zones[i + 1] if i + 1 < len(zones) else None) if n]
        tgt = max(nb, key=lambda n: n[2] - n[1])
        tgt[1], tgt[2] = min(tgt[1], a), max(tgt[2], b)
        del zones[i]
        merged = []
        for zz in zones:
            if merged and merged[-1][0] == zz[0]:
                merged[-1][2] = zz[2]
            else:
                merged.append(zz)
        zones[:] = merged
        i = 0
    return zones


def clip_audio(src: str, t0: float, dur: float) -> np.ndarray | None:
    """The camera's own sound for [t0, t0+dur] of a clip, or None (no audio track)."""
    p = subprocess.run(ffmpeg_base() + ["-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-vn",
                                        "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if p.returncode != 0 or len(p.stdout) < SR * 8 * 0.5:
        return None
    return np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()


def judge_clip_audio(x: np.ndarray) -> tuple[bool, str, dict]:
    """Is this usable as an ambience bed? Rejects near silence, clipping and wind rumble."""
    mono = x.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono ** 2))) + 1e-12
    db = 20 * math.log10(rms)
    clip = float(np.mean(np.abs(x) > 0.985))
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)
    low = float(spec[freqs < 150].sum() / max(1e-12, spec.sum()))
    env = _env(x, 0.05)
    crest = float(np.percentile(env, 99) / max(1e-9, np.median(env)))  # bumps, knocks, shouts
    m = {"rms_db": round(db, 1), "clipped": round(clip, 4), "low_share": round(low, 2), "crest": round(crest, 1)}
    if db < -55:
        return False, "near silent", m
    if clip > 0.001:
        return False, "clipped", m
    if low > 0.6:
        return False, "wind / handling rumble", m
    if crest > 12:
        return False, "bumps or loud one-off noises", m
    return True, "clean", m


def native_beds(plan: dict, mode: str = "auto") -> list[dict]:
    """Segments whose own clip sound is clean enough to be their ambience (the real waves, the real
    market). Needs speed 1 and no speed ramp; Gemini's audio label (watch.py) vetoes speech/music/noise."""
    if mode == "off":
        return []
    shots = {s["id"]: s for s in (read_json(Path(plan.get("work", ".")) / "shots_scored.json", []) or [])}
    beds = []
    for k, e in enumerate(plan["segments"]):
        if e.get("kind") != "video" or e.get("panel") or e.get("ramp") or abs(float(e.get("speed", 1)) - 1) > 0.01:
            continue
        sh = shots.get(e.get("shot_id"), {})
        label = ((sh.get("ai") or {}).get("watch") or {}).get("audio")
        if mode == "auto" and label in ("speech", "music", "noisy"):
            beds.append({"seg": k, "ok": False, "why": f"Gemini heard {label}"})
            continue
        x = clip_audio(e["src"], float(e.get("in", 0)), float(e["dur"]) + 0.08)
        if x is None:
            continue
        ok, why, m = judge_clip_audio(x)
        if ok and label == "silent":
            ok, why = False, "Gemini heard nothing worth keeping"
        beds.append({"seg": k, "ok": ok, "why": why, "label": label, **m, "x": x if ok else None,
                     "from": float(e["out_start"]), "to": float(e["out_start"]) + float(e["dur"])})
    return beds


def _ambience(plan, stem, licenses, online, report, level, native: str = "auto"):
    zones = ambience_zones(plan)
    beds = native_beds(plan, native)
    cover = np.zeros(len(stem), np.float32)  # 1 where the clip's own sound plays
    f = int(0.04 * SR)
    for b in beds:
        if not b["ok"]:
            continue
        x = b.pop("x")
        rms = float(np.sqrt(np.mean(x ** 2))) + 1e-9
        g = min(10 ** (12 / 20), 10 ** ((AMB_RMS_DB + 3 + level) / 20) / rms)  # never lift noise by > 12 dB
        piece = x * g
        piece[:f] *= np.linspace(0, 1, f)[:, None]
        piece[-f:] *= np.linspace(1, 0, f)[:, None]
        p0 = int(b["from"] * SR)
        p1 = min(len(stem), p0 + len(piece))
        stem[p0:p1] += piece[:p1 - p0]
        c1 = min(len(stem), int(b["to"] * SR))
        cover[p0:c1] = 1.0
        report["ambience"].append({"zone": "clip", "from": round(b["from"], 3), "to": round(b["to"], 3),
                                   "take": Path(plan["segments"][b["seg"]]["src"]).name, "source": "clip",
                                   "license": "own footage", "gain_db": round(20 * math.log10(g), 1)})
    report["native"] = [{k: v for k, v in b.items() if k != "x"} for b in beds]
    if cover.any():  # soften the edges of the gaps so library beds duck in and out, not click
        k = np.ones(f, np.float32) / f
        cover = np.clip(np.convolve(cover, k, mode="same"), 0, 1)
    used = {}
    for z, a, b in zones:
        if z is None:
            continue
        if z not in used:
            used[z] = ambience_takes(z, licenses, online)
        pool = used[z]
        if not pool:
            continue
        take = pool[0]
        x, meta = _load_take(take)
        x = x[meta["start"]:meta["end"]]
        if len(x) < SR:
            continue
        need = int((b - a + 0.08) * SR)
        off = int(_srand("amb", z, a) * max(0, len(x) - need))
        piece = x[off:off + need]
        while len(piece) < need:  # loop with a short crossfade (rarely needed: beds are long)
            xf = int(0.2 * SR)
            nxt = x[:need - len(piece) + xf]
            ramp = np.linspace(0, 1, min(xf, len(nxt), len(piece)))[:, None]
            m = len(ramp)
            piece = np.concatenate([piece[:-m], piece[-m:] * (1 - ramp) + nxt[:m] * ramp, nxt[m:]])
        rms = float(np.sqrt(np.mean(piece ** 2))) + 1e-9
        piece = piece * (10 ** ((AMB_RMS_DB + level) / 20) / rms)
        f = int(0.04 * SR)  # cut with the picture: 40 ms in/out, no clicks
        piece[:f] *= np.linspace(0, 1, f)[:, None]
        piece[-f:] *= np.linspace(1, 0, f)[:, None]
        p0 = int(a * SR)
        p1 = min(len(stem), p0 + len(piece))
        free = 1.0 - cover[p0:p1, None]
        if float(free.mean()) < 0.05:
            continue  # the whole zone plays the clips' own sound
        stem[p0:p1] += piece[:p1 - p0] * free
        report["ambience"].append({"zone": z, "from": round(a, 3), "to": round(b, 3), "take": Path(take["file"]).name,
                                   "source": take["source"], "license": take.get("license")})
        report["sources"][take["file"]] = {k2: take.get(k2) for k2 in ("source", "title", "creator", "license",
                                                                        "license_version", "landing", "provider")}


def loudness(path: Path) -> dict:
    """Integrated loudness, true peak and range (ffmpeg loudnorm, measurement only)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        return {}
    d = json.loads(m.group(0))
    return {"I": float(d["input_i"]), "TP": float(d["input_tp"]), "LRA": float(d["input_lra"]),
            "thresh": float(d["input_thresh"]), "offset": float(d.get("target_offset", 0))}


def mix_into(video: Path, plan: dict, text_events: list[dict] | None, work: Path) -> dict | None:
    """Design the sound for a rendered reel, mix it under the music, master, and mux (video copied)."""
    cfg = plan.get("sound") or {}
    if str(cfg.get("sfx", "on")) == "off" and str(cfg.get("ambience", "on")) == "off":
        return None
    log("sound design: effects + ambience on the cue frames...")
    res = design(plan, text_events)
    if not res["cues"] and not res["ambience"]:
        log("sound design: nothing to add")
        return None
    stem_path = video.with_suffix(".sfx.wav")
    write_wav(stem_path, res["stem"][: int((float(plan["duration"]) + 0.05) * SR)])
    has_music = bool((plan.get("music") or {}).get("path"))
    tmp = video.with_name(video.stem + ".mix.mp4")
    if has_music:  # sum the music already in the reel with the stem, then master
        graph = "[0:a][1:a]amix=inputs=2:normalize=0:duration=first[m]"
    else:
        graph = "[1:a]anull[m]"
    meas_wav = work / "mix_measure.wav"
    run(ffmpeg_base() + ["-i", str(video), "-i", str(stem_path), "-filter_complex", graph, "-map", "[m]",
                         "-ar", str(SR), "-c:a", "pcm_f32le", str(meas_wav)])  # float: no clipping before the limiter
    m = loudness(meas_wav)
    # master: one static gain to -14 LUFS, then a look-ahead limiter at -2 dBFS (AAC adds ~0.5 dB of
    # overs), so the dynamics of the edit (the drop louder than the intro) survive
    gain = min(6.0, (-14.0 - m["I"])) if m and m["I"] > -70 else 0.0
    trim = 0.0
    for attempt in range(2):  # AAC adds overs to limited peaks: measure the encoded file, trim once if needed
        ln = f"volume={gain:.2f}dB,alimiter=limit=0.71:attack=2:release=80:level=false,volume={trim:.2f}dB"
        run(ffmpeg_base() + ["-i", str(video), "-i", str(meas_wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                             "-af", ln + f",aresample={SR}", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                             "-shortest", str(tmp)])
        tp = loudness(tmp).get("TP", -99)
        if tp <= -1.0 or attempt:
            break
        trim = -(tp + 1.3)
    tmp.replace(video)
    meas_wav.unlink(missing_ok=True)
    final = loudness(video)
    report = {k: v for k, v in res.items() if k != "stem"}
    report["master"] = {"target": "-14 LUFS, -1.5 dBTP", **{k: round(v, 2) for k, v in final.items()
                                                             if k in ("I", "TP", "LRA")}}
    report["stem"] = str(stem_path)
    errs = [abs(c["err_ms"]) for c in report["cues"]]
    report["sync"] = {"cues": len(errs), "max_err_ms": max(errs) if errs else 0.0,
                      "warnings": [f"{c['t']:.2f}s {c['role']}: {c['warn']}" for c in report["cues"] if c.get("warn")]}
    dens = _density(report["cues"], float(plan["duration"]))
    report["density_per_10s"] = dens
    srcs = {}
    for c in report["cues"]:
        srcs[c["source"]] = srcs.get(c["source"], 0) + 1
    credits = credit_lines(report["sources"])
    if credits:
        cp = video.with_suffix(".credits.txt")
        cp.write_text("Sound effects:\n" + "\n".join(credits) + "\n")
        report["credits"] = str(cp)
    try:
        mpath = (plan.get("music") or {}).get("path")
        mus = None
        if mpath and Path(mpath).exists():
            mus = work / "music_window.wav"
            run(ffmpeg_base() + ["-ss", f"{float(plan['music'].get('start', 0)):.3f}", "-t",
                                 f"{float(plan['duration']):.3f}", "-i", mpath, str(mus)])
        report["sheet"] = str(sound_sheet(plan, report, mus, res["stem"], video.with_suffix(".sound.jpg")))
    except Exception as e:
        log(f"sound sheet skipped ({e})")
    write_json(video.with_suffix(".sound.json"), report)
    log(f"sound: {len(report['cues'])} effects ({', '.join(f'{n} {s}' for s, n in srcs.items())}), "
        f"{len(report['ambience'])} ambience zone(s); peak density {dens:.1f}/10s; placed within "
        f"{report['sync']['max_err_ms']:.1f} ms; master {final.get('I', 0):.1f} LUFS, {final.get('TP', 0):.1f} dBTP")
    if "synth" in srcs:
        log("  some effects are synthesized stand-ins: run `tripshots sounds --fetch` (or add your own to "
            f"{LIBRARY}) for real recordings")
    for w in report["sync"]["warnings"]:
        log(f"  check: {w}")
    return report


def _density(cues, total) -> float:
    """Designed gestures per 10 s (a run of pops counts once, like in restrain())."""
    firsts = sorted({min(x["t"] for x in cues if x.get("group") == c.get("group")) for c in cues})
    best = 0.0
    for t in firsts:
        n = sum(1 for x in firsts if t <= x <= t + 10)
        best = max(best, n * 10 / min(10, max(1.0, total)))
    return round(best, 1)


def credit_lines(sources: dict) -> list[str]:
    out = []
    for f, s in sources.items():
        lic = str(s.get("license") or "").lower()
        if s.get("source") != "openverse" or lic in ("cc0", "pdm"):
            continue  # no credit needed (still recorded in NAME.sound.json)
        v = f" {s['license_version']}" if s.get("license_version") else ""
        out.append(f'"{s.get("title") or Path(f).stem}" by {s.get("creator") or "unknown"} '
                   f"(CC {lic.upper()}{v}) {s.get('landing') or ''}".strip())
    return out


# ================================================================ prefetch / listing
def prefetch(licenses: str = LICENSES_DEFAULT, ambience: bool = True) -> dict:
    """Fill the cache once (Openverse allows ~200 anonymous searches a day; this uses ~20)."""
    got = {}
    for role in ROLES:
        got[role] = len(fetch_openverse(role, licenses))
        log(f"  {role:<11} {got[role]} take(s)")
    if ambience:
        for z in AMBIENCE:
            got[z] = len(fetch_openverse(z, licenses, want=2, ambience=True))
            log(f"  {z:<11} {got[z]} ambience take(s)")
    es = earshot_takes("whoosh") if _earshot() else []
    if es:
        for role in ROLES:
            earshot_takes(role)
    return got


def status(licenses: str = LICENSES_DEFAULT) -> dict:
    out = {"library": str(LIBRARY), "earshot": bool(_earshot()), "roles": {}, "ambience": {}}
    idx = _index()
    for role in ROLES:
        srcs = {"library": len(library_takes(role)),
                "openverse": len([t for t in idx.get(f"ov:{role}:{licenses}", []) if Path(t["file"]).exists()]),
                "earshot": len(idx.get(f"es:{role}", []))}
        out["roles"][role] = srcs
    for z in AMBIENCE:
        out["ambience"][z] = {"library": len(library_takes(z)),
                              "openverse": len(idx.get(f"ov:{z}:{licenses}", []))}
    return out


def listen(video: Path) -> dict:
    """earshot's listening pass (needs earshot with its models: `./install.sh --sound-ears`)."""
    py = os.environ.get("EARSHOT_PY") or shutil.which("python3")
    out = video.with_suffix(".listen.json")
    try:
        p = subprocess.run([py, "-m", "earshot", "timeline", str(video), "--json", "--out", str(out)],
                           capture_output=True, text=True, timeout=1800)
    except Exception as e:
        raise ReelError(f"earshot could not run: {e}")
    if p.returncode != 0 or not out.exists():
        raise ReelError("earshot's listening models are not installed (`./install.sh --sound-ears`, ~1.1 GB "
                        f"on first use): {p.stderr.strip()[-300:]}")
    return {"timeline": str(out), "summary": p.stdout.strip()[-1500:]}


def sound_sheet(plan: dict, report: dict, music_wav: Path | None, stem: np.ndarray, out: Path) -> Path:
    """One picture of the sound against the edit: beat grid, cuts, music and effects waveforms, cues."""
    from PIL import Image, ImageDraw
    from .text import load_font
    total = float(plan["duration"])
    W, H = 1800, 520
    x0, x1 = 60, W - 20
    img = Image.new("RGB", (W, H), (18, 18, 20))
    d = ImageDraw.Draw(img)
    f = load_font(15, "regular")
    fb = load_font(18, "bold")

    def X(t):
        return x0 + (x1 - x0) * t / max(total, 0.01)

    def wave(sig, top, h, col):
        if sig is None or not len(sig):
            return
        m = np.abs(sig).max(axis=1) if sig.ndim == 2 else np.abs(sig)
        cols = x1 - x0
        per = max(1, len(m) // cols)
        env = m[: per * cols].reshape(cols, per).max(axis=1)
        env = env / max(1e-6, float(np.abs(m).max()))
        mid = top + h // 2
        for i, v in enumerate(env):
            d.line([(x0 + i, mid - v * h / 2), (x0 + i, mid + v * h / 2)], fill=col)
    for b in plan.get("beats") or []:
        if 0 <= b <= total:
            d.line([(X(b), 40), (X(b), H - 30)], fill=(44, 44, 52))
    for s in plan["segments"][1:]:
        d.line([(X(s["out_start"]), 40), (X(s["out_start"]), H - 30)], fill=(120, 120, 130), width=2)
    d.text((8, 60), "music", font=f, fill=(150, 150, 160))
    d.text((8, 250), "effects", font=f, fill=(150, 150, 160))
    if music_wav and Path(music_wav).exists():
        try:
            wave(decode(Path(music_wav))[: int(total * SR)], 50, 150, (90, 140, 200))
        except Exception:
            pass
    wave(stem[: int(total * SR)], 230, 150, (240, 190, 60))
    colors = {"impact": (255, 80, 80), "riser": (255, 140, 60), "whoosh": (120, 220, 255), "whoosh_big": (80, 180, 255),
              "pop": (255, 220, 90), "tick": (200, 200, 200), "glitch": (200, 120, 255), "shutter": (255, 255, 255)}
    for k, c in enumerate(report.get("cues", [])):
        x = X(c["t"])
        col = colors.get(c["role"], (255, 255, 255))
        d.line([(x, 220), (x, 390)], fill=col, width=2)
        d.text((x + 3, 395 + (k % 4) * 18), c["role"], font=f, fill=col)
    for a in report.get("ambience", []):
        own = a.get("source") == "clip"  # the clip's own sound: amber; library beds: green
        d.rectangle([X(a["from"]), H - 28, X(a["to"]) - 2, H - 12], fill=(110, 80, 20) if own else (40, 90, 70))
        d.text((X(a["from"]) + 4, H - 29), "own sound" if own else a["zone"], font=f,
               fill=(255, 230, 170) if own else (200, 255, 220))
    m = report.get("master", {})
    d.text((x0, 10), f"sound design · {len(report.get('cues', []))} effects · beats (dark) · cuts (grey) · "
                     f"master {m.get('I', '?')} LUFS / {m.get('TP', '?')} dBTP", font=fb, fill=(255, 214, 0))
    img.save(out, "JPEG", quality=88)
    return out
