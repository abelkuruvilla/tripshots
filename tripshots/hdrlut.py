"""HDR -> SDR without zscale, through a 3D LUT applied with lut3d (in every ffmpeg build).

Homebrew's standard `ffmpeg` no longer includes zscale (it moved to `ffmpeg-full`), so iPhone HLG and HDR10 (PQ)
footage needs another route to normal colour. The tables in tripshots/data/ were measured from TripShots' own
zscale + tonemap chain (tools/make_hdr_luts.py), so both routes give the same picture. The YUV -> R'G'B' step
(BT.2020 matrix, limited range) is done by ffmpeg's scale filter, then the table maps the HDR signal to BT.709.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import HOME

LUT_VERSION = 1
SIZE = 65
DATA = Path(__file__).parent / "data"


def _kind(transfer: str | None) -> str:
    return "pq" if transfer == "smpte2084" else "hlg"


def data_file(transfer: str | None) -> Path:
    return DATA / f"hdr_{_kind(transfer)}_to_sdr_{SIZE}.npy"


def lut_path(transfer: str | None) -> Path:
    """The .cube for this transfer, written once from the packaged table into ~/.tripshots/luts."""
    p = HOME / "luts" / f"hdr_{_kind(transfer)}_to_sdr_v{LUT_VERSION}.cube"
    if not p.exists():
        table = np.load(data_file(transfer)).astype(np.float64) / 65535.0
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        with open(tmp, "w") as fh:
            fh.write(f'TITLE "tripshots hdr {_kind(transfer)} to sdr"\nLUT_3D_SIZE {SIZE}\n'
                     "DOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n")
            fh.write("\n".join(f"{a:.6f} {b:.6f} {c:.6f}" for a, b, c in table) + "\n")
        tmp.replace(p)
    return p


def chain(info: dict) -> list[str]:
    """ffmpeg filters: decode the BT.2020 YUV to R'G'B' unchanged, then the table."""
    lut = str(lut_path(info.get("transfer"))).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return ["scale=in_color_matrix=bt2020:in_range=tv:out_range=pc", "format=rgb48le",
            f"lut3d=file='{lut}':interp=tetrahedral"]
