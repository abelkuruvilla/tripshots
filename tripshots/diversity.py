"""Which shots are really the same moment, and how alike two pictures look.

A reel shouldn't show the same view twice: two photos a few seconds apart, the clip and the photo taken at the
same spot, or two chunks of one clip. `scene_groups` puts such shots in one group (so a reel uses one of
them), and `look` / `look_similarity` compare the light and colour of two pictures (used to match a reference
reel's mood: golden hour to golden hour, not to a blue midday sky).

Everything works from the shot thumbnails, so it is quick and needs no AI.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from functools import lru_cache

import cv2
import numpy as np


@lru_cache(maxsize=8192)
def _thumb(path: str) -> np.ndarray | None:
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    s = 160 / max(h, w)
    return cv2.cvtColor(cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_BGR2RGB)


def _dhash(rgb: np.ndarray) -> int:
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def _hist(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
    return h / max(1e-6, h.sum())


def look(rgb: np.ndarray) -> np.ndarray:
    """Light and colour of a picture: brightness, contrast, warmth (b*), tint (a*), colourfulness, share of
    highlights and shadows, plus a coarse hue histogram."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[..., 0] / 255.0, (lab[..., 1] - 128) / 64.0, (lab[..., 2] - 128) / 64.0
    C = np.hypot(a, b)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hh = cv2.calcHist([hsv], [0], (hsv[..., 1] > 50).astype(np.uint8), [9], [0, 180]).flatten()
    hh = hh / max(1e-6, hh.sum())
    return np.r_[L.mean(), L.std(), b.mean(), a.mean(), C.mean(), (L > 0.85).mean(), (L < 0.15).mean(), hh]


def look_similarity(u: np.ndarray, v: np.ndarray) -> float:
    """0..1: how alike two pictures' light and colour are."""
    w = np.r_[3.0, 2.0, 3.0, 1.5, 2.0, 1.5, 1.5, np.full(9, 0.8)]
    d = float(np.sqrt(np.sum(w * (u - v) ** 2)))
    return math.exp(-2.2 * d)


def thumb_look(path: str | None) -> np.ndarray | None:
    t = _thumb(str(path)) if path else None
    return look(t) if t is not None else None


def _when(s: dict) -> float | None:
    c = s.get("created")
    if not c:
        return None
    c = str(c).split(";")[-1].strip()      # "UTC;local" from some drones (files read before media._norm_time knew)
    try:
        return datetime.fromisoformat(c.replace("Z", "+00:00")).replace(tzinfo=None).timestamp()
    except ValueError:
        return None


def _metres(ga, gb) -> float:
    dy = (ga[0] - gb[0]) * 111_000
    dx = (ga[1] - gb[1]) * 111_000 * math.cos(math.radians(ga[0]))
    return math.hypot(dx, dy)


def _far(a: dict, b: dict, metres: float = 400) -> bool:
    ga, gb = a.get("gps"), b.get("gps")
    return bool(ga and gb) and _metres(ga, gb) > metres


def _fixer(timed: list[tuple]):
    """where(t, shot) -> [lat, lon] or None: the shot's own GPS, else the fix of the picture taken closest in
    time (within 40 minutes). `timed`: (time, id, shot) for every shot with a time."""
    import bisect
    fixes = [(t, s["gps"]) for t, _, s in timed if s.get("gps")]
    ft = [t for t, _ in fixes]

    def where(t, s):
        if s.get("gps"):
            return s["gps"]
        k = bisect.bisect_left(ft, t)
        best = min((fixes[i] for i in (k - 1, k) if 0 <= i < len(fixes)), key=lambda f: abs(f[0] - t), default=None)
        return best[1] if best and abs(best[0] - t) <= 2400 else None
    return where


def positions(shots: list[dict]) -> dict[str, list]:
    """{shot id: [lat, lon]} for every shot whose position is known: its own GPS, or (a drone, a camera
    without GPS) the phone picture taken closest in time."""
    timed = sorted(((t, s["id"], s) for s in shots if (t := _when(s)) is not None), key=lambda x: x[:2])
    where = _fixer(timed)
    out = {s["id"]: s["gps"] for s in shots if s.get("gps")}
    for t, sid, s in timed:
        if sid not in out and (g := where(t, s)):
            out[sid] = g
    return out


