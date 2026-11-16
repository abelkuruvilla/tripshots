"""Telemetry: nothing without a yes, only plain counts, scrubbed crashes, and what was sent kept for the user to see."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tripshots import telemetry as tm


@pytest.fixture()
def tel(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "STATE", tmp_path / "telemetry.json")
    for name in ("QUEUE", "SENT", "ERRORS"):
        monkeypatch.setattr(tm, name, tmp_path / "t" / f"{name.lower()}.jsonl")
    monkeypatch.setattr(tm, "PENDING", tmp_path / "t" / "pending")
    for k in ("DO_NOT_TRACK", "TRIPSHOTS_TELEMETRY"):
        monkeypatch.delenv(k, raising=False)
    got = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            got.append((self.path, body))
            code = 503 if H.down else 202
            self.send_response(code)
            self.end_headers()
    H.down = False
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("TRIPSHOTS_TELEMETRY_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    yield got, H
    srv.shutdown()


def test_nothing_is_kept_or_sent_without_a_yes(tel, monkeypatch):
    got, _ = tel
    assert tm.consent() is None and not tm.record("view", view="make") and tm.flush(force=True)["sent"] == 0
    tm.set_consent(False)
    assert not tm.record("view", view="make") and not tm.QUEUE.exists()
    tm.set_consent(True)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert not tm.record("view", view="make") and tm.status()["blocked"] == "DO_NOT_TRACK is set"
    monkeypatch.delenv("DO_NOT_TRACK")
    monkeypatch.delenv("TRIPSHOTS_TELEMETRY_URL")
    assert tm.blocked() and not tm.record("view", view="make")
    assert got == []


def test_only_plain_words_and_numbers_go_out(tel):
    got, _ = tel
    tm.set_consent(True)
    assert tm.record("command", cmd="make", ok=True, secs=tm.bucket(42), flags=["music", "/Users/x/a.mp4"],
                     hook="Day 3 in Yosemite", error=None)
    assert not tm.record("made_up", x=1)
    tm.record("view", view="/Users/me/Trips/Paris")   # a path never passes as a word
    assert tm.flush(force=True)["sent"] == 3   # consent, command, view
    evs = got[0][1]["events"]
    cmd = next(e for e in evs if e["name"] == "command")
    assert cmd["props"] == {"cmd": "make", "ok": True, "secs": 60, "flags": ["music"]}
    assert next(e for e in evs if e["name"] == "view")["props"] == {}
    assert {"install", "session", "v", "os", "osv", "arch"} <= set(cmd) and len(cmd["install"]) == 32
    assert "Yosemite" not in json.dumps(got) and "/Users" not in json.dumps(got)
    assert tm.sent_log()[0]["events"] == evs and not tm.QUEUE.read_text().strip()


def test_waiting_events_survive_a_collector_that_is_down(tel):
    got, H = tel
    tm.set_consent(True)
    H.down = True
    tm.record("edit", op="split")
    assert tm.flush(force=True)["sent"] == 0 and tm.status()["queued"] == 2
    H.down = False
    assert tm.flush(force=True)["sent"] == 2 and tm.status()["queued"] == 0


def test_crashes_are_scrubbed_and_grouped(tel):
    got, _ = tel
    tm.set_consent(True)
    home = tm.HOME_DIR

    def boom(n):
        raise ValueError(f"can't read {home}/Trips/Bali/IMG_0042.MOV for me@example.com "
                         f"see https://x.io/a?key=sk-ant-abcdefghijklmnopqrstuvwxyz0123 and/or retry {n}")
    try:
        boom(1)
    except ValueError as e:
        c1 = tm.crash(e, f"api:{home}/x")
    try:
        boom(2)
    except ValueError as e:
        c2 = tm.crash(e, "api:/x")
    for bad in ("Bali", "IMG_0042", "example.com", "sk-ant", "x.io", home):
        assert bad not in json.dumps(c1)
    assert "and/or retry 1" in c1["message"] and c1["fingerprint"] == c2["fingerprint"]
    assert c1["frames"][-1].startswith("tests/") is False and any("boom" in f for f in c1["frames"]) is False
    tm.flush(force=True)
    assert [e for e in got[0][1]["events"] if e["name"] == "crash"][0]["crash"]["type"] == "ValueError"
    assert tm.recent_errors()[-1]["message"] == c2["message"]


def test_own_frames_name_the_function(tel):
    from tripshots import planedit
    try:
        planedit.apply("/nonexistent/x.plan.json", [{"op": "nope"}])
    except Exception as e:
        c = tm.crash(e, "test")
    assert any(f.startswith("tripshots/planedit.py:") for f in c["frames"])
    assert all("/" not in f.split(":")[0][len("tripshots/"):] or f.startswith("<") for f in c["frames"])


def test_window_and_shell_crashes(tel):
    got, _ = tel
    tm.set_consent(True)
    c = tm.outside_crash({"type": "TypeError", "message": "x is undefined in /Users/a/b.json",
                          "frames": ["at render (http://127.0.0.1:5173/assets/index-abc.js:10:5)"]}, "ui")
    assert c["kind"] == "ui" and "<path>" in c["message"] and "127.0.0.1" not in c["frames"][0]
    tm.PENDING.mkdir(parents=True)
    (tm.PENDING / "1.json").write_text(json.dumps({"type": "panic", "message": "engine.rs: no engine",
                                                   "where": "engine_start"}))
    tm.flush(force=True)
    kinds = [e["crash"]["kind"] for e in got[0][1]["events"] if e["name"] == "crash"]
    assert kinds == ["ui", "shell"] and not list(tm.PENDING.glob("*.json"))


def test_a_bug_report_is_shown_first_and_sent_on_request(tel, monkeypatch):
    got, _ = tel
    p = tm.report_payload("The timeline froze", "", True)
    assert p["message"] == "The timeline froze" and p["email"] is None and "errors" in p["diagnostics"]
    assert tm.send_report("", "")["ok"] is False
    r = tm.send_report("The timeline froze", "a@b.co", False)   # needs no usage consent: the user pressed Send
    assert r["ok"] and got[-1][0] == "/v1/report" and got[-1][1]["email"] == "a@b.co"
    assert "diagnostics" not in got[-1][1]
    monkeypatch.delenv("TRIPSHOTS_TELEMETRY_URL")
    r = tm.send_report("The timeline froze")
    assert not r["ok"] and r["issue_url"].startswith(tm.ISSUES)


def test_reset_gives_a_new_id_and_the_app_server_routes(tel):
    from tripshots.server import telemetry_post
    tm.set_consent(True)
    a = tm.install_id()
    tm.reset_id()
    assert tm.install_id() != a
    assert telemetry_post({"events": [{"name": "view", "props": {"view": "reel"}}, {"name": "nope"}]}) == {"recorded": 1}
    telemetry_post({"crash": {"type": "Error", "message": "boom"}})
    assert telemetry_post({"consent": False})["consent"] is False and not tm.QUEUE.exists()


def test_command_line_counts_option_names_only(tel, monkeypatch):
    from tripshots import cli
    got, _ = tel
    tm.set_consent(True)
    monkeypatch.setattr("sys.argv", ["tripshots", "styles", "--json-nope", "/Users/x"])
    with pytest.raises(SystemExit):
        cli.main(["styles", "--nope"])
    cli.main(["styles"])
    evs = [e for _, b in got for e in b.get("events", [])]   # a command-line run sends now and then: this was the first
    cmd = [e for e in evs if e["name"] == "command"][-1]
    assert cmd["props"]["cmd"] == "styles" and cmd["props"]["ok"] is True and cmd["props"]["via"] == "cli"
    assert "/Users" not in json.dumps(evs)
