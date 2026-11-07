"""A stand-in for the Edits app's automation server (Edits for Mac isn't available in CI).

Tool names and arguments are invented: TripShots never relies on them, it maps them with `edits probe`.
Run: python tests/fake_edits.py PORT TOKEN
"""
import sys
import uuid

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

app = MCPServer("fake-edits")
STATE = {"project": None, "media": {}, "timeline": []}


@app.tool()
def appState() -> dict:
    """Current app state."""
    return {"signedIn": True, "project": STATE["project"]}


@app.tool()
def createProject(aspectRatio: str = "9:16") -> dict:
    """Create a new project."""
    STATE.update(project=uuid.uuid4().hex[:6], timeline=[])
    return {"id": STATE["project"], "aspectRatio": aspectRatio}


@app.tool()
def importMedia(path: str) -> dict:
    """Import a media file from disk into the project."""
    mid = uuid.uuid4().hex[:8]
    STATE["media"][mid] = path
    return {"id": mid}


@app.tool()
def addClipToTimeline(mediaId: str, startTime: float, duration: float, track: int = 0) -> dict:
    """Add an imported video clip to the timeline."""
    STATE["timeline"].append({"kind": "video", "file": STATE["media"][mediaId], "start": startTime, "dur": duration})
    return {"ok": True}


@app.tool()
def addText(text: str, startTime: float, duration: float, style: str = "classic") -> dict:
    """Add a text layer."""
    STATE["timeline"].append({"kind": "text", "text": text, "start": startTime, "dur": duration})
    return {"ok": True}


@app.tool()
def addAudio(mediaId: str, startTime: float, volume: float = 1.0) -> dict:
    """Add an audio clip (sound effect or music) to the timeline."""
    STATE["timeline"].append({"kind": "audio", "file": STATE["media"][mediaId], "start": startTime})
    return {"ok": True}


@app.tool()
def getTimeline() -> dict:
    """Everything on the timeline."""
    return {"items": STATE["timeline"]}


@app.tool()
def exportVideo(resolutionType: str, aspectRatio: str, quality: str) -> dict:
    """Export the project."""
    return {"started": True}


if __name__ == "__main__":
    import uvicorn
    port, token = int(sys.argv[1]), sys.argv[2]
    try:
        asgi = app.streamable_http_app(host="127.0.0.1")
    except TypeError:
        asgi = app.streamable_http_app()
    sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
    from tripshots.mcp_server import _BearerAuth
    uvicorn.run(_BearerAuth(asgi, token), host="127.0.0.1", port=port, log_level="warning")
