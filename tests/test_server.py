"""The desktop app's local API (server.py): token, reels, timelines, media with byte ranges, jobs, settings."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tripshots import server


@pytest.fixture
def api(tmp_path, monkeypatch):
    reels = tmp_path / "reels"
    reels.mkdir()
    monkeypatch.setenv("TRIPSHOTS_OUT", str(reels))
    server.Handler.token = "tok"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None, token="tok", headers=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={**({"Authorization": f"Bearer {token}"} if token else {}),
                                              **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                return r.status, (json.loads(data) if r.headers.get_content_type() == "application/json" else data)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    yield call, reels
    httpd.shutdown()


def _reel(reels, name="trip"):
    plan = {"style": "x", "segments": [{"out_start": 0, "dur": 1.5, "role": "hook", "shot_id": "S1"},
                                       {"out_start": 1.5, "dur": 2.0, "role": "ending", "shot_id": "S2"}],
            "overlays": [{"type": "hook", "text": "this is", "start": 0, "duration": 1}], "music": {"label": "song"}}
    (reels / f"{name}.plan.json").write_text(json.dumps(plan))
    (reels / f"{name}.mp4").write_bytes(bytes(range(256)) * 8)
    (reels / f"{name}.caption.txt").write_text("hello")
    return reels / f"{name}.plan.json"


def test_every_call_needs_the_token(api):
    call, _ = api
    assert call("/api/health", token=None)[0] == 401
    assert call("/api/health", token="wrong")[0] == 401
    assert call("/api/health") == (200, {"ok": True, "version": server.__version__})


def test_reels_their_timeline_and_media(api):
    call, reels = api
    plan = _reel(reels)
    code, got = call("/api/reels")
    assert code == 200 and [r["name"] for r in got] == ["trip"] and got[0]["rendered"] and got[0]["duration"] == 3.5
    code, d = call(f"/api/reel?plan={plan}")
    assert [s["role"] for s in d["segments"]] == ["hook", "ending"] and d["caption"] == "hello"
    code, part = call(f"/api/file?path={reels / 'trip.mp4'}", headers={"Range": "bytes=10-19"})
    assert code == 206 and part == bytes(range(10, 20))
    assert call("/api/file?path=/etc/hosts")[0] == 404           # outside TripShots' folders: never served
    assert call(f"/api/reel?plan={reels / 'trip.mp4'}")[0] == 400  # only plan files
    assert call("/api/caption", {"plan": str(plan), "text": "new"}) == (200, {"ok": True})
    assert (reels / "trip.caption.txt").read_text() == "new"


def test_jobs_are_only_the_known_kinds_built_from_fields():
    args, _ = server.job_args("make", {"sources": ["/a"], "music": "https://x/reel/1/", "style": "s", "dry_run": True})
    assert args[:1] == ["make"] and "--dry-run" in args and args[-2:] == ["--", "/a"]
    assert server.job_args("learn", {"refs": ["u"], "name": "my style!"})[0] == ["learn", "u", "-n", "my-style"]
    with pytest.raises(server.ReelError):
        server.job_args("rm", {})


def test_a_key_pasted_into_the_wrong_setting_is_not_shown(monkeypatch):
    monkeypatch.setenv("TRIPSHOTS_MODEL", "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    assert server._shown("TRIPSHOTS_MODEL").startswith("(hidden") and server._shown("GEMINI_API_KEY") is True
    monkeypatch.setenv("TRIPSHOTS_MODEL", "claude-sonnet")
    assert server._shown("TRIPSHOTS_MODEL") == "claude-sonnet"
