"""HDR -> SDR: the lut3d fallback (for ffmpeg builds without zscale) matches the zscale + tonemap chain."""
import subprocess

import numpy as np
import pytest

from tripshots import fx, hdrlut
from tripshots.util import has_filter

TRANSFERS = ["arib-std-b67", "smpte2084"]


def test_tables_are_packaged():
    for tr in TRANSFERS:
        t = np.load(hdrlut.data_file(tr))
        assert t.shape == (hdrlut.SIZE ** 3, 3) and t.dtype == np.uint16
        assert t[0].max() < 2000                # black stays black
        assert t[-1].min() > 60000              # peak white maps to white


def test_cube_written_once(tmp_path, monkeypatch):
    monkeypatch.setattr(hdrlut, "HOME", tmp_path)
    p = hdrlut.lut_path("arib-std-b67")
    lines = p.read_text().splitlines()
    assert f"LUT_3D_SIZE {hdrlut.SIZE}" in lines
    assert len([ln for ln in lines if ln[:1].isdigit()]) == hdrlut.SIZE ** 3
    mtime = p.stat().st_mtime_ns
    assert hdrlut.lut_path("arib-std-b67").stat().st_mtime_ns == mtime
    assert hdrlut.lut_path("smpte2084") != p


def test_chain_without_zscale(monkeypatch):
    monkeypatch.setattr(fx, "has_filter", lambda name: name == "lut3d")
    chain = fx.hdr_chain({"hdr": True, "transfer": "arib-std-b67"})
    assert chain[0].startswith("scale=in_color_matrix=bt2020") and chain[-1].startswith("lut3d=")
    assert fx.hdr_chain({"hdr": False}) == []
    monkeypatch.setattr(fx, "has_filter", lambda name: True)
    assert fx.hdr_chain({"hdr": True, "transfer": "smpte2084"}) == fx.zscale_chain("smpte2084")


@pytest.mark.skipif(not (has_filter("zscale") and has_filter("tonemap") and has_filter("lut3d")),
                    reason="needs an ffmpeg with zscale to compare against")
@pytest.mark.parametrize("transfer", TRANSFERS)
def test_lut_matches_zscale(transfer):
    rng = np.random.default_rng(1)
    x = rng.integers(0, 65536, (128 * 128, 3)).astype(np.uint16)

    def run(chain):
        p = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", "128x128",
                            "-i", "-", "-vf", ",".join(chain + ["format=rgb24"]), "-f", "rawvideo", "-"],
                           input=x.tobytes(), capture_output=True, check=True)
        return np.frombuffer(p.stdout, np.uint8).astype(int)

    tag = f"setparams=color_trc={transfer}:color_primaries=bt2020:colorspace=gbr:range=pc"
    z = run([tag] + fx.zscale_chain(transfer))
    lut = str(hdrlut.lut_path(transfer))
    lt = run([f"lut3d=file='{lut}':interp=tetrahedral"])
    d = np.abs(z - lt)
    assert d.mean() < 1.0 and np.percentile(d, 99) < 8
