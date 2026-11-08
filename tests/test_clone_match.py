"""Clone: one shot per moment, light-and-colour matching, a black ending becomes a fade."""
from PIL import Image, ImageDraw

from tripshots import clone, diversity
from tripgen import photo


def _scene(path, sky, ground, sun=None, person_x=None, shift=0, when="2026:10:09 18:00:00", view=0):
    im = Image.new("RGB", (1600, 1200), sky)
    d = ImageDraw.Draw(im)
    peaks = [[(500, 420), (900, 650), (1300, 380)], [(300, 900), (800, 300), (1400, 850)],
             [(200, 500), (600, 950), (1000, 450)], [(700, 800), (1100, 300), (1500, 900)]][view]
    d.polygon([(0, 700 + shift), *peaks, (1600, 600), (1600, 1200), (0, 1200)], fill=ground)
    if sun:
        d.ellipse([1100 + shift, 380, 1260 + shift, 540], fill=sun)
    if person_x:
        d.rectangle([person_x + shift, 600, person_x + 60 + shift, 900], fill=(20, 20, 20))
    im.save(path)
    return photo(path, when, src=path)


def _shot(i, p, kind="photo", created="2026-10-09T18:00:00"):
    return {"id": f"S{i:03d}", "kind": kind, "thumb": str(p), "src": str(p), "sig": f"sig{i}", "t0": 0, "t1": 0,
            "w": 1600, "h": 1200, "created": created, "ai": {"score": 8, "tags": [], "note": ""}}


def test_scene_groups_and_light_matching(tmp_path):
    golden = ((250, 190, 120), (90, 60, 30), (255, 240, 200))
    blue = ((90, 150, 230), (60, 110, 60), None)
    a = _scene(tmp_path / "a.jpg", *golden, person_x=600)
    b = _scene(tmp_path / "b.jpg", *golden, person_x=600, shift=12, when="2026:10:09 18:00:20")   # a burst
    c = _scene(tmp_path / "c.jpg", *blue, when="2026:10:09 12:00:00")
    d = _scene(tmp_path / "d.jpg", *blue, when="2026:10:10 12:00:00", view=1)
    shots = [_shot(1, a), _shot(2, b, created="2026-10-09T18:00:20"), _shot(3, c, created="2026-10-09T12:00:00"),
             _shot(4, d, created="2026-10-10T12:00:00")]
    g = diversity.scene_groups(shots)
    assert g["S001"] == g["S002"]                      # the burst is one moment
    assert len({g["S001"], g["S003"], g["S004"]}) == 3
    ref_frame = tmp_path / "ref.jpg"
    Image.open(a).resize((360, 270)).save(ref_frame)
    ref = {"shots": [{"id": "R01", "frame": str(ref_frame), "dur": 1.0, "motion": 0},
                     {"id": "R02", "frame": str(ref_frame), "dur": 1.0, "motion": 0}]}
    slots = [{"id": "R01", "type": "other"}, {"id": "R02", "type": "other"}]
    m = clone.heuristic_match(slots, ref["shots"], shots, ref, g)
    assert m["R01"][0] in ("S001", "S002")            # golden reference -> golden shot first
    picks = clone._assign(slots, ref["shots"], m, {s["id"]: s for s in shots}, 0, g, m)
    assert g[picks[0]] != g[picks[1]]                  # never the burst twice


def test_black_ending_becomes_a_fade(tmp_path, monkeypatch):
    black = tmp_path / "black.jpg"
    Image.new("RGB", (360, 640), (3, 3, 3)).save(black)
    pic = tmp_path / "p.jpg"
    Image.new("RGB", (360, 640), (200, 160, 100)).save(pic)
    ref = {"shots": [{"id": "R01", "frame": str(pic), "f0": 0, "f1": 45, "t0": 0, "t1": 1.5, "dur": 1.5},
                     {"id": "R02", "frame": str(pic), "f0": 45, "f1": 90, "t0": 1.5, "t1": 3, "dur": 1.5},
                     {"id": "R03", "frame": str(black), "f0": 90, "f1": 97, "t0": 3, "t1": 3.2333, "dur": 0.2333}],
           "duration": 3.2333, "source": "x", "dir": str(tmp_path)}
    shots = [_shot(i, _scene(tmp_path / f"s{i}.jpg", (200 - 40 * i, 160, 90 + 50 * i), (60, 50, 40),
                             when=f"2026:10:0{i + 1} 10:00:00", view=i + 1), created=f"2026-10-0{i + 1}T10:00:00")
             for i in range(3)]
    for s in shots:
        s["still"] = s["thumb"]
    from tripshots.config import load_style
    slots = [{"id": f"R0{k}", "type": "other", "energy": "calm", "text": ""} for k in (1, 2, 3)]
    plan = clone.build_clone_plan(ref, slots, {}, {}, shots, load_style("beat-montage"),
                                  fallback=clone.heuristic_match(slots, ref["shots"], shots, ref, depth=12))
    assert len(plan["segments"]) == 2 and abs(sum(s["dur"] for s in plan["segments"]) - 3.2333) < 1e-3
    assert plan["fade_out_video"] > 0.2
    assert len({s["shot_id"] for s in plan["segments"]}) == 2


def test_follow_motion():
    e = {"kind": "photo", "layout": "kenburns", "kb": "in"}
    clone._follow_motion(e, {"dx": -0.1, "zoom": 0.0})
    assert e["kb"] == "left"
    clone._follow_motion(e, {"dx": 0.0, "zoom": -0.05})
    assert e["kb"] == "out"


def test_template_track_follows_the_subject_while_the_camera_moves(tmp_path):
    import cv2
    import numpy as np
    from tripshots.framing import template_track
    rng = np.random.default_rng(3)
    world = cv2.GaussianBlur(rng.integers(0, 255, (180, 1200, 3)).astype(np.uint8), (0, 0), 3)
    cv2.rectangle(world, (500, 90), (520, 130), (230, 40, 40), -1)          # the small subject (a person)
    frames = np.stack([world[:, 300 + 12 * i: 300 + 12 * i + 320] for i in range(12)])  # camera pans right
    thumb = tmp_path / "t.jpg"
    cv2.imwrite(str(thumb), cv2.cvtColor(frames[0], cv2.COLOR_RGB2BGR))
    box = {"x0": 200 / 320, "x1": 220 / 320, "y0": 0.5, "y1": 130 / 180, "cx": 210 / 320, "cy": 0.6}
    xs = template_track(frames, str(thumb), box)
    assert xs is not None
    want = np.array([(210 - 12 * i) / 320 for i in range(12)])
    assert np.abs(xs - want).max() < 0.03


def test_a_person_is_framed_not_panned_past():
    from tripshots.config import load_style
    from tripshots.planner import _shot_fields
    shot = {"id": "S1", "kind": "video", "src": "/x.mp4", "t0": 0, "t1": 10, "w": 3840, "h": 2160, "fps": 60,
            "metrics": {"pan": 0.0, "activity": 0.0},
            "samples": {"t": [0, 5], "sharp": [1, 1], "jitter": [0, 0]},
            "ai": {"subject_box": [0.2, 0.17, 0.6, 1.0],
                   "subjects": [{"label": "man with raised arms", "box": [0.5, 0.2, 0.6, 1.0]},
                                {"label": "half dome", "box": [0.2, 0.17, 0.6, 0.7]}]}}
    e, _ = _shot_fields(shot, 2.0, "calm", load_style("beat-montage"), 0)
    assert e["layout"] == "crop" and abs(e["subject_x"] - 0.55) < 1e-6
