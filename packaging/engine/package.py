"""Turn a PyInstaller build (dist/tripshots/) into a release archive the desktop app installs.

    python packaging/engine/package.py --dist dist/tripshots --platform darwin-aarch64 --version 0.2.0 [--ffmpeg DIR] --out out/

1. copies ffmpeg/ffprobe from --ffmpeg (if given) into tripshots/bin/ (the engine puts that folder first on PATH)
2. smoke-tests the engine: `--help`, then `serve` answers /api/health with the right version
3. archives it: tripshots-engine-<version>-<platform>.zip on Windows, .tar.gz elsewhere (keeps permissions)
4. writes <archive>.json: {platform, file, sha256, size} for packaging/engine/manifest.py

Signing the archive (minisign, the same key as the app's updater) is a separate step: `tauri signer sign`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path


def smoke(exe: Path, version: str) -> None:
    out = subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=180)
    if out.returncode != 0 or "serve" not in out.stdout:
        sys.exit(f"engine --help failed:\n{out.stdout}\n{out.stderr}")
    # complex scripts (Malayalam) must shape: the frozen engine has to find its own fribidi (entry._text_shaping)
    doc = subprocess.run([str(exe), "doctor"], capture_output=True, text=True, timeout=180, cwd=str(Path.home()))
    if "shaping    ok" not in doc.stdout:
        sys.exit(f"engine can't shape complex scripts (Malayalam would render with split letters):\n{doc.stdout[-800:]}")
    env = {**os.environ, "TRIPSHOTS_API_TOKEN": "smoke", "TRIPSHOTS_HOME": str(Path.cwd() / ".smoke-home")}
    p = subprocess.Popen([str(exe), "serve"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    try:
        line = p.stdout.readline()
        url = json.loads(line)["url"]
        req = urllib.request.Request(url + "/api/health", headers={"Authorization": "Bearer smoke"})
        got = json.loads(urllib.request.urlopen(req, timeout=30).read())
        if got.get("version") != version:
            sys.exit(f"engine says version {got.get('version')}, release is {version}")
        print(f"smoke test ok: {url} {got}")
    except Exception as e:
        p.kill()
        sys.exit(f"engine serve failed: {e}\n{p.stderr.read()[-3000:]}")
    finally:
        p.kill()
        shutil.rmtree(Path.cwd() / ".smoke-home", ignore_errors=True)


def archive(dist: Path, dest: Path) -> None:
    if dest.suffix == ".zip":
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(dist.rglob("*")):
                z.write(f, Path("tripshots") / f.relative_to(dist))
    else:
        with tarfile.open(dest, "w:gz", compresslevel=6) as t:
            t.add(dist, arcname="tripshots")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True, type=Path)
    ap.add_argument("--platform", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--ffmpeg", type=Path, help="folder holding ffmpeg and ffprobe to bundle")
    ap.add_argument("--out", type=Path, default=Path("out"))
    a = ap.parse_args()
    exe = a.dist / ("tripshots.exe" if a.platform.startswith("windows") else "tripshots")
    if a.ffmpeg:
        b = a.dist / "bin"
        b.mkdir(exist_ok=True)
        for f in a.ffmpeg.iterdir():
            if f.stem.lower() in ("ffmpeg", "ffprobe") and f.is_file():
                shutil.copy2(f, b / f.name)
        for f in a.ffmpeg.glob("LICENSE*"):
            shutil.copy2(f, b / f"FFMPEG-{f.name}")
    t = time.time()
    smoke(exe, a.version)
    a.out.mkdir(parents=True, exist_ok=True)
    ext = "zip" if a.platform.startswith("windows") else "tar.gz"
    dest = a.out / f"tripshots-engine-{a.version}-{a.platform}.{ext}"
    archive(a.dist, dest)
    h = hashlib.sha256(dest.read_bytes()).hexdigest()
    meta = {"platform": a.platform, "file": dest.name, "sha256": h, "size": dest.stat().st_size}
    Path(f"{dest}.json").write_text(json.dumps(meta, indent=2))
    print(f"{dest.name}: {meta['size'] / 1e6:.0f} MB, sha256 {h[:16]}…, {time.time() - t:.0f} s")


if __name__ == "__main__":
    main()
