"""Build the HDR -> SDR lookup tables in tripshots/data/ by measuring the zscale + tonemap chain (fx.ZSCALE_CHAIN)
on every point of a 33x33x33 colour grid. Run with an ffmpeg that has zscale (e.g. Homebrew's ffmpeg-full):

    python tools/make_hdr_luts.py

TripShots uses the tables (via lut3d, which every ffmpeg has) when the installed ffmpeg lacks zscale, so footage
looks the same either way.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tripshots.fx import zscale_chain  # noqa: E402
from tripshots.hdrlut import SIZE, data_file  # noqa: E402


def measure(transfer: str) -> np.ndarray:
    n = SIZE
    v = np.round(np.linspace(0, 1, n) * 65535).astype(np.uint16)
    B, G, R = np.meshgrid(v, v, v, indexing="ij")      # .cube order: red fastest, then green, then blue
    grid = np.stack([R, G, B], -1).reshape(n * n, n, 3)  # n*n rows of n pixels
    vf = ",".join([f"setparams=color_trc={transfer}:color_primaries=bt2020:colorspace=gbr:range=pc",
                   *zscale_chain(transfer), "format=rgb48le"])
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{n}x{n * n}",
                        "-i", "-", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"],
                       input=grid.tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint16).reshape(n * n * n, 3)


if __name__ == "__main__":
    for tr in ("arib-std-b67", "smpte2084"):
        out = measure(tr)
        np.save(data_file(tr), out)
        print(f"{data_file(tr).relative_to(ROOT)}: {out.shape[0]} points")
