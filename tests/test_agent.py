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
