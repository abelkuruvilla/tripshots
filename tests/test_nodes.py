"""Secondary colour grading: layers on parts of the frame (nodes.py)."""
import json

import cv2
import numpy as np

from tripshots import nodes


def _scene():
    """A sky (smooth blue, top), a horizon, and textured ground below."""
    rng = np.random.default_rng(3)
    im = np.zeros((480, 270, 3), np.uint8)
    for y in range(200):
        im[y] = (90 + y // 8, 150 + y // 10, 225)
    ground = rng.integers(60, 140, (280, 270, 1)).astype(np.uint8)
    im[200:] = np.concatenate([ground, ground * 0 + 110, ground // 2], 2)
    return im


def test_a_neutral_layer_changes_nothing_and_matrices_are_sane():
    M = nodes.matrix({"region": "sky"})
    assert np.allclose(M, np.concatenate([np.eye(3), np.zeros((3, 1))], 1))
    grey = nodes.matrix({"region": "sky", "saturation": 0.0})[:, :3] @ np.array([0.2, 0.5, 0.8])
    assert np.ptp(grey) < 1e-5                                   # no saturation: grey
    darker = nodes.matrix({"region": "sky", "exposure": -1})[:, :3] @ np.ones(3) * 0.5
    assert (darker < 0.5).all()
    assert nodes.clean({"region": "sky", "exposure": 9, "contrast": 1.0, "junk": 1}) == {"region": "sky", "exposure": 1.5}


def test_a_sky_layer_darkens_the_sky_and_leaves_the_ground():
    im = cv2.resize(_scene(), (540, 960), interpolation=cv2.INTER_NEAREST)
    out = nodes.apply(im, [{"region": "sky", "exposure": -0.8}], nodes.Masks({}, (540, 960)), still=True)
    sky_before, sky_after = im[:300].mean(), out[:300].mean()
    ground_before, ground_after = im[600:].mean(), out[600:].mean()
    assert sky_after < sky_before - 15
    assert abs(ground_after - ground_before) < 3
    off = nodes.apply(im, [{"region": "sky", "exposure": -0.8, "on": False}], nodes.Masks({}, (540, 960)), still=True)
    assert np.array_equal(off, im)


def test_automatic_layers_hold_back_a_bright_sky():
    im = _scene()
    im[:200] = (200, 225, 250)                                   # a washed-out sky
    layers = nodes.auto_layers(im, {}, None, people=False)
    sky = next(l for l in layers if l["region"] == "sky")
    assert sky["exposure"] < 0 and sky["auto"]
    assert any(l["region"] == "edges" for l in layers)


def test_layer_edits_keep_yours_and_go_back_to_automatic(tmp_path, monkeypatch):
    import tripshots.text as T
    from tripshots import planedit
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    shots = [{"id": "S0", "kind": "photo", "src": "/x/0.jpg", "still": "/x/0.jpg", "w": 4000, "h": 3000, "t0": 0, "t1": 0,
              "ai": {"score": 8}, "metrics": {}}]
    (tmp_path / "shots_scored.json").write_text(json.dumps(shots))
    plan = {"style": "beat-montage", "work": str(tmp_path), "duration": 2.0, "tempo": 120, "overlays": [], "color": {},
            "segments": [{"shot_id": "S0", "kind": "photo", "dur": 2.0, "out_start": 0.0, "trans_out": None,
                          "layers": [{"region": "sky", "exposure": -0.3, "auto": True}]}]}
    p = tmp_path / "t.plan.json"
    p.write_text(json.dumps(plan))
    planedit.apply(p, [{"op": "layer", "segment": 1, "region": "sky", "saturation": 1.2},
                       {"op": "layer", "segment": 1, "region": "subject", "exposure": 0.3}])
    layers = json.loads(p.read_text())["segments"][0]["layers"]
    assert {l["region"]: l.get("auto") for l in layers} == {"sky": False, "subject": False}
    assert next(l for l in layers if l["region"] == "sky") == {"region": "sky", "exposure": -0.3, "saturation": 1.2, "auto": False}
    planedit.apply(p, [{"op": "layer", "segment": 1, "region": "subject", "remove": True}])
    assert [l["region"] for l in json.loads(p.read_text())["segments"][0]["layers"]] == ["sky"]
    from tripshots import grade
    seg = {"layers": [{"region": "sky", "exposure": -0.1, "auto": False}]}
    grade.set_layers(seg, shots[0], {"layers": [{"region": "sky", "exposure": -0.4, "auto": True},
                                                {"region": "greens", "saturation": 1.1, "auto": True}]}, None)
    assert seg["layers"][0]["exposure"] == -0.1 and seg["layers"][1]["region"] == "greens"   # yours stays
