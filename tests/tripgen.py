"""Synthetic trip folders with real EXIF times/GPS (and, optionally, real face photos)."""
import shutil
import subprocess
from pathlib import Path

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

YELLOWSTONE = (44.62, -110.56)
OLD_FAITHFUL = (44.4605, -110.8281)
DENVER = (39.7392, -104.9903)
LISBON = (38.7223, -9.1393)


def _dms(v):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60 * 100)
    return (IFDRational(d, 1), IFDRational(m, 1), IFDRational(s, 100))


def photo(path: Path, when: str, gps=None, src: Path | None = None, color=(90, 140, 200)):
    """when: 'YYYY:MM:DD HH:MM:SS'."""
    im = Image.open(src).convert("RGB") if src else Image.new("RGB", (1600, 1200), color)
    ex = Image.Exif()
    ex[0x0132] = when
    ex.get_ifd(0x8769)[36867] = when
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2] = ("N" if gps[0] >= 0 else "S"), _dms(gps[0])
        g[3], g[4] = ("E" if gps[1] >= 0 else "W"), _dms(gps[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=90, exif=ex)
    return path


def video(path: Path, gps=None, dur=3, src="testsrc2"):
    meta = []
    if gps:
        meta = ["-metadata", f"location={gps[0]:+.4f}{gps[1]:+.4f}/"]
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"{src}=s=1280x720:r=30", "-t", str(dur),
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", *meta, str(path)], check=True)
    return path


def make_library(root: Path, faces: dict | None = None) -> Path:
    """faces: optional {"me": [paths], "other": [paths], "me_and_other": [paths]} of real photos."""
    faces = faces or {}
    me = list(faces.get("me", []))
    oth = list(faces.get("other", []))
    both = list(faces.get("me_and_other", []))
    ys = root / "SSD" / "Yellowstone 2025"
    photo(ys / "IMG_0001.jpg", "2025:07:12 09:10:00", YELLOWSTONE, me[0] if me else None)
    photo(ys / "IMG_0002.jpg", "2025:07:12 11:30:00", OLD_FAITHFUL, both[0] if both else None, (200, 160, 90))
    photo(ys / "IMG_0003.jpg", "2025:07:13 08:00:00", YELLOWSTONE, oth[0] if oth else None, (60, 160, 90))
    photo(ys / "IMG_0004.jpg", "2025:07:13 16:45:00", OLD_FAITHFUL, None, (220, 220, 240))
    video(ys / "DJI_20250712101500_0001_D.MP4", OLD_FAITHFUL)
    # phone export elsewhere: no GPS (camera off), same day as the park -> added by whole_days
    video(root / "Phone" / "VID_20250712_120000.mp4", None, src="smptehdbars")
    # the drive home through Denver: has GPS far away -> not Yellowstone
    photo(root / "Phone" / "IMG_20250714_101000.jpg", "2025:07:14 10:10:00", DENVER, me[1] if len(me) > 1 else None,
          (120, 120, 120))
    video(root / "Phone" / "VID_20250714_110000.mp4", None, src="mandelbrot")
    # an earlier trip
    photo(root / "Phone" / "IMG_20250310_150000.jpg", "2025:03:10 15:00:00", LISBON,
          me[2] if len(me) > 2 else None, (240, 200, 160))
    photo(root / "Phone" / "IMG_20250311_100000.jpg", "2025:03:11 10:00:00", LISBON,
          oth[1] if len(oth) > 1 else None, (160, 200, 240))
    return root


def seed_place(home: Path, name: str, centre, half=0.5):
    """Offline stand-in for the OpenStreetMap search (tests can't reach it)."""
    import json
    la, lo = centre
    poly = [[lo - half, la - half], [lo + half, la - half], [lo + half, la + half], [lo - half, la + half],
            [lo - half, la - half]]
    p = home / "geocode_search.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    d[name.lower()] = {"name": name, "lat": la, "lon": lo, "bbox": [la - half, la + half, lo - half, lo + half],
                       "type": "national_park", "shape": {"type": "Polygon", "coordinates": [poly]}}
    p.write_text(json.dumps(d))
