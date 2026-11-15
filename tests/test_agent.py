import asyncio
import json

from tripshots import jobs


def test_job_roundtrip():
    jid = jobs.start(["styles"], "styles", "test")
    st = jobs.wait(jid, 60)
    assert st["state"] == "done" and st["result"] is not None


def test_mcp_tools_registered():
    from tripshots import mcp_server
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in (tools.tools if hasattr(tools, "tools") else tools)}
    assert {"status", "find_footage", "make_reel", "edit_plan", "render_reel", "job_status", "people_add",
            "people_discover", "list_trips"} <= names


def test_mcp_status_runs():
    from tripshots import mcp_server
    out = json.loads(asyncio.run(mcp_server.status()))
    assert "footage_folders" in out and "people" in out


def test_ask_always_has_a_sound_when_a_learned_style_has_reference_reels(monkeypatch):
    from tripshots import ask, config
    style = {"recipes": [{"id": "r1", "source": "https://x/reel/A/"}, {"id": "r2", "source": "https://x/reel/B/"},
                         {"id": "r3", "source": "https://x/reel/C/", "unread": True}]}
    monkeypatch.setattr(config, "load_style", lambda name: style)
    assert ask.reference_sound("mine", "r2", []) == "https://x/reel/B/"          # the one the AI chose
    assert ask.reference_sound("mine", None, ["r1"]) == "https://x/reel/B/"      # else one not used recently
    assert ask.reference_sound("mine", "r9", ["r1", "r2"]) == "https://x/reel/A/"  # all used: still not silent
    assert ask.reference_sound(None, "r1", []) is None


def test_the_app_asks_for_a_finished_reel():
    from tripshots import server
    assert server.job_args("ask", {"request": "drone"})[0] == ["ask", "drone", "--render"]
    assert server.job_args("ask", {"request": "drone", "plan_only": True})[0] == ["ask", "drone"]
    args, _ = server.job_args("find", {"camera": "drone", "kinds": "video"})
    assert "--camera" in args and args[args.index("--camera") + 1] == "drone"
