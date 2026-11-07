import re

from tripshots import export

PLAN = {"duration": 4.0, "tempo": 120, "style": "t", "music": {"path": "/m/song.wav", "start": 10.0},
        "segments": [{"shot_id": "S1", "kind": "video", "src": "/f/DJI_0001.MP4", "in": 1.0, "dur": 2.0, "speed": 0.5,
                      "out_start": 0.0, "trans_out": "whip"},
                     {"shot_id": "S2", "kind": "photo", "src": "/f/IMG_1.jpg", "dur": 2.0, "out_start": 2.0}],
        "overlays": [{"type": "hook", "text": "Day one", "start": 0.1, "duration": 1.5}]}


def test_timecode():
    assert export.tc(0) == "00:00:00:00"
    assert export.tc(1.5) == "00:00:01:15"
    assert export.tc(3661 + 1 / 30) == "01:01:01:01"


def test_edl_lines():
    edl = export.to_edl(PLAN, "trip")
    ev = [l for l in edl.splitlines() if re.match(r"^\d{3}  ", l)]
    assert len(ev) == 3  # two shots + music
    v1 = ev[0].split()
    assert v1[4:8] == ["00:00:01:00", "00:00:02:00", "01:00:00:00", "01:00:02:00"]  # half speed: 1 s of source
    assert "M2" in edl and "* FROM CLIP NAME: DJI_0001.MP4" in edl


def test_markdown_has_every_shot():
    md = export.to_markdown(PLAN, "trip")
    assert md.count("\n| ") == 3 and "Day one" in md
