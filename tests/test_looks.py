"""The look library: built-in cinematic and travel looks, any LUT as a look (luts.py), automatic choice."""
import json

import cv2
import numpy as np
import pytest

from tripshots import grade, luts


def _cube(path, f, size=9):
    path.write_text("TITLE \"t\"\nLUT_3D_SIZE %d\n" % size + "\n".join(
        " ".join(f"{v:.6f}" for v in f(np.array([r, g, b]) / (size - 1)))
        for b in range(size) for g in range(size) for r in range(size)) + "\n")
    return path


def _hald(path, f, level=4):
    n = level * level
    idx = np.arange(n ** 3)
    r, g, b = idx % n, (idx // n) % n, idx // (n * n)
    rgb = np.stack([f(np.array([x, y, z]) / (n - 1)) for x, y, z in zip(r, g, b)])
    img = (rgb.reshape(level ** 3, level ** 3, 3) * 255).round().astype(np.uint8)
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return path


warm = lambda c: np.clip(c * np.array([1.08, 1.0, 0.86]) + np.array([0.02, 0.01, 0.0]), 0, 1)


def test_a_cube_and_a_haldclut_become_looks(tmp_path):
    a = _cube(tmp_path / "Warm Sunset.cube", warm)
    b = _hald(tmp_path / "warm_hald.png", warm)
    got = luts.add([str(a), str(b)])
    assert [g["title"] for g in got] == ["Warm sunset", "Warm hald"]
    looks = grade.list_looks()
    lk = looks[got[0]["name"]]
    assert lk["cube"].endswith(".cube") and ("warm" in lk["desc"].lower() or "golden" in lk["desc"].lower())
    # the HaldCLUT reads the same as the .cube it was made from
    t1, t2 = grade.read_lut(lk["cube"]), grade.read_lut(looks[got[1]["name"]]["cube"])
    probe = np.random.default_rng(1).random((50, 3)).astype(np.float32)
    assert np.abs(grade.sample_lut(t1, probe) - grade.sample_lut(t2, probe)).max() < 0.03
    assert luts.remove(name=got[0]["name"], quiet=True) == 1 and got[0]["name"] not in grade.list_looks()


def test_a_zip_and_bad_files(tmp_path):
    import zipfile
    _cube(tmp_path / "a.cube", warm)
    (tmp_path / "notes.cube").write_text("LUT_1D_SIZE 4\n0 0 0\n1 1 1\n")
    with zipfile.ZipFile(tmp_path / "pack.zip", "w") as z:
        z.write(tmp_path / "a.cube", "../../evil/a.cube")   # a path that tries to leave the folder
        z.write(tmp_path / "notes.cube", "notes.cube")
    got = luts.add([str(tmp_path / "pack.zip")], pack="test-pack")
    assert len(got) == 1 and got[0]["pack"] == "test-pack"
    assert str(luts.LIB) in got[0]["cube"]
    with pytest.raises(Exception):
        luts.add([str(tmp_path / "notes.cube")])


def test_profiles_flag_log_luts_and_negatives():
    ident = np.stack(np.meshgrid(*[np.linspace(0, 1, 9)] * 3, indexing="ij"), -1)[..., ::-1].astype(np.float32)
    logish = np.clip((ident - 0.5) * 3.2 + 0.5, 0, 1)
    p = luts.profile(logish)
    assert p["log_input"] and "log" in luts.describe(p)
    neg = luts.profile(1 - ident)
    assert neg["inverts"] and not luts.profile(ident)["inverts"]
    mono = luts.profile(np.repeat(ident.mean(-1, keepdims=True), 3, -1))
    assert mono["mono"]


def test_a_lut_look_grades_a_shot_and_keeps_skin_closer():
    st = grade.measure([np.full((32, 32, 3), 128, np.uint8)])
    teal = lambda c: np.clip(c * np.array([0.7, 1.0, 1.15]), 0, 1)
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    look = luts.add([str(_cube(d / "teal.cube", teal))])[0]
    f = grade.build_transform(st, grade.get_look(look["name"]), 1.0)
    grey = f(np.full((1, 3), 0.5, np.float32))[0]
    skin = np.array([[0.85, 0.62, 0.5]], np.float32)
    out = f(skin)[0]
    assert grey[2] > grey[0]                       # the LUT's teal shows on neutral tones
    full = teal(skin[0])
    assert abs(out[0] - skin[0][0]) < abs(full[0] - skin[0][0])   # skin moved less than the raw LUT would


def test_built_in_looks_and_black_and_white():
    st = grade.measure([cv2.cvtColor(np.uint8([[[200, 120, 60], [40, 90, 200]]]), cv2.COLOR_BGR2RGB).repeat(16, 0).repeat(16, 1)])
    for name in ("cinematic-film", "coastal", "desert-warm", "alpine", "tropical", "forest-moody", "night-neon"):
        out = grade.build_transform(st, grade.get_look(name), 0.8)(np.random.default_rng(0).random((40, 3)).astype(np.float32))
        assert np.isfinite(out).all() and out.min() >= 0 and out.max() <= 1
    bw = grade.build_transform(st, grade.get_look("black-and-white"), 0.6)(np.array([[0.8, 0.3, 0.2], [0.1, 0.5, 0.9]], np.float32))
    assert np.ptp(bw, axis=1).max() < 0.02          # no colour left, whatever the strength


def test_the_footage_picks_the_look_without_ai():
    st = [grade.measure([np.full((8, 8, 3), 140, np.uint8)])]
    assert grade.auto_look(st, ["beach", "ocean", "surf", "sand", "coast"]) == "coastal"
    assert grade.auto_look(st, ["red rock", "canyon", "arch", "desert"]) == "desert-warm"
    assert grade.auto_look(st, ["person", "car"]) in grade.PRESETS
    menu = grade.look_menu()
    assert "cinematic-film" in menu and all(not (grade.list_looks()[k].get("profile") or {}).get("log_input") for k in menu)


def test_a_look_learned_from_reels_moves_colour_families():
    # reference: teal-cyan skies (no pure blue), golden light; shot: a blue sky
    ref = np.zeros((40, 40, 3), np.uint8)
    ref[:20] = (60, 150, 160)       # teal sky
    ref[20:] = (190, 150, 90)       # golden ground
    shot = np.zeros((40, 40, 3), np.uint8)
    shot[:20] = (70, 120, 220)      # blue sky
    shot[20:] = (150, 140, 120)
    look = {**grade.look_from_images([ref], "t"), "match": "full"}
    src = grade.measure([shot])
    ops = grade.band_ops(src["bands"], look["bands"], 1.0)
    assert ops and any(op[2] < -10 for op in ops)          # blue turns toward the reference's cyan
    f = grade.build_transform(src, look, 0.9, {"match": "full"})
    sky = cv2.cvtColor(f(shot[:1, :1].astype(np.float32) / 255).astype(np.float32).reshape(1, 1, 3), cv2.COLOR_RGB2LAB)[0, 0]
    before = cv2.cvtColor((shot[:1, :1].astype(np.float32) / 255).reshape(1, 1, 3), cv2.COLOR_RGB2LAB)[0, 0]
    hue = lambda lab: np.degrees(np.arctan2(lab[2], lab[1])) % 360
    assert hue(sky) < hue(before) - 5
