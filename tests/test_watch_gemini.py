import threading
from types import SimpleNamespace as NS

import pytest

from tripshots import watch


class _Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class FakeClient:
    def __init__(self, missing=(), refuse=False):
        self.missing, self.refuse, self.calls = set(missing), refuse, []
        self.files = NS(upload=lambda file: NS(name="files/1", state=NS(name="ACTIVE")),
                        get=lambda name: NS(name=name, state=NS(name="ACTIVE")), delete=lambda name: None)
        self.models = NS(generate_content=self._gen, list=lambda: [])

    def _gen(self, model, contents, config):
        self.calls.append(model)
        if self.refuse:
            raise _Err(403, "PERMISSION_DENIED")
        if model in self.missing:
            raise _Err(404, f"404 NOT_FOUND. models/{model} is not found for API version v1")
        return NS(text='{"moments": [], "transitions": []}')


def _gemini(client, models):
    g = watch.Gemini.__new__(watch.Gemini)
    g.client, g.models, g._busy_until, g._lock = client, list(models), 0.0, threading.Lock()
    return g


def test_missing_model_switches_to_the_next_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(watch.time, "sleep", lambda s: pytest.fail("no waiting on a missing model"))
    c = FakeClient(missing={"gemini-flash-latest"})
    g = _gemini(c, ["gemini-flash-latest", "gemini-2.5-flash"])
    _, used = g.watch(tmp_path / "p.mp4", 5.0)
    assert used == "gemini-2.5-flash" and g.models == ["gemini-2.5-flash"]
    g.watch(tmp_path / "p.mp4", 5.0)
    assert c.calls == ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash"]  # not asked again


def test_no_model_left_stops_watching(tmp_path):
    g = _gemini(FakeClient(missing={"a", "b"}), ["a", "b"])
    with pytest.raises(watch.GeminiUnavailable):
        g.watch(tmp_path / "p.mp4", 5.0)


def test_refused_key_stops_watching(tmp_path):
    with pytest.raises(watch.GeminiUnavailable):
        _gemini(FakeClient(refuse=True), ["a"]).watch(tmp_path / "p.mp4", 5.0)


def test_resolve_picks_an_available_flash(monkeypatch):
    g = watch.Gemini.__new__(watch.Gemini)
    monkeypatch.setattr(g, "_available", lambda: ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                                                  "gemini-2.5-pro", "gemini-3-flash-preview"])
    assert g._resolve(["gemini-flash-latest", "gemini-2.5-flash"]) == ["gemini-2.5-flash"]
    assert g._resolve(["gemini-flash-latest"]) == ["gemini-2.5-flash"]   # plain > preview, newest version
    monkeypatch.setattr(g, "_available", lambda: None)                    # can't list: trust the settings
    assert g._resolve(["x", "y"]) == ["x", "y"]


def test_watch_media_stops_after_the_first_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "WATCH_DIR", tmp_path / "w")
    monkeypatch.setattr(watch, "available", lambda: (True, "ok"))
    monkeypatch.setattr(watch, "make_proxy", lambda src, dst, h=480: dst)
    client = FakeClient(missing={"a"})
    g = _gemini(client, ["a"])
    monkeypatch.setattr(watch, "Gemini", lambda model=None: g)
    media = [{"kind": "video", "sig": f"s{i}", "path": f"/x/{i}.mp4", "name": f"{i}.mp4", "duration": 3}
             for i in range(20)]
    assert watch.watch_media(media, tmp_path, workers=1) == {}
    assert len(client.calls) == 1   # 20 clips, one request
