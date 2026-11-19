"""The crop is placed on the frames that actually play (compose.py)."""
import json

import numpy as np

from tripshots import compose
from conftest import ff, needs_ffmpeg


def _person(cx, w=0.05, yaw=0.0, y=0.3):
    f = {"x": cx - w / 2, "y": y, "w": w, "h": w * 1.6, "yaw": yaw, "score": 0.9}
    return compose._people([f], [])[0]


CW = 0.316  # a 16:9 clip cut to 9:16


def test_a_group_that_fits_is_held_whole_and_not_cut_at_the_edge():
    ps = [_person(0.30), _person(0.42)]
    r = compose.decide([(t, ps) for t in (0, 0.5, 1)], CW, 1.0, 1.5)
    a, b = r["span"]
    assert r["by"] == "people" and "pts" not in r
    assert r["cx"] - CW / 2 < a and b < r["cx"] + CW / 2


def test_one_person_looking_sideways_gets_room_in_front():
    right = compose.decide([(t, [_person(0.5, yaw=0.6)]) for t in (0, 1)], CW, 1.0, 1.0)
    left = compose.decide([(t, [_person(0.5, yaw=-0.6)]) for t in (0, 1)], CW, 1.0, 1.0)
    assert right["cx"] > 0.5 > left["cx"] and "look" in right["why"]
    p = _person(0.5)   # still never cut: the person stays inside the window
    for r in (right, left):
        assert r["cx"] - CW / 2 < p["x0"] and p["x1"] < r["cx"] + CW / 2


def test_a_person_at_the_edge_of_the_clip_is_not_centred_off_the_picture():
    r = compose.decide([(0, [_person(0.03)])], CW, 1.0, 1.0)
    assert abs(r["cx"] - CW / 2) < 1e-6


def test_people_too_far_apart_keep_the_main_person():
    ps = [_person(0.15, w=0.04), _person(0.8, w=0.07)]
    r = compose.decide([(t, ps) for t in (0, 1)], CW, 1.0, 1.0)
    assert r["why"].startswith("the main person") and abs(r["cx"] - 0.8) < 0.1


def test_someone_walking_across_is_followed_slowly():
    r = compose.decide([(t, [_person(0.2 + 0.2 * t)]) for t in (0, 0.5, 1, 1.5, 2)], CW, 1.0, 2.0)
    xs = [c for _t, c in r["pts"]]
    assert xs == sorted(xs) and xs[-1] - xs[0] > 0.2
    assert all(b - a <= compose.MAX_SPEED * 0.5 + 1e-6 for a, b in zip(xs, xs[1:]))


def test_an_upright_clip_cut_top_and_bottom_keeps_the_head_with_eyes_high():
    ps = [_person(0.5, w=0.1, y=0.4)]
    r = compose.decide([(0, ps), (1, ps)], 1.0, 0.56, 1.0)
    top = r["cy"] - 0.56 / 2
    assert top < ps[0]["y0"] and 0.3 < (0.4 + 0.4 * 0.16 - top) / 0.56 < 0.4
    big = [_person(0.5, w=0.2, y=0.3)]   # a close-up: the top of the head wins over the third
    r = compose.decide([(0, big)], 1.0, 0.56, 1.0)
    assert r["cy"] - 0.56 / 2 < big[0]["y0"]


def test_a_passer_by_in_one_frame_is_not_the_subject():
    samples = [(t, []) for t in range(5)] + [(5, [_person(0.9)])]
    assert compose.decide(samples, CW, 1.0, 2.0) is None


@needs_ffmpeg
def test_the_window_that_plays_is_what_gets_looked_at(tmp_path, monkeypatch):
    # a white square moves left to right; the clip is cut 0.5-1.5 s, where it is on the right
    src = tmp_path / "walk.mp4"
    ff("-f", "lavfi", "-i", "color=c=black:s=640x360:d=2:r=30", "-vf",
       "drawbox=x='if(lt(t,0.5),60,480)':y=150:w=40:h=60:c=white:t=fill", str(src))
    monkeypatch.setattr(compose, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(compose, "figures", lambda rgb: [])

    def bright(rgb):
        xs = np.nonzero(rgb[..., 0].max(0) > 200)[0]
        return [{"x": xs.min() / rgb.shape[1], "y": 0.4, "w": (xs.max() - xs.min()) / rgb.shape[1], "h": 0.17,
                 "yaw": 0.0, "score": 1.0}] if len(xs) else []
    monkeypatch.setattr(compose, "faces", bright)
    e = {"kind": "video", "src": str(src), "src_w": 640, "src_h": 360, "in": 0.6, "speed": 1.0, "layout": "crop",
         "subject_x": 0.2, "subject": {"cx": 0.2, "x0": 0.1, "x1": 0.3, "cy": 0.5}}
    out = compose.apply(e, 0.9, (1080, 1920))
    assert out["subject_x"] > 0.6 and out["_framed"]["by"] == "people" and e["subject_x"] == 0.2
    assert compose.fit({**e, "frame_by": "hand"}, 0.9, (1080, 1920)) is None
    assert compose.fit({**e, "src_w": 360, "src_h": 640}, 0.9, (1080, 1920)) is None   # already upright: nothing cut


def test_framing_by_hand_sticks_until_put_back_to_automatic(tmp_path, monkeypatch):
    from tripshots import planedit
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    (tmp_path / "shots_scored.json").write_text("[]")
    seg = {"shot_id": "S1", "kind": "video", "src": "/x/a.mp4", "in": 0.0, "dur": 2.0, "out_start": 0.0,
           "layout": "crop", "subject_x": 0.5, "subject": {"cx": 0.5, "x0": 0.4, "x1": 0.6}, "src_w": 1920,
           "src_h": 1080, "level": "mid", "trans_out": None}
    p = tmp_path / "t.plan.json"
    p.write_text(json.dumps({"style": "beat-montage", "work": str(tmp_path), "duration": 2.0, "segments": [seg],
                             "color": {}, "tempo": 120, "overlays": []}))
    planedit.apply(p, [{"op": "frame", "segment": 1, "subject_x": 0.3}])
    s = json.loads(p.read_text())["segments"][0]
    assert s["frame_by"] == "hand" and s["subject_x"] == 0.3
    planedit.apply(p, [{"op": "frame", "segment": 1, "auto": True}])
    assert "frame_by" not in json.loads(p.read_text())["segments"][0]
