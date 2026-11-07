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