def sessions(shots: list[dict], gap: float = 900.0, near: float = 1200.0) -> dict[str, str]:
    """{shot id: stop id}: one stop of the trip, whatever the angle or the camera. A reel that shows the
    same headland three times in a row looks like it ran out of places, even when each shot is good.

    Shots filmed one after another with no pause longer than `gap` seconds are one stop; a drone or camera
    without GPS borrows the position of the phone picture taken closest in time (within 40 minutes), and
    stops within `near` metres and four hours of each other are the same place (a long visit with breaks).
    Chunks of one clip always share a stop; shots without a time are their own."""
    timed = sorted(((t, s["id"], s) for s in shots if (t := _when(s)) is not None), key=lambda x: x[:2])
    where = _fixer(timed)

    out: dict[str, str] = {}
    by_src: dict[str, str] = {}
    stops: dict[str, dict] = {}       # stop id -> {t0, t1, pts}
    cur, last_t, last_g = None, 0.0, None
    for t, sid, s in timed:
        src = str(s.get("src") or sid)
        if src in by_src:
            out[sid] = by_src[src]
            continue
        g = where(t, s)
        if cur is None or t - last_t > gap or (g and last_g and _metres(g, last_g) > 1500):
            cur = sid
            stops[cur] = {"t0": t, "t1": t, "pts": []}
        out[sid] = by_src[src] = cur
        end = t + (float(s.get("t1") or 0) if s.get("kind") == "video" else 0.0)
        stops[cur]["t1"] = max(stops[cur]["t1"], end)
        if g:
            stops[cur]["pts"].append(g)
            last_g = g
        last_t = max(last_t, end) if cur != sid else end
    # a long visit with breaks: stops close in place and time are one
    parent = {k: k for k in stops}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    keys = sorted(stops, key=lambda k: stops[k]["t0"])
    mid = {k: (float(np.mean([p[0] for p in v["pts"]])), float(np.mean([p[1] for p in v["pts"]])))
           for k, v in stops.items() if v["pts"]}
    for i, a in enumerate(keys):
        if a not in mid:
            continue
        for b in keys[i + 1:]:
            if stops[b]["t0"] - stops[a]["t1"] > 4 * 3600:
                break
            if b in mid and _metres(mid[a], mid[b]) <= near:
                parent[find(b)] = find(a)
    out = {k: find(v) for k, v in out.items()}
    by_src = {k: find(v) for k, v in by_src.items()}
    for s in shots:
        if s["id"] not in out:
            src = str(s.get("src") or s["id"])
            out[s["id"]] = by_src.setdefault(src, s["id"])
    return out


def place_name(shot: dict) -> str | None:
    """The landmark the AI recognised, as a key: "Half Dome, Yosemite" and "Half Dome (Glacier Point)" are one."""
    lm = (shot.get("ai") or {}).get("landmark")
    if not lm or str(lm).lower() in ("none", "null", "unknown"):
        return None
    name = re.split(r"[,(/;]| - ", str(lm))[0].lower().replace("'", "").replace("\u2019", "")
    name = re.sub(r"[^\w ]+", " ", name)
    name = re.sub(r" (national|state) (park|monument|forest|seashore)$", "", " ".join(name.split()))
    return " ".join(w for w in name.split() if w != "the") or None


def place_keys(shots: list[dict]) -> dict[str, str]:
    """{shot id: place}: where a shot was taken, for variety. A recognised landmark is the place wherever and
    whenever it was filmed (two visits, the drone and the phone); the rest go by the stop of the trip
    (`sessions`). A stop whose named shots mostly agree gives that name to its unnamed ones."""
    stops = sessions(shots)
    named = {s["id"]: n for s in shots if (n := place_name(s))}
    votes: dict[str, Counter] = {}
    for sid, n in named.items():
        votes.setdefault(stops[sid], Counter())[n] += 1
    lead = {}
    for stop, c in votes.items():
        n, k = c.most_common(1)[0]
        if k * 2 > sum(c.values()) or len(c) == 1:
            lead[stop] = n
    out = {}
    for s in shots:
        sid = s["id"]
        n = named.get(sid) or lead.get(stops[sid])
        out[sid] = f"at:{n}" if n else f"stop:{stops[sid]}"
    return out


