import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tripshots import edits

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def fake_edits():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    p = subprocess.Popen([sys.executable, str(HERE / "fake_edits.py"), str(port), "tok3n"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    p.terminate()


def _package(tmp_path):
    pkg = tmp_path / "trip.edits"
    (pkg / "clips").mkdir(parents=True)
    (pkg / "text").mkdir()
    for f in ("picture.mp4", "clips/01-S1.mp4", "clips/02-S2.mp4", "sound-effects.wav", "music.m4a"):
        (pkg / f).write_bytes(b"x")
    m = {"tripshots_edits": 1, "name": "trip", "duration": 4.0, "picture": {"file": "picture.mp4"},
         "clips": [{"file": "clips/01-S1.mp4", "start": 0.0, "duration": 2.0},
                   {"file": "clips/02-S2.mp4", "start": 2.0, "duration": 2.0}],
         "texts": [{"type": "hook", "text": "Old Faithful at dawn", "start": 0.1, "duration": 1.8}],
         "audio": [{"role": "sound effects", "file": "sound-effects.wav", "start": 0.0}],
         "music": {"title": "song", "file": "music.m4a", "song_start": 26.5}}
    (pkg / "manifest.json").write_text(json.dumps(m))
    return pkg


def test_needs_the_token(fake_edits):
    with pytest.raises(Exception):
        edits.tools(fake_edits, "wrong")


def test_probe_maps_the_steps(fake_edits, monkeypatch, tmp_path):
    monkeypatch.setattr(edits, "EDITS_DIR", tmp_path)
    monkeypatch.setattr(edits, "PROFILE", tmp_path / "profile.json")
    res = edits.probe(fake_edits, "tok3n")
    assert res["mapped"] == {"new_project": "createProject", "import": "importMedia",
                             "add_clip": "addClipToTimeline", "add_text": "addText", "add_audio": "addAudio"}
    prof = json.loads((tmp_path / "profile.json").read_text())
    assert prof["confirmed"] is False
    assert prof["steps"]["add_clip"]["args"] == {"mediaId": "{media_id}", "startTime": "{start}",
                                                 "duration": "{duration}"}


def test_push_builds_the_timeline(fake_edits, monkeypatch, tmp_path):
    monkeypatch.setattr(edits, "EDITS_DIR", tmp_path)
    monkeypatch.setattr(edits, "PROFILE", tmp_path / "profile.json")
    edits.probe(fake_edits, "tok3n")
    pkg = _package(tmp_path)
    with pytest.raises(Exception, match="confirmed"):
        edits.push(pkg, url=fake_edits, token="tok3n")
    prof = json.loads((tmp_path / "profile.json").read_text())
    prof["confirmed"] = True
    (tmp_path / "profile.json").write_text(json.dumps(prof))
    res = edits.push(pkg, url=fake_edits, token="tok3n")
    assert res["left_to_do"] and "song" in res["left_to_do"][0]   # music: from Edits' library by default
    import asyncio

    async def timeline():
        async with edits._session(fake_edits, "tok3n") as s:
            return edits._result_json(await s.call_tool("getTimeline", {}))["items"]
    items = asyncio.run(timeline())
    assert [(i["kind"], i["start"]) for i in items] == [("video", 0.0), ("video", 2.0), ("text", 0.1), ("audio", 0.0)]
    assert items[0]["file"].endswith("clips/01-S1.mp4") and items[2]["text"] == "Old Faithful at dawn"


def test_fill_units():
    assert edits._fill({"t": "{start}", "n": "x-{text}"}, {"start": 1.25, "text": "hi"}, "ms") == {"t": 1250, "n": "x-hi"}
    assert edits._fill("{duration}", {"duration": 2.0}, "frames") == 60


def test_titles_behind_the_skyline_stay_in_the_picture():
    from types import SimpleNamespace as NS

    from tripshots.render import TextTrack
    tt = TextTrack({"overlays": [{"type": "hook", "text": "a", "start": 0, "duration": 1},
                                 {"type": "location", "text": "b", "start": 1, "duration": 1}]}, [], native=True)
    tt.built = {0: NS(sprites=[NS(behind=False)]), 1: NS(sprites=[NS(behind=False), NS(behind=True)])}
    assert not tt.baked(0) and tt.baked(1)
