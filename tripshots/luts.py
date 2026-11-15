"""A library of creative LUTs used as looks: any .cube or HaldCLUT .png, from a file, a folder, a zip or a URL, and a
few free packs that can be fetched on request (never bundled: their authors don't state a licence for
redistributing them, so each user downloads them for their own reels).

Each LUT becomes a look (~/.tripshots/looks/<name>.json with `cube`, `pack`, `source`, `licence`, `profile`): the
grade first balances every shot (exposure, cast, tones, so shots match), then the LUT is applied on top at the
look's strength, with skin kept closer to its own colour (grade.build_transform). Every LUT is measured on test
colours (`profile`): how it moves contrast, tints shadows and highlights, and saturation. That gives it a plain
description, lets the AI pick it, and spots LUTs made for log footage (a huge contrast jump on normal video), which
are never picked automatically.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from .config import HOME
from .grade import GRID, LOOKS_DIR, read_cube, read_hald, sample_lut, write_cube
from .util import ReelError, log

LIB = HOME / "looks" / "lib"
UA = "Mozilla/5.0 (tripshots looks)"
MAX_DOWNLOAD = 600 * 1024 * 1024

PACKS: dict[str, dict] = {
    "gmic-creative": {
        "title": "Creative pack",
        "by": "G'MIC / RawTherapee",
        "url": "https://gmic.eu/color_presets/creative/creative_cube.zip",
        "size_mb": 2,
        "about": "33 creative looks: bleach bypass, teal and orange, late sunset, fall colours, crisp winter, "
                 "moonlight, candlelight, foggy night and more",
        "home": "https://gmic.eu/color_presets/",
        "licence": "Free download from gmic.eu; no licence for the LUT files is stated. Fine for your own reels; "
                   "check with the authors before sharing the files themselves",
    },
    "film-simulation": {
        "title": "Film simulation collection",
        "by": "RawTherapee",
        "url": "https://rawtherapee.com/shared/HaldCLUT.zip",
        "size_mb": 420,
        "about": "About 300 emulations of colour and black-and-white film stocks (negative, slide, instant, print)",
        "home": "https://rawtherapee.com",
        "licence": "Free download from rawtherapee.com; no licence for the LUT files is stated. Film names are "
                   "their makers' trademarks, used only to say what each one imitates",
    },
}

# readable names for the creative pack's files
TITLES = {
    "anime": "Anime", "bleachbypass": "Bleach bypass", "candlelight": "Candlelight", "colornegative": "Colour negative",
    "crispwarm": "Crisp warm", "crispwinter": "Crisp winter", "dropblues": "Drop blues", "edgyember": "Edgy ember",
    "fallcolors": "Fall colours", "foggynight": "Foggy night", "futuristicbleak": "Futuristic bleak",
    "horrorblue": "Horror blue", "latesunset": "Late sunset", "moonlight": "Moonlight", "nightfromday": "Night from day",
    "redblueyellow": "Red blue yellow", "smokey": "Smoky", "softwarming": "Soft warming",
    "tealmagentagold": "Teal magenta gold", "tealorange": "Teal and orange", "tensiongreen": "Tension green",
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "lut"


def title_of(stem: str) -> str:
    m = re.fullmatch(r"([a-z]+)_?(\d*)", stem.lower())
    if m and m.group(1) in TITLES:
        return TITLES[m.group(1)] + (f" {m.group(2)}" if m.group(2) else "")
    return re.sub(r"[_\-]+", " ", stem).strip().capitalize()


# ------------------------------------------------------------------ reading and measuring
def load_table(path: Path) -> np.ndarray:
    """A 3D LUT file as a table; ValueError for anything else (1D LUTs, broken files)."""
    if path.suffix.lower() == ".cube":
        txt = path.read_text(errors="ignore")
        if "LUT_3D_SIZE" not in txt:
            raise ValueError("not a 3D LUT")
        size = int(re.search(r"LUT_3D_SIZE\s+(\d+)", txt).group(1))
        if not 2 <= size <= 129:
            raise ValueError(f"unusual size {size}")
        t = read_cube(path)
    elif path.suffix.lower() in (".png", ".tif", ".tiff"):
        t = read_hald(path)
    else:
        raise ValueError("not a .cube or HaldCLUT image")
    if not np.isfinite(t).all():
        raise ValueError("broken values")
    return np.clip(t, 0, 1).astype(np.float32)


def profile(table: np.ndarray) -> dict:
    """What a LUT does to ordinary video: contrast and black/white points on a grey ramp, the tint it adds to
    shadows, mid-tones and highlights, and how much it changes saturation on everyday colours."""
    import cv2
    ramp = np.linspace(0, 1, 33, dtype=np.float32)
    grey = np.stack([ramp] * 3, -1)
    out = sample_lut(table, grey)
    lab_in = cv2.cvtColor(grey.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    lab = cv2.cvtColor(out.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    L = lab[:, 0]
    mid = slice(12, 21)
    slope = float(np.polyfit(lab_in[mid, 0], L[mid], 1)[0])
    tint = lambda sl: [round(float(lab[sl, 1].mean()), 1), round(float(lab[sl, 2].mean()), 1)]
    # everyday colours: sky, foliage, skin, sand, water, red, at three brightnesses
    base = np.array([[0.35, 0.55, 0.85], [0.25, 0.45, 0.2], [0.85, 0.62, 0.5], [0.85, 0.75, 0.55],
                     [0.15, 0.45, 0.55], [0.7, 0.15, 0.12]], np.float32)
    swatch = np.concatenate([base * k for k in (0.5, 0.8, 1.0)])
    c_in = cv2.cvtColor(swatch.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    c_out = cv2.cvtColor(sample_lut(table, swatch).reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    sat = float(np.mean(np.hypot(c_out[:, 1], c_out[:, 2])) / max(1e-3, np.mean(np.hypot(c_in[:, 1], c_in[:, 2]))))
    return {"contrast": round(slope, 2), "black": round(float(L[0]), 1), "white": round(float(L[-1]), 1),
            "shadows": tint(slice(3, 10)), "mids": tint(mid), "highlights": tint(slice(24, 31)),
            "saturation": round(sat, 2), "mono": bool(np.mean(np.hypot(c_out[:, 1], c_out[:, 2])) < 3),
            "log_input": slope > 2.2 and L[16] - L[8] > 30,   # made for flat log footage, not normal video
            "inverts": slope < 0}                             # a negative: light becomes dark


def describe(p: dict) -> str:
    """A LUT's profile in a few plain words."""
    words = []
    if p.get("log_input"):
        return "Made for log (flat) footage: turns a camera's log picture into normal contrast"
    if p.get("inverts"):
        return "Inverts the picture like a film negative: an effect, not a grade"
    if p.get("mono"):
        words.append("black and white")
    c = p["contrast"]
    words.append("punchy contrast" if c > 1.25 else "soft, low contrast" if c < 0.85 else "")
    if p["black"] > 8:
        words.append("lifted, faded blacks")
    s = p["saturation"]
    if not p.get("mono"):
        words.append("rich colour" if s > 1.2 else "muted colour" if s < 0.8 else "")

    def hue(ab):
        a, b = ab
        if abs(a) + abs(b) < 3:
            return ""
        if b > 3 and a > 1:
            return "warm"
        if b > 3:
            return "golden"
        if b < -3 and a < -1:
            return "teal"
        if b < -3:
            return "cool blue"
        return "green" if a < -3 else "magenta" if a > 3 else ""
    sh, hi = hue(p["shadows"]), hue(p["highlights"])
    if sh and hi and sh != hi:
        words.append(f"{sh} shadows, {hi} highlights")
    elif sh or hi:
        words.append(f"{sh or hi} cast")
    text = ", ".join(w for w in words if w)
    return (text[0].upper() + text[1:]) if text else "A gentle, mostly neutral look"