_BAKED = re.compile(r"\b(text overlay|title overlay|overlay text|caption|subtitle|watermark|screenshot|"
                    r"screen recording|logo overlay)s?\b")


def baked_text(shot: dict) -> bool:
    """True for a picture that already carries titles, captions or a watermark (an edited export, a reel saved
    back to the camera roll): another title on top of it looks like a mistake."""
    a = shot.get("ai") or {}
    if "burned-in-text" in (a.get("issues") or []):
        return True
    return bool(_BAKED.search(" | ".join(str(t).lower() for t in [*(a.get("tags") or [])[:12], a.get("note") or ""])))


def same_scene(a: dict, b: dict, fa=None, fb=None) -> bool:
    """True when two shots show the same view of the same moment."""
    aa, ab = a.get("ai") or {}, b.get("ai") or {}
    if aa.get("duplicate_of") == b["id"] or ab.get("duplicate_of") == a["id"]:
        return True
    if a.get("sig") and a.get("sig") == b.get("sig"):  # chunks of one clip
        return abs(float(a.get("t0") or 0) - float(b.get("t0") or 0)) < 30
    if _far(a, b):
        return False
    fa = fa or _feat(a)
    fb = fb or _feat(b)
    if fa is None or fb is None:
        return False
    bits = bin(fa[0] ^ fb[0]).count("1")
    corr = float(cv2.compareHist(fa[1].astype(np.float32), fb[1].astype(np.float32), cv2.HISTCMP_CORREL))
    ta, tb = _when(a), _when(b)
    close = ta is not None and tb is not None and abs(ta - tb) <= 600
    if bits <= 8 and corr > 0.8:
        return True                   # the same picture (re-export, burst), whenever it was taken
    if close and (bits <= 18 or (bits <= 26 and corr > 0.85)):
        return True                   # taken minutes apart, looking the same: one moment
    return False


def _feat(s: dict):
    t = _thumb(str(s.get("thumb"))) if s.get("thumb") else None
    if t is None:
        return None
    return _dhash(t), _hist(t)


def scene_groups(shots: list[dict]) -> dict[str, str]:
    """{shot id: group id}; shots of one moment share a group (the group id is one of its shots).
    Compares only pairs that can match (same clip, taken within 10 minutes, or sharing part of their
    picture hash), so thousands of shots take a moment."""
    by_id = {s["id"]: s for s in shots}
    feats = {s["id"]: _feat(s) for s in shots}
    parent = {k: k for k in by_id}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def test(a, b):
        if find(a) != find(b) and same_scene(by_id[a], by_id[b], feats[a], feats[b]):
            union(a, b)
    for s in shots:  # the AI said so
        d = (s.get("ai") or {}).get("duplicate_of")
        if d in by_id:
            union(d, s["id"])
    timed = sorted((t, s["id"]) for s in shots if (t := _when(s)) is not None)
    for i, (ta, a) in enumerate(timed):  # taken within 10 minutes of each other
        for tb, b in timed[i + 1:]:
            if tb - ta > 600:
                break
            test(a, b)
    clips: dict[str, list] = {}
    for s in shots:  # chunks of one clip
        if s.get("sig") and s.get("kind") == "video":
            clips.setdefault(s["sig"], []).append(s["id"])
    for ids in clips.values():
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                test(a, b)
    bands: dict[tuple, list] = {}  # the same picture at any time: <= 8 differing bits leave one of 9 bands equal
    for k, f in feats.items():
        if f is not None:
            for j in range(9):
                bands.setdefault((j, (f[0] >> (j * 7)) & 0x7F), []).append(k)
    for ids in bands.values():
        if len(ids) > 60:  # a flat band (sky, black frames): too common to tell anything
            continue
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if bin(feats[a][0] ^ feats[b][0]).count("1") <= 8:
                    test(a, b)
    return {k: find(k) for k in parent}
