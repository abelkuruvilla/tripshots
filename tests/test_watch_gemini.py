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
    g.pacer = watch.Pacer(rpm=1e6)  # no pacing unless a test is about it
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


def _quota_err(quota_id, delay="34s", limit="10"):
    return _Err(429, "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota', "
                     "'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': "
                     f"[{{'quotaId': '{quota_id}', 'quotaValue': '{limit}'}}]}}, "
                     f"{{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '{delay}'}}]}}}}")


class LimitedClient(FakeClient):
    def __init__(self, errors):
        super().__init__()
        self.errors = list(errors)

    def _gen(self, model, contents, config):
        self.calls.append(model)
        if self.errors:
            raise self.errors.pop(0)
        return NS(text='{"moments": [], "transitions": []}')


def test_rate_limit_waits_for_gemini_and_slows_down(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(watch.time, "sleep", slept.append)
    c = LimitedClient([_quota_err("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "34s", "5")] * 2)
    g = _gemini(c, ["gemini-2.5-flash"])
    _, used = g.watch(tmp_path / "p.mp4", 5.0)
    assert used == "gemini-2.5-flash" and len(c.calls) == 3          # waited twice, then it worked
    assert any(33 <= s <= 35 for s in slept)                        # Gemini's own retry time
    assert g.pacer.max_rpm <= 4.5 and g.pacer.rpm < 4.5             # learned the key's limit (5 a minute)


def test_daily_quota_switches_model_then_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(watch.time, "sleep", lambda s: None)
    day = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    c = LimitedClient([_quota_err(day)])
    g = _gemini(c, ["gemini-flash-latest", "gemini-2.5-flash-lite"])
    _, used = g.watch(tmp_path / "p.mp4", 5.0)
    assert used == "gemini-2.5-flash-lite" and g.models == ["gemini-2.5-flash-lite"]
    c.errors = [_quota_err(day)]
    with pytest.raises(watch.GeminiUnavailable, match="daily quota"):
        g.watch(tmp_path / "p.mp4", 5.0)


def test_pacer_spaces_requests(monkeypatch):
    now = [1000.0]
    slept = []
    monkeypatch.setattr(watch.time, "time", lambda: now[0])
    monkeypatch.setattr(watch.time, "sleep", lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    p = watch.Pacer(rpm=12)
    for _ in range(4):
        p.wait()
    assert slept == pytest.approx([5.0, 5.0, 5.0])                  # 12 a minute = one every 5 s
    assert watch._quota(Exception("503 UNAVAILABLE")) is None
