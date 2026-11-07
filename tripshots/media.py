"""Find photos/videos in folders and read the metadata we care about
(dimensions, fps, rotation, HDR, capture time, GPS)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from . import library as lib
from .util import ReelError, debug, ffprobe, is_mac, log, parse_rate, run, which, write_json

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".3gp", ".webm"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}

try:  # optional HEIC support
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")

# action / 360 cameras (pattern from tripcut, MIT): files they make that are not usable footage
RAW_360_EXT = {".insv", ".insp"}          # Insta360 raw 360 video / photo: reframe in Insta360 Studio first
PREVIEW_EXT = {".lrv", ".lrf", ".thm"}    # GoPro/Insta360 low-res previews, DJI LRF proxies, thumbnails
# VID_20260912_101530_00_012.mp4 (Insta360), DJI_20260912101530_0001_D.MP4, PXL_20260912_101530123.mp4,
# IMG_20260912_101530.jpg, 20260912_101530.mp4 (Android): the camera's local wall-clock time
_FILENAME_TS = re.compile(r"(20\d{2})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})")


def time_from_filename(name: str) -> str | None:
    m = _FILENAME_TS.search(name)
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups())).isoformat()
    except ValueError:
        return None


def is_equirect(w: int, h: int) -> bool:
    """An unreframed 360 export: exactly 2:1 and large (reframed exports are 16:9, 9:16, ...)."""
    return w >= 2880 and abs(w / max(h, 1) - 2.0) < 0.01


def parse_iso6709(s: str | None):
    if not s:
        return None
    m = _ISO6709.search(s)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    return [round(lat, 6), round(lon, 6)]


# folders that never hold source footage (or hold tripshots's own output / camera junk)
SKIP_DIRS = {"reels", "@eadir", "$recycle.bin", "system volume information", "thumbnails", "thmbnl",
             "proxy", "proxies", "cache"}
# tripshots's own outputs
OUTPUT_SUFFIXES = (".storyboard.jpg", ".cover.jpg")


def _is_live_photo_motion(p: Path, stems: set[str]) -> bool:
    """iPhone Live Photo companion clip: IMG_1234.MOV next to IMG_1234.HEIC/JPG."""
    return p.suffix.lower() == ".mov" and p.stem.lower() in stems


def find_media(inputs: list[Path], skip: list[Path] | None = None, exclude: list[str] | None = None,
               recursive: bool = True, live_photos: bool = False) -> list[Path]:
    """Collect photos/videos from any number of folders (recursively), skipping hidden files,
    macOS '._' sidecar files, tripshots outputs, Live Photo clips and exact duplicates
    (the same file copied to both the SSD and a phone export)."""
    import fnmatch
    skip = [str(s.resolve()) for s in (skip or [])]
    exclude = [e.lower() for e in (exclude or [])]
    files: list[Path] = []
    seen_paths: set[Path] = set()
    for root in inputs:
        root = root.expanduser()
        if not root.exists():
            raise ReelError(f"Input not found: {root}")
        if root.is_file():
            cands = [root]
            base = root.parent
        else:
            base = root
            cands = sorted(root.rglob("*") if recursive else root.iterdir())
        n_before = len(files)
        stems_by_dir: dict[Path, set[str]] = {}
        raw360, previews = [], 0
        for p in cands:
            try:
                rel = p.relative_to(base).parts
            except ValueError:
                rel = (p.name,)
            if any(part.startswith(".") for part in rel):  # hidden + AppleDouble "._X.MOV"
                continue
            if any(part.lower() in SKIP_DIRS or part.lower().endswith((".photoslibrary", ".fcpbundle", ".lrdata"))
                   for part in rel[:-1]):
                continue
            if p.suffix.lower() in RAW_360_EXT and p.is_file():
                raw360.append(p.name)
                continue
            if p.suffix.lower() in PREVIEW_EXT:
                previews += 1
                continue
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXT | PHOTO_EXT:
                continue
            if p.name.lower().endswith(OUTPUT_SUFFIXES) or p.with_suffix(".plan.json").exists():
                continue  # a reel tripshots made earlier
            rp = p.resolve()
            if rp in seen_paths or any(str(rp).startswith(s) for s in skip):
                continue
            rel_s = "/".join(rel).lower()
            if any(fnmatch.fnmatch(t, pat) for pat in exclude for t in (rel_s, "/" + rel_s, p.name.lower())):
                continue
            if not live_photos and p.suffix.lower() == ".mov":
                if p.parent not in stems_by_dir:
                    stems_by_dir[p.parent] = {q.stem.lower() for q in p.parent.iterdir()
                                              if q.suffix.lower() in PHOTO_EXT}
                if _is_live_photo_motion(p, stems_by_dir[p.parent]):
                    continue
            seen_paths.add(rp)
            files.append(p)
        log(f"{root}: {len(files) - n_before} media files" + ("" if recursive or root.is_file() else " (top level only)"))
        if raw360:
            log(f"  skipped {len(raw360)} raw 360° file(s) ({', '.join(raw360[:3])}{'…' if len(raw360) > 3 else ''}): "
                "reframe them in Insta360 Studio (Auto Frame) and export flat 9:16 or 16:9 MP4s")
        if previews:
            log(f"  ignored {previews} camera preview file(s) (.lrv/.lrf/.thm)")

    # drop byte-identical copies (same trip on SSD and in a phone export)
    by_size: dict[int, list[Path]] = {}
    for p in files:
        by_size.setdefault(p.stat().st_size, []).append(p)
    dupes: set[Path] = set()
    for group in by_size.values():
        if len(group) < 2:
            continue
        seen: dict[str, Path] = {}
        for p in group:
            h = lib.content_key(p)
            if h in seen:
                dupes.add(p)
            else:
                seen[h] = p
    if dupes:
        log(f"skipping {len(dupes)} duplicate copies found in more than one folder")
    return [p for p in files if p not in dupes]


def probe_video(path: Path) -> dict:
    info = ffprobe(path)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
               and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    if not vs:
        raise ReelError("no video stream")
    fmt = info.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    stags = {k.lower(): v for k, v in (vs.get("tags") or {}).items()}

    rot = 0
    for sd in vs.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(round(float(sd["rotation"])))
    if not rot and "rotate" in stags:
        rot = int(stags["rotate"])
    w, h = int(vs.get("width", 0)), int(vs.get("height", 0))
    if abs(rot) % 180 == 90:
        w, h = h, w

    duration = float(vs.get("duration") or fmt.get("duration") or 0)
    fps = parse_rate(vs.get("avg_frame_rate")) or parse_rate(vs.get("r_frame_rate"))
    transfer = (vs.get("color_transfer") or "").lower()
    created = (tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
               or stags.get("creation_time"))
    gps = parse_iso6709(tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
                        or tags.get("location-eng"))
    return {
        "kind": "video", "w": w, "h": h, "rotation": rot, "duration": duration, "fps": round(fps, 3),
        "codec": vs.get("codec_name"), "pix_fmt": vs.get("pix_fmt"),
        "hdr": transfer in ("arib-std-b67", "smpte2084"), "transfer": transfer,
        "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
        "created": _local_time(_norm_time(created), path.name), "gps": gps,
        "equirect": is_equirect(w, h),
    }


def _local_time(meta: str | None, name: str) -> str | None:
    """Recording time on the camera's local clock where we can tell (pattern from tripcut, MIT).
    QuickTime metadata is UTC; Insta360/DJI/phone file names carry local time. When both exist and
    differ by a plausible time-zone offset, the file name wins, so evening clips keep their date."""
    named = time_from_filename(name)
    if not meta:
        return named
    if named:
        try:
            gap = (datetime.fromisoformat(named) - datetime.fromisoformat(meta)).total_seconds()
            q = round(gap / 900) * 900
            if abs(q) <= 14 * 3600 and abs(gap - q) <= 120:
                return named
        except ValueError:
            pass
    return meta


def _norm_time(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ", "%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=None).isoformat()
        except ValueError:
            continue
    return s


def _exif_gps(exif) -> list | None:
    try:
        gps = exif.get_ifd(0x8825)
    except Exception:
        return None
    if not gps or 2 not in gps or 4 not in gps:
        return None

    def conv(v, ref):
        d, m, s = (float(x) for x in v)
        val = d + m / 60 + s / 3600
        return -val if ref in ("S", "W") else val
    try:
        lat = conv(gps[2], gps.get(1, "N"))
        lon = conv(gps[4], gps.get(3, "E"))
    except Exception:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    return [round(lat, 6), round(lon, 6)]


def prepare_photo(path: Path, key: str) -> dict:
    """Decode (incl. HEIC), apply EXIF orientation and save a normalized JPEG for ffmpeg
    in the shared library (one per photo, reused by every run)."""
    out = lib.STILLS / f"{key}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    src = path
    if path.suffix.lower() in (".heic", ".heif") and not HEIF_OK:
        if is_mac() and which("sips"):
            tmp = lib.STILLS / f"{key}_sips.jpg"
            if not tmp.exists():
                run(["sips", "-s", "format", "jpeg", str(path), "--out", str(tmp)])
            src = tmp
        else:
            raise ReelError("HEIC needs `pip install pillow-heif` (or macOS sips)")
    with Image.open(src) as im:
        exif = im.getexif()
        gps = _exif_gps(exif)
        created = None
        try:
            created = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        except Exception:
            pass
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        if not out.exists():
            im.thumbnail((4096, 4096))
            im.save(out, "JPEG", quality=94)
    if src != path:
        Path(src).unlink(missing_ok=True)
    return {"kind": "photo", "w": w, "h": h, "duration": None, "fps": None, "hdr": False,
            "created": _norm_time(created) or time_from_filename(path.name), "gps": gps, "still": str(out)}


def ingest(inputs: list[Path], work: Path, opts: dict | None = None) -> list[dict]:
    """Return the media list. Metadata comes from the shared library when the file
    (by content) has been seen before, so repeat runs only stat() each file.
    opts: exclude (globs), recursive, live_photos, since/until (YYYY-MM-DD), skip (extra paths)."""
    opts = opts or {}
    media = []
    files = find_media(inputs, skip=[work, lib.LIB_DIR] + list(opts.get("skip") or []), exclude=opts.get("exclude"),
                       recursive=opts.get("recursive", True), live_photos=opts.get("live_photos", False))
    if not files:
        raise ReelError("No photos or videos found in the input folder(s).")
    since, until = opts.get("since"), opts.get("until")
    dropped_date = dropped_short = new = 0
    equi: list[str] = []
    for p in files:
        try:
            key = lib.content_key(p)
        except OSError as e:
            log(f"skipping {p.name}: {e}")
            continue
        info = lib.get_media(key)
        if info and info.get("kind") == "photo" and not Path(info.get("still", "")).exists():
            info = None  # library still was deleted: rebuild it
        if info is None:
            new += 1
            if new == 1 and len(files) > 50:
                log("reading metadata of new files (only once per file)...")
            try:
                info = probe_video(p) if p.suffix.lower() in VIDEO_EXT else prepare_photo(p, key)
            except Exception as e:  # unreadable file: skip, keep going
                log(f"skipping {p.name}: {e}")
                continue
            if not info.get("created"):  # fall back to file modified time
                info["created"] = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
                info["created_from"] = "mtime"
            lib.put_media(key, info)
        else:
            debug(f"known {p.name}")
        rec = {**info, "sig": key, "path": str(p.resolve()), "name": p.name}
        if rec.get("kind") == "video" and (rec.get("equirect") or is_equirect(rec.get("w", 0), rec.get("h", 0))):
            equi.append(p.name)
            continue
        day = str(rec.get("created") or "")[:10]
        if (since and day and day < since) or (until and day and day > until):
            dropped_date += 1
            continue
        if rec["kind"] == "video" and (rec.get("duration") or 0) < 1.0:
            dropped_short += 1
            continue
        media.append(rec)
    write_json(work / "media.json", media)
    if dropped_date:
        log(f"{dropped_date} files outside {since or '…'} → {until or '…'} skipped")
    if dropped_short:
        log(f"{dropped_short} clips shorter than 1s skipped")
    if equi:
        log(f"skipped {len(equi)} unreframed 360° export(s) (2:1 panorama: {', '.join(equi[:3])}"
            f"{'…' if len(equi) > 3 else ''}): reframe them to a flat 9:16 / 16:9 video first")
    if not media:
        raise ReelError("No photos or videos left after filtering.")
    nv = sum(m["kind"] == "video" for m in media)
    log(f"using {nv} videos and {len(media) - nv} photos ({len(files) - new} already known, {new} new)")
    return media
