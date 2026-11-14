import numpy as np

from tripshots import grade


def _img(rgb):
    return np.full((64, 64, 3), rgb, np.uint8)


def test_strength_scales_the_grade():
    rng = np.random.default_rng(0)
    imgs = [np.clip(rng.normal(128, 50, (64, 64, 3)), 0, 255).astype(np.uint8)]
    st, look = grade.measure(imgs), grade.get_look("natural")
    x = rng.random((32, 32, 3))
    off = np.abs(grade.build_transform(st, look, strength=0.0)(x) - x).mean()
    on = np.abs(grade.build_transform(st, look, strength=0.8)(x) - x).mean()
    assert off < 0.01 < on


def test_grey_stays_neutral():
    rng = np.random.default_rng(1)
    imgs = [np.clip(rng.normal(128, 40, (64, 64, 3)), 0, 255).astype(np.uint8)]
    f = grade.build_transform(grade.measure(imgs), grade.get_look("natural"), strength=0.8)
    out = grade.apply_to_image(_img((128, 128, 128)), f)[0, 0].astype(int)
    assert out.max() - out.min() <= 12  # no strong colour cast on mid grey


def test_a_flat_scene_stays_flat():
    rng = np.random.default_rng(2)
    sand = np.clip(rng.normal(150, 6, (96, 96, 3)), 0, 255).astype(np.uint8)   # wet sand, fog: tones close together
    look = {**grade.get_look("natural"), "Lq": [0, 4, 22, 41, 64, 88, 96], "black": 0, "white": 96}
    st = grade.measure([sand])
    out = grade.measure([grade.apply_to_image(sand, grade.build_transform(st, look, 0.9, {"match": "full"}))])
    before, after = st["Lq"][5] - st["Lq"][1], out["Lq"][5] - out["Lq"][1]
    assert after <= grade.MAX_CONTRAST * before + 2               # texture isn't turned into blotches
    full = np.clip(rng.normal(128, 55, (96, 96, 3)), 0, 255).astype(np.uint8)  # a shot with its own contrast
    st = grade.measure([full])
    f = grade.build_transform(st, look, 0.9, {"match": "full"})
    cap, grade.MAX_CONTRAST = grade.MAX_CONTRAST, 99.0
    try:
        g = grade.build_transform(st, look, 0.9, {"match": "full"})
    finally:
        grade.MAX_CONTRAST = cap
    assert np.abs(grade.apply_to_image(full, f).astype(int) - grade.apply_to_image(full, g).astype(int)).max() <= 6
