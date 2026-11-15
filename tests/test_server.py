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


def test_ai_page_shows_what_is_ready_and_never_a_key(api, monkeypatch):
    call, _ = api
    monkeypatch.setattr(server, "which", lambda n: None, raising=False)
    import tripshots.util as util
    monkeypatch.setattr(util, "which", lambda n: None)
    monkeypatch.setenv("MINIMAX_API_KEY", "mm-secret-123")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TRIPSHOTS_BACKEND", "auto")
    code, st = call("/api/ai")
    assert code == 200 and st["providers"]["claude"]["state"] == "missing"
    assert st["providers"]["minimax"]["state"] == "ready" and st["order"] == ["minimax"] and st["using"] == "minimax"
    assert "mm-secret-123" not in json.dumps(st)
    assert call("/api/ai/test", {"provider": "nope"})[1]["ok"] is False


def test_keys_are_saved_and_removed(tmp_path, monkeypatch):
    from tripshots import config
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("TRIPSHOTS_BACKEND", "auto")      # (registered so they're put back after the test)
    monkeypatch.setenv("MINIMAX_API_KEY", "x")
    server.save_settings({"env": {"MINIMAX_API_KEY": "mm-1"}, "backend": "minimax"})
    assert "MINIMAX_API_KEY=mm-1" in (tmp_path / ".env").read_text() and server.os.environ["TRIPSHOTS_BACKEND"] == "minimax"
    server.save_settings({"env": {"MINIMAX_API_KEY": ""}})
    assert "MINIMAX_API_KEY" not in server.os.environ and "MINIMAX_API_KEY=mm-1" not in (tmp_path / ".env").read_text()
    server.save_settings({"backend": "rm -rf"})          # only known backends
    assert server.os.environ["TRIPSHOTS_BACKEND"] == "minimax"


def test_the_editor_api_texts_fonts_undo_and_a_still(api, monkeypatch):
    import tripshots.text as T
    monkeypatch.setattr(T, "storyboard", lambda plan, by_id, out: out)
    call, reels = api
    plan = _reel(reels)
    plan.write_text(plan.read_text().replace('"style": "x"', '"style": "beat-montage", "duration": 3.5, "tempo": 120'))
    code, d = call(f"/api/reel?plan={plan}")
    assert d["texts"][0]["index"] == 1 and d["texts"][0]["text"] == "this is" and "hook" in d["text_defaults"]
    code, fonts = call("/api/fonts")
    assert any(f["id"] == "anton" and f["bundled"] for f in fonts) and any(f["id"].startswith("gf:") for f in fonts)
    code, ttf = call("/api/font?name=anton")
    assert code == 200 and len(ttf) > 1000
    assert call("/api/font?name=../../etc/passwd")[0] == 404
    code, res = call("/api/edit", {"plan": str(plan), "edits": [{"op": "edit_text", "index": 1, "style": {"color": "#ff0000"}}]})
    assert code == 200 and res["undo"] == 1
    code, d = call(f"/api/reel?plan={plan}")
    assert d["texts"][0]["style"]["color"] == [255, 0, 0] and d["history"] == {"undo": 1, "redo": 0}
    assert call("/api/undo", {"plan": str(plan)})[0] == 200
    code, d = call(f"/api/reel?plan={plan}")
    assert not d["texts"][0]["style"] and d["history"] == {"undo": 0, "redo": 1}
    assert call("/api/undo", {"plan": str(plan)})[0] == 400        # nothing left to undo
    p = json.loads(plan.read_text())
    for sg in p["segments"]:
        sg["kind"] = "photo"
    plan.write_text(json.dumps(p))
    code, jpg = call(f"/api/still?plan={plan}&at=0.5")           # the edited frame: picture (or black) + its words
    assert code == 200 and jpg[:2] == b"\xff\xd8"



def test_caption_jobs_and_the_post_written_without_an_ai(tmp_path):
    from tripshots import social
    p = tmp_path / "r.plan.json"
    p.write_text(json.dumps({"segments": [{"dur": 2.0, "shot_id": "S1"}], "work": str(tmp_path),
                             "overlays": [{"type": "location", "text": "Big Sur, California", "start": 0, "duration": 1}]}))
    args, _ = server.job_args("caption", {"plan": str(p), "tone": "funny"})
    assert args == ["caption", str(p), "--tone", "funny"]
    got = social.write(p)
    assert got["source"] == "local" and "Big Sur" in got["caption"] and 1 <= len(got["hashtags"]) <= social.MAX_TAGS
    assert (tmp_path / "r.caption.txt").read_text().strip().endswith(" ".join("#" + h for h in got["hashtags"]))
    assert json.loads((tmp_path / "r.social.json").read_text())["keywords"]
    assert social.checks({"caption": "x" * 200, "hashtags": list("abcdef")})[:2] == [
        "the first line is 200 characters: only about 125 show before \"more\"", "Instagram allows 5 hashtags"]


def test_look_previews_need_a_picture(api):
    call, reels = api
    plan = _reel(reels)
    assert call(f"/api/lookthumb?plan={plan}&slot=1&look=moody")[0] == 404   # no thumbnail: nothing to show, no crash