# ------------------------------------------------------------------ importing
def _store(table: np.ndarray, pack: str, name: str) -> Path:
    d = LIB / slug(pack)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{slug(name)}.cube"
    if table.shape[0] == GRID:
        write_cube(lambda rgb: sample_lut(table, rgb), out)
    else:
        write_cube(lambda rgb: sample_lut(table, rgb), out, size=min(GRID, max(17, table.shape[0])))
    return out


def add_table(table: np.ndarray, title: str, pack: str, source: str, licence: str = "") -> dict:
    prof = profile(table)
    cube = _store(table, pack, title)
    name = slug(f"{pack}-{title}") if pack != "yours" else slug(title)
    look = {"desc": describe(prof), "title": title, "cube": str(cube), "pack": pack, "source": source,
            "licence": licence, "profile": prof, "vignette": False, "grain": 0}
    LOOKS_DIR.mkdir(parents=True, exist_ok=True)
    (LOOKS_DIR / f"{name}.json").write_text(json.dumps(look, indent=2))
    return {"name": name, **look}


def _files_in_zip(data: bytes):
    """(name, bytes) of every LUT file in a zip, with nothing written outside our folder."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            n = Path(info.filename).name
            if info.is_dir() or n.startswith(".") or "__MACOSX" in info.filename:
                continue
            if Path(n).suffix.lower() in (".cube", ".png", ".tif", ".tiff") and info.file_size < 64 * 1024 * 1024:
                yield info.filename, z.read(info)


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        if total > MAX_DOWNLOAD:
            raise ReelError(f"{url} is {total // 2**20} MB: too big")
        buf, got, last = io.BytesIO(), 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            got += len(chunk)
            if got > MAX_DOWNLOAD:
                raise ReelError(f"{url} is bigger than {MAX_DOWNLOAD // 2**20} MB")
            if total and got - last > total / 10:
                last = got
                log(f"  downloading {got * 100 // total}%")
        return buf.getvalue()


def add(sources: list[str], pack: str | None = None, name: str | None = None, licence: str = "") -> list[dict]:
    """Import LUTs as looks: files (.cube, HaldCLUT .png), folders, zips or URLs of any of those."""
    import tempfile
    added, skipped = [], []
    pack = pack or "yours"

    def one(fname: str, data: bytes | None, path: Path | None, source: str):
        stem = Path(fname).stem
        try:
            if data is not None:
                with tempfile.TemporaryDirectory() as td:
                    tmp = Path(td) / Path(fname).name
                    tmp.write_bytes(data)
                    table = load_table(tmp)
            else:
                table = load_table(path)
        except Exception as e:
            skipped.append(f"{Path(fname).name} ({e})")
            return
        title = name if (name and len(sources) == 1 and not added) else title_of(stem)
        sub = Path(fname).parent.name
        if pack == "film-simulation" and sub and sub not in (".", "HaldCLUT"):
            title = f"{title_of(sub)}: {title}" if not title.lower().startswith(sub.lower()) else title
        added.append(add_table(table, title, pack, source, licence))
        if len(added) % 25 == 0:
            log(f"  {len(added)} looks added")

    for src in sources:
        if re.match(r"https?://", src):
            log(f"downloading {src}")
            data = _download(src)
            if src.lower().split("?")[0].endswith(".zip") or data[:2] == b"PK":
                for fn, b in _files_in_zip(data):
                    one(fn, b, None, src)
            else:
                one(Path(src.split("?")[0]).name, data, None, src)
            continue
        p = Path(src).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix.lower() in (".cube", ".png", ".tif", ".tiff"):
                    one(str(f.relative_to(p)), None, f, str(p))
                elif f.suffix.lower() == ".zip":
                    for fn, b in _files_in_zip(f.read_bytes()):
                        one(fn, b, None, str(f))
        elif p.suffix.lower() == ".zip" and p.exists():
            for fn, b in _files_in_zip(p.read_bytes()):
                one(fn, b, None, str(p))
        elif p.exists():
            one(p.name, None, p, str(p))
        else:
            raise ReelError(f"not a file, folder, zip or link: {src}")
    if skipped:
        log(f"skipped {len(skipped)}: " + "; ".join(skipped[:6]) + (" ..." if len(skipped) > 6 else ""))
    if not added:
        raise ReelError("no 3D LUTs found (.cube files or HaldCLUT images)")
    log(f"{len(added)} look(s) added" + (f" to {pack}" if pack != "yours" else ""))
    return added


def fetch(pack: str) -> list[dict]:
    """Download one of the free packs and add its LUTs as looks (done again, it replaces them)."""
    if pack not in PACKS:
        raise ReelError(f"unknown pack {pack} ({', '.join(PACKS)})")
    info = PACKS[pack]
    log(f"{info['title']} by {info['by']}, about {info['size_mb']} MB. {info['licence']}")
    remove(pack=pack, quiet=True)
    return add([info["url"]], pack=pack, licence=info["licence"])


def remove(name: str | None = None, pack: str | None = None, quiet: bool = False) -> int:
    """Remove one imported look, or a whole pack."""
    n = 0
    for p in sorted(LOOKS_DIR.glob("*.json")) if LOOKS_DIR.exists() else []:
        try:
            lk = json.loads(p.read_text())
        except Exception:
            continue
        if not lk.get("cube") or not str(lk.get("cube")).startswith(str(LIB)):
            continue
        if (name and p.stem == name) or (pack and lk.get("pack") == pack):
            Path(lk["cube"]).unlink(missing_ok=True)
            p.unlink()
            n += 1
    if pack:
        shutil.rmtree(LIB / slug(pack), ignore_errors=True)
    if not quiet:
        log(f"removed {n} look(s)")
    return n


def packs() -> list[dict]:
    """The free packs, and whether each is in the library."""
    from .grade import list_looks
    have: dict[str, int] = {}
    for lk in list_looks().values():
        if lk.get("pack"):
            have[lk["pack"]] = have.get(lk["pack"], 0) + 1
    return [{"id": k, **v, "installed": have.get(k, 0)} for k, v in PACKS.items()]
