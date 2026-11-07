"""Who is in each photo and clip, recognised on this computer (nothing is uploaded).

Models (OpenCV's own face models, downloaded once into ~/.tripshots/models, checked by SHA-256):
  YuNet face detector (BSD-3 / MIT, 230 KB) and SFace face embeddings (Apache-2.0, 37 MB).

- `enroll("me", photos)` teaches a person from a few photos of them (the largest face in each).
- `discover(records)` groups the faces nobody has named yet into clusters and draws a sheet, so you
  (or the agent, asking you) can say "cluster 3 is Mom" -> `name_cluster("c3", "mom")`.
- `who_is_in(records)` -> {path: [names]}; faces are computed once per file (by content) and cached.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from . import library as lib
from .config import HOME
from .util import ReelError, ffmpeg_base, log, read_json, write_json

MODEL_DIR = HOME / "models"
FACE_DIR = lib.LIB_DIR / "faces"
PEOPLE = HOME / "people" / "people.json"
CLUSTERS = HOME / "people" / "clusters.json"
FACES_VERSION = 1

MODELS = {
    "yunet": {
        "file": "face_detection_yunet_2023mar.onnx", "size": 232589,
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "urls": [  # the same bytes are published in both places
            "https://raw.githubusercontent.com/ShiqiYu/libfacedetection.train/master/onnx/yunet_s_640_640.onnx",
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
            "face_detection_yunet_2023mar.onnx",
        ]},
    "sface": {
        "file": "face_recognition_sface_2021dec.onnx", "size": 38696353,
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "urls": [
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/"
            "face_recognition_sface_2021dec.onnx",
            "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx",
        ]},
}
MATCH = 0.40       # cosine similarity for "same person" (SFace's own threshold is 0.363; a bit stricter)
CLUSTER = 0.45     # stricter still when grouping strangers
MIN_FACE = 40      # px (in the analysed image): smaller faces are too blurry to recognise reliably
ME = {"me", "i", "myself", "self", "you"}

_tls = threading.local()
_lock = threading.Lock()


# ------------------------------------------------------------------ models
def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def model_path(name: str) -> Path:
    m = MODELS[name]
    p = MODEL_DIR / m["file"]
    if p.exists() and p.stat().st_size == m["size"]:
        return p
    with _lock:
        if p.exists() and p.stat().st_size == m["size"]:
            return p
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        errs = []
        for url in m["urls"]:
            tmp = p.with_suffix(".part")
            try:
                log(f"downloading face model {m['file']} ({m['size'] / 1e6:.1f} MB, once)")
                req = urllib.request.Request(url, headers={"User-Agent": "tripshots"})
                with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
                if _sha(tmp) != m["sha256"]:
                    raise ValueError("checksum mismatch")
                tmp.replace(p)
                return p
            except Exception as e:
                errs.append(f"{url.split('/')[2]}: {e}")
                tmp.unlink(missing_ok=True)
        raise ReelError(f"could not download {m['file']} ({'; '.join(errs)}). Put the file in {MODEL_DIR} by hand")


def available() -> tuple[bool, str]:
    ok = all((MODEL_DIR / m["file"]).exists() for m in MODELS.values())
    return ok, "face models ready" if ok else "face models download on first use (38 MB)"


def _nets():
    if not hasattr(_tls, "det"):
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass
        _tls.det = cv2.FaceDetectorYN.create(str(model_path("yunet")), "", (640, 640), 0.8, 0.3, 50)
        _tls.rec = cv2.FaceRecognizerSF.create(str(model_path("sface")), "")
    return _tls.det, _tls.rec


# ------------------------------------------------------------------ faces in one image / file
def faces_in_image(bgr: np.ndarray, max_side: int = 1600) -> list[dict]:
    det, rec = _nets()
    h, w = bgr.shape[:2]
    s = min(1.0, max_side / max(h, w))
    img = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr
    det.setInputSize((img.shape[1], img.shape[0]))
    _, rows = det.detect(img)
    out = []
    for f in rows if rows is not None else []:
        if min(f[2], f[3]) < MIN_FACE:
            continue
        crop = rec.alignCrop(img, f)
        e = rec.feature(crop).flatten().astype(np.float32)
        e /= np.linalg.norm(e) + 1e-9
        H, W = img.shape[:2]
        out.append({"box": [round(float(f[0]) / W, 4), round(float(f[1]) / H, 4),
                            round(float(f[2]) / W, 4), round(float(f[3]) / H, 4)],
                    "score": round(float(f[14]), 3), "px": int(min(f[2], f[3])),
                    "emb": [round(float(x), 5) for x in e]})
    return out


def _video_frames(path: str, duration: float, n: int = 4) -> list[tuple[float, np.ndarray]]:
    frames = []
    for k in range(n):
        t = duration * (k + 0.5) / n
        p = subprocess.run(ffmpeg_base() + ["-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                                            "-vf", "scale='min(1600,iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True)
        if p.returncode == 0 and p.stdout:
            img = cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                frames.append((round(t, 2), img))
    return frames


def faces_in(rec: dict) -> list[dict]:
    """Faces in a catalog record (photo or video), cached by file content."""
    sig = rec.get("sig")
    cache = FACE_DIR / f"{sig}.json" if sig else None
    if cache and cache.exists():
        d = read_json(cache, {}) or {}
        if d.get("v") == FACES_VERSION:
            return d["faces"]
    faces = []
    if rec["kind"] == "photo":
        src = rec.get("still") or rec["path"]
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is not None:
            faces = faces_in_image(img)
    else:
        for t, img in _video_frames(rec["path"], float(rec.get("duration") or 2)):
            for f in faces_in_image(img):
                f["t"] = t
                faces.append(f)
    if cache:
        FACE_DIR.mkdir(parents=True, exist_ok=True)
        write_json(cache, {"v": FACES_VERSION, "faces": faces})
    return faces


def index(recs: list[dict], workers: int = 4) -> dict[str, list[dict]]:
    """Faces for many files (cached ones are instant). {path: faces}."""
    todo = [r for r in recs if not (r.get("sig") and (FACE_DIR / f"{r['sig']}.json").exists())]
    if todo:
        log(f"looking for faces in {len(todo)} new file(s) (on this computer, once per file)...")
        model_path("yunet"), model_path("sface")
    out: dict[str, list[dict]] = {}
    done = [0]

    def one(r):
        try:
            out[r["path"]] = faces_in(r)
        except Exception as e:
            log(f"faces: skipped {Path(r['path']).name}: {e}")
            out[r["path"]] = []
        done[0] += 1
        if todo and done[0] % 50 == 0:
            log(f"  faces: {done[0]}/{len(recs)}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, recs))
    return out


# ------------------------------------------------------------------ people
def _load() -> dict:
    return read_json(PEOPLE, {}) or {}


def _save(d: dict) -> None:
    PEOPLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(PEOPLE, d)


def canonical(name: str) -> str:
    n = name.strip().lower()
    if n in ME:
        return "me"
    for key, p in _load().items():
        if n == key or n in [a.lower() for a in p.get("aliases", [])]:
            return key
    return n


def known(name: str) -> bool:
    return canonical(name) in _load()


def list_people() -> list[dict]:
    return [{"name": k, "aliases": v.get("aliases", []), "faces": len(v.get("embs", [])),
             "from": v.get("from", [])[:5]} for k, v in sorted(_load().items())]


def _add(name: str, embs: list, source: list[str], aliases: list[str] | None = None) -> dict:
    d = _load()
    key = canonical(name)
    p = d.setdefault(key, {"aliases": [], "embs": [], "from": []})
    for a in aliases or []:
        if a.lower() != key and a.lower() not in p["aliases"]:
            p["aliases"].append(a.lower())
    p["embs"] = (p["embs"] + embs)[-60:]
    p["from"] = (p["from"] + source)[-20:]
    _save(d)
    return {"name": key, "faces": len(p["embs"]), "aliases": p["aliases"]}


def enroll(name: str, photos: list[str], aliases: list[str] | None = None) -> dict:
    """Teach a person from photos of them: the largest face in each picture (a selfie, a portrait)."""
    from .catalog import records
    embs, used, skipped = [], [], []
    paths = [Path(p).expanduser() for p in photos]
    recs = records(paths) if paths else []
    for r in recs:
        faces = faces_in(r)
        if not faces:
            skipped.append(f"{Path(r['path']).name}: no clear face")
            continue
        big = max(faces, key=lambda f: f["px"])
        if len(faces) > 1 and sorted(f["px"] for f in faces)[-2] > 0.8 * big["px"]:
            skipped.append(f"{Path(r['path']).name}: {len(faces)} faces of similar size, unclear which one")
            continue
        embs.append(big["emb"])
        used.append(Path(r["path"]).name)
    if not embs:
        raise ReelError("no usable face in those photos: use 2-5 photos where this person's face is the largest")
    res = _add(name, embs, used, aliases)
    res.update({"used": used, "skipped": skipped})
    if len(embs) < 3:
        res["tip"] = "3-5 photos (different days, light, angles) make recognition much more reliable"
    return res


def forget(name: str) -> bool:
    d = _load()
    k = canonical(name)
    if k in d:
        del d[k]
        _save(d)
        return True
    return False


def _gallery() -> tuple[list[str], np.ndarray | None]:
    names, embs = [], []
    for k, p in _load().items():
        for e in p.get("embs", []):
            names.append(k)
            embs.append(e)
    return names, (np.array(embs, np.float32) if embs else None)


def identify(faces: list[dict]) -> list[tuple[str, float]]:
    """Best named person for each face (or ('', score) when nobody matches)."""
    names, G = _gallery()
    out = []
    for f in faces:
        if G is None:
            out.append(("", 0.0))
            continue
        sims = G @ np.array(f["emb"], np.float32)
        best = {}
        for n, s in zip(names, sims):
            best[n] = max(best.get(n, -1), float(s))
        n, s = max(best.items(), key=lambda kv: kv[1])
        out.append((n, s) if s >= MATCH else ("", s))
    return out


def who_is_in(recs: list[dict]) -> dict[str, list[str]]:
    faces = index(recs)
    out = {}
    for path, fs in faces.items():
        out[path] = sorted({n for n, _ in identify(fs) if n})
    return out


# ------------------------------------------------------------------ discover unknown faces
def discover(recs: list[dict], min_files: int = 2, max_clusters: int = 16) -> dict:
    """Cluster faces nobody is named for; save clusters + a sheet of example crops per cluster."""
    allf = index(recs)
    by_path = {r["path"]: r for r in recs}
    items = []
    for path, fs in allf.items():
        for f, (n, _) in zip(fs, identify(fs)):
            if not n:
                items.append((path, f))
    items.sort(key=lambda it: -it[1]["px"])
    clusters: list[dict] = []
    for path, f in items:
        e = np.array(f["emb"], np.float32)
        best, bs = None, CLUSTER
        for c in clusters:
            s = float(c["centre"] @ e)
            if s > bs:
                best, bs = c, s
        if best is None:
            clusters.append({"centre": e, "members": [(path, f)]})
        else:
            best["members"].append((path, f))
            m = best["centre"] * (len(best["members"]) - 1) + e
            best["centre"] = m / (np.linalg.norm(m) + 1e-9)
    keep = [c for c in clusters if len({p for p, _ in c["members"]}) >= min_files]
    keep.sort(key=lambda c: -len({p for p, _ in c["members"]}))
    keep = keep[:max_clusters]
    saved = {}
    for i, c in enumerate(keep, 1):
        files = sorted({p for p, _ in c["members"]})
        saved[f"c{i}"] = {"files": files, "count": len(files),
                          "embs": [f["emb"] for _, f in c["members"][:40]],
                          "examples": [{"path": p, "box": f["box"], "t": f.get("t"),
                                        "still": by_path.get(p, {}).get("still"),
                                        "kind": by_path.get(p, {}).get("kind")} for p, f in c["members"][:8]]}
    CLUSTERS.parent.mkdir(parents=True, exist_ok=True)
    write_json(CLUSTERS, saved)
    sheet = cluster_sheet(saved) if saved else None
    return {"clusters": [{"id": k, "files": v["count"]} for k, v in saved.items()],
            "sheet": str(sheet) if sheet else None, "unnamed_faces": len(items),
            "next": "name a cluster: `tripshots people name c1 me` (or mom, alex, ...)"}


def _crop(ex: dict, size: int = 120):
    from PIL import Image
    try:
        if ex.get("kind") == "video":
            p = subprocess.run(ffmpeg_base() + ["-ss", f"{ex.get('t') or 0:.2f}", "-i", ex["path"], "-frames:v", "1",
                                                "-vf", "scale='min(1600,iw)':-2", "-f", "image2pipe", "-vcodec", "png",
                                                "-"], capture_output=True)
            import io
            im = Image.open(io.BytesIO(p.stdout)).convert("RGB")
        else:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(Image.open(ex.get("still") or ex["path"])).convert("RGB")
        x, y, w, h = ex["box"]
        W, H = im.size
        cx, cy, r = (x + w / 2) * W, (y + h / 2) * H, max(w * W, h * H) * 0.8
        im = im.crop((int(cx - r), int(cy - r), int(cx + r), int(cy + r))).resize((size, size))
        return im
    except Exception:
        return None


def cluster_sheet(saved: dict, out: Path | None = None) -> Path:
    from PIL import Image, ImageDraw
    rows = list(saved.items())
    cell, per = 120, 8
    sheet = Image.new("RGB", (90 + per * (cell + 6), len(rows) * (cell + 10) + 10), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    for i, (cid, c) in enumerate(rows):
        y = 10 + i * (cell + 10)
        d.text((10, y + cell // 2 - 14), f"{cid}", fill=(255, 214, 0))
        d.text((10, y + cell // 2 + 2), f"{c['count']} files", fill=(200, 200, 200))
        for j, ex in enumerate(c["examples"][:per]):
            im = _crop(ex, cell)
            if im:
                sheet.paste(im, (90 + j * (cell + 6), y))
    out = out or CLUSTERS.with_suffix(".jpg")
    sheet.save(out, "JPEG", quality=88)
    return out


def name_cluster(cid: str, name: str) -> dict:
    saved = read_json(CLUSTERS, {}) or {}
    c = saved.get(cid)
    if not c:
        raise ReelError(f"no cluster {cid}: run `tripshots people discover` first")
    res = _add(name, c["embs"], [f"cluster {cid}"])
    res["files"] = c["count"]
    return res
