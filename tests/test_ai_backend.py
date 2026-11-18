import json
import subprocess

import pytest

from tripshots import ai


def _fake_run(outputs):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = outputs(cmd)
        return subprocess.CompletedProcess(cmd, out.get("rc", 0), out.get("stdout", ""), out.get("stderr", ""))
    return run, calls


def test_not_logged_in_stops_at_once(monkeypatch):
    reply = {"is_error": True, "subtype": "success", "result": "Not logged in · Please run /login"}
    run, calls = _fake_run(lambda cmd: {"rc": 1, "stdout": json.dumps(reply)})
    monkeypatch.setattr(ai, "run", run)
    b = ai.ClaudeCLI()
    with pytest.raises(ai.AIAuthError, match="claude auth login"):
        b.ask("hi")
    with pytest.raises(ai.AIAuthError):
        b.ask("again")
    assert len(calls) == 1  # the second call never reached the CLI


def test_other_errors_show_the_message_only(monkeypatch):
    run, _ = _fake_run(lambda cmd: {"rc": 1, "stdout": json.dumps({"is_error": True, "result": "Overloaded"})})
    monkeypatch.setattr(ai, "run", run)
    with pytest.raises(ai.ReelError) as e:
        ai.ClaudeCLI().ask("hi")
    assert str(e.value) == "claude CLI error: Overloaded" and not isinstance(e.value, ai.AIAuthError)


def test_get_backend_checks_the_login_first(monkeypatch):
    monkeypatch.setattr(ai, "which", lambda name: "/usr/bin/claude")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(ai.ClaudeCLI, "login_status", staticmethod(lambda: {"loggedIn": False}))
    with pytest.raises(ai.AIAuthError):
        ai.get_backend("claude-cli")
    monkeypatch.setattr(ai.ClaudeCLI, "login_status", staticmethod(lambda: {"loggedIn": True}))
    assert isinstance(ai.get_backend("claude-cli"), ai.ClaudeCLI)
    monkeypatch.setattr(ai.ClaudeCLI, "login_status", staticmethod(lambda: None))  # older CLI: can't tell
    assert isinstance(ai.get_backend("claude-cli"), ai.ClaudeCLI)


def test_scoring_stops_after_an_auth_error(monkeypatch, tmp_path):
    import tripshots.text as text
    shots = [{"id": f"S{i:03d}", "sig": f"s{i}", "t0": 0.0, "kind": "photo", "w": 1, "h": 1, "thumb": "x",
              "metrics": {"bright": 0.5}} for i in range(1, 25)]
    monkeypatch.setattr(text, "contact_sheets",
                        lambda ss, d, **k: [(tmp_path / f"s{n}.jpg", [s["id"] for s in ss[n:n + 8]])
                                            for n in range(0, len(ss), 8)])
    reply = {"is_error": True, "result": "Not logged in · Please run /login"}
    run, calls = _fake_run(lambda cmd: {"rc": 1, "stdout": json.dumps(reply)})
    monkeypatch.setattr(ai, "run", run)
    with pytest.raises(ai.AIAuthError):
        ai.score_shots(shots, ai.ClaudeCLI(), tmp_path, workers=1)
    assert len(calls) == 1  # 3 sheets, no retries: one call only


class _B(ai.Backend):
    def __init__(self, name, fail=False):
        self.name, self.fail, self.calls = name, fail, 0

    def ask(self, prompt, images=None, max_tokens=4000):
        self.calls += 1
        if self.fail:
            raise ai.AIAuthError(f"{self.name} refused")
        return f"{self.name} says hi"


def test_chain_moves_on_when_one_refuses():
    a, b = _B("claude-cli", fail=True), _B("minimax")
    c = ai.Chain([a, b])
    assert c.ask("x") == "minimax says hi" and c.name == "minimax"
    assert c.ask("y") == "minimax says hi" and a.calls == 1   # the refusing one isn't asked again
    with pytest.raises(ai.AIAuthError):
        ai.Chain([_B("a", True), _B("b", True)]).ask("z")


def test_auto_skips_a_logged_out_claude_for_minimax(monkeypatch):
    monkeypatch.setattr(ai, "which", lambda name: "/usr/bin/claude")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    monkeypatch.setattr(ai.ClaudeCLI, "login_status", staticmethod(lambda: {"loggedIn": False}))
    b = ai.get_backend("auto")
    assert b.name == "minimax" and b.model == "MiniMax-M3"
    monkeypatch.setattr(ai.ClaudeCLI, "login_status", staticmethod(lambda: {"loggedIn": True}))
    b = ai.get_backend("auto")
    assert isinstance(b, ai.Chain) and [x.name for x in b.backends] == ["claude-cli", "minimax"]
    with pytest.raises(ai.AIAuthError):  # asked for Claude Code by name: no silent switch
        monkeypatch.setattr(ai.ClaudeCLI, "login_status", staticmethod(lambda: {"loggedIn": False}))
        ai.get_backend("claude-cli")


def test_a_spent_usage_limit_stops_at_once(monkeypatch):
    reply = {"is_error": True, "result": "You've hit your session limit · resets 7:20am (America/Chicago)"}
    run, calls = _fake_run(lambda cmd: {"rc": 1, "stdout": json.dumps(reply)})
    monkeypatch.setattr(ai, "run", run)
    b = ai.ClaudeCLI()
    with pytest.raises(ai.AILimitError, match="resets 7:20am"):
        b.ask("hi")
    with pytest.raises(ai.AILimitError):
        b.ask("again")
    assert len(calls) == 1


def test_a_caption_never_puts_a_place_in_the_wrong_state():
    facts = [{"landmark": "Half Dome", "place": "Yosemite National Park, California", "region": "California"},
             {"landmark": "Old Faithful", "region": "Wyoming"}, {"place": "Lake McDonald, Montana", "region": "Montana"},
             {"region": "Utah"}, {}]
    bad = "Washington redwoods, Utah's Half Dome and Old Faithful, then California's Lake McDonald.\nWhich one first?"
    assert {(n, t) for n, _, t in ai.misplaced(bad, facts)} == {
        ("Half Dome", "California"), ("Old Faithful", "Wyoming"), ("Lake McDonald", "Montana")}
    good = "From Half Dome in California to Old Faithful in Wyoming, then Utah.\nWhich one first?"
    assert not ai.misplaced(good, facts) and not ai.misplaced("Half Dome at sunrise, Utah at dusk", facts)

    class Fixes(ai.Backend):
        name, asked = "fixes", 0

        def ask(self, prompt, images=None, max_tokens=4000):
            self.asked += 1
            return good

    class Stubborn(Fixes):
        def ask(self, prompt, images=None, max_tokens=4000):
            self.asked += 1
            return bad
    b = Fixes()
    assert ai.true_caption(b, good, facts) == good and b.asked == 0     # nothing wrong: nothing asked
    assert ai.true_caption(b, bad, facts) == good and b.asked == 1      # one correction
    left = ai.true_caption(Stubborn(), bad, facts)                      # still wrong: the sentence goes, the states stay
    assert not ai.misplaced(left, facts) and "Half Dome" not in left and left.endswith("Which one first?")
    assert left.startswith("California, Wyoming, Montana and Utah.")


def test_the_copywriter_is_told_which_shot_the_sunset_belongs_to():
    """'The Teton Range at dusk' when the dusk was filmed in Utah: the light is listed with its own shot."""
    class Reads:
        name, prompt = "stub", ""

        def ask(self, prompt, images=None, max_tokens=300):
            Reads.prompt = prompt
            return '{"hooks": [{"text": "One fall out west"}], "cta": "", "caption": "", "hashtags": []}'
    plan = {"segments": [{"shot_id": "A", "role": "hook"}, {"shot_id": "B", "role": "ending"}]}
    by_id = {"A": {"ai": {"note": "peaks over the sage", "time_of_day": "midday"}},
             "B": {"ai": {"note": "rock silhouettes", "time_of_day": "sunset"}}}
    facts = [{"landmark": "Teton Range", "region": "Wyoming"}, {"region": "Utah"}]
    from tripshots.config import load_style
    ai.write_story_copy(Reads(), plan, by_id, load_style("beat-montage"), extra={"facts": facts})
    assert "1. landmark: Teton Range; region: Wyoming\n" in Reads.prompt
    assert "2. region: Utah (sunset)" in Reads.prompt


def test_a_line_trails_off_with_three_dots():
    assert ai.clean_line("POV: Someone asks what I dream about....") == "POV: Someone asks what I dream about..."
    assert ai.clean_line("wait for it….") == "wait for it..." and ai.clean_line("One. Two... three") == "One. Two... three"


def test_every_wording_of_a_spent_limit_is_recognised():
    for msg in ("You've hit your 5-hour limit · resets 1:10am (America/Chicago)",
                "You've hit your session limit · resets 7:20am (America/Chicago)",
                "Claude AI usage limit reached|1712345678", "Opus weekly limit reached ∙ resets Mon 9am",
                "5-hour limit reached · resets 3pm", "Your limit will reset at 4pm"):
        assert ai.is_limit(msg), msg
    for msg in ("claude CLI error: overloaded", "Invalid API key · Please run /login", "the image limit is 20 files"):
        assert not ai.is_limit(msg), msg


def test_a_spent_claude_hands_over_to_minimax_once_even_from_several_threads(monkeypatch):
    import threading
    reply = {"is_error": True, "result": "You've hit your 5-hour limit · resets 1:10am (America/Chicago)"}
    gate = threading.Barrier(3)

    def answer(cmd):
        gate.wait(timeout=5)   # three sheets asked at once, all refused together
        return {"rc": 1, "stdout": json.dumps(reply)}
    run, calls = _fake_run(answer)
    monkeypatch.setattr(ai, "run", run)
    mm = _B("minimax")
    c = ai.Chain([ai.ClaudeCLI(), mm])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        got = list(ex.map(lambda k: c.ask(f"sheet {k}"), range(3)))
    assert got == ["minimax says hi"] * 3 and c.name == "minimax" and len(calls) == 3 and mm.calls == 3
    assert c.ask("next") == "minimax says hi" and len(calls) == 3   # Claude isn't asked again this run


_KEYS = ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
         "MISTRAL_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "TRIPSHOTS_OLLAMA_MODEL", "TRIPSHOTS_AI_ORDER",
         "TRIPSHOTS_AI_OFF", "TRIPSHOTS_BACKEND", "TRIPSHOTS_OPENAI_MODEL", "CLAUDE_CODE_OAUTH_TOKEN")


def _clean(monkeypatch):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ai, "which", lambda name: None)   # no Claude Code here


def test_automatic_follows_the_chosen_order_and_leaves_out_the_ones_switched_off(monkeypatch):
    from tripshots import aiproviders as P
    _clean(monkeypatch)
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.setenv(k, "k")
    b = ai.get_backend("auto")
    assert [x.name for x in b.backends] == ["minimax", "openai", "gemini", "deepseek"]   # the default order
    monkeypatch.setenv("TRIPSHOTS_AI_ORDER", "gemini,deepseek,bogus,openai")
    monkeypatch.setenv("TRIPSHOTS_AI_OFF", "openai")
    assert P.order()[:3] == ["gemini", "deepseek", "openai"] and len(P.order()) == len(P.PROVIDERS)
    assert [x.name for x in ai.get_backend("auto").backends] == ["gemini", "deepseek", "minimax"]
    assert ai.get_backend("openai").name == "openai"            # asked for by name: used even when off for automatic
    monkeypatch.setenv("TRIPSHOTS_OLLAMA_MODEL", "qwen2.5vl")   # a local model needs no key, only a name
    assert "ollama" in [x.name for x in ai.get_backend("auto").backends]
    with pytest.raises(ai.ReelError):
        ai.get_backend("nonsense")


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def _http(monkeypatch, answers, seen):
    import io
    import urllib.error
    import urllib.request

    def urlopen(req, timeout=None):
        seen.append({"url": req.full_url, "body": json.loads(req.data), "auth": req.get_header("Authorization")})
        code, body = answers.pop(0)
        if code != 200:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(json.dumps(body).encode()))
        return _Resp(body)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ai.OpenAIChat, "RETRIES", (0.0, 0.0))


def test_openai_style_services_get_pictures_and_hand_over_when_spent(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    img = tmp_path / "s.jpg"
    img.write_bytes(b"\xff\xd8jpeg")
    seen = []
    ok = {"choices": [{"message": {"content": "fine"}}]}
    _http(monkeypatch, [(429, {"error": {"message": "slow down"}}), (200, ok)], seen)
    b = ai.make("openai")
    assert b.ask("judge", [img], max_tokens=100) == "fine" and len(seen) == 2    # a busy answer is waited out
    req = seen[0]
    assert req["url"] == "https://api.openai.com/v1/chat/completions" and req["auth"] == "Bearer sk-test"
    assert req["body"]["model"] == "gpt-5" and req["body"]["max_completion_tokens"] == 100 + 8000
    parts = req["body"]["messages"][0]["content"]
    assert parts[0]["text"] == "judge" and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # a spent quota hands over; a refused key too; neither is asked again
    _http(monkeypatch, [(429, {"error": {"code": "insufficient_quota"}})], seen)
    with pytest.raises(ai.AILimitError):
        b.ask("x")
    with pytest.raises(ai.AILimitError):
        b.ask("x again")
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    m = ai.make("mistral")
    _http(monkeypatch, [(401, {"message": "Unauthorized"})], seen)
    with pytest.raises(ai.AIAuthError):
        m.ask("x")
    # in a chain the next AI carries on
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    _http(monkeypatch, [(402, {"error": "no credit"}), (200, ok)], seen)
    c = ai.Chain([ai.make("mistral"), ai.make("gemini")])
    assert c.ask("y") == "fine" and c.name == "gemini" and "generativelanguage" in seen[-1]["url"]


def test_a_text_only_ai_lets_the_next_one_judge_pictures(monkeypatch, tmp_path):
    img = tmp_path / "s.jpg"
    img.write_bytes(b"x")
    words, eyes = _B("deepseek"), _B("gemini")
    words.vision = False
    c = ai.Chain([words, eyes])
    assert c.ask("caption please") == "deepseek says hi"
    assert c.ask("judge", [img]) == "gemini says hi" and c.name == "gemini"
    assert c.ask("caption again") == "deepseek says hi" and (words.calls, eyes.calls) == (2, 1)
    blind = ai.Chain([words])
    with pytest.raises(ai.ReelError, match="look at pictures"):
        blind.ask("judge", [img])


def test_the_app_saves_the_order_and_shows_every_ai(monkeypatch, tmp_path):
    from tripshots import config, server
    _clean(monkeypatch)
    from tripshots import util
    monkeypatch.setattr(util, "which", lambda name: None)
    for k in ("TRIPSHOTS_AI_ORDER", "TRIPSHOTS_AI_OFF", "TRIPSHOTS_XAI_MODEL"):   # (written into the environment)
        monkeypatch.setenv(k, "")
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(server, "status", lambda: {})
    monkeypatch.setenv("XAI_API_KEY", "k")
    server.save_settings({"ai_order": ["xai", "openai", "evil;rm"], "ai_off": ["openai"],
                          "env": {"TRIPSHOTS_XAI_MODEL": "grok-4-fast"}})
    env = (tmp_path / ".env").read_text()
    assert "TRIPSHOTS_AI_ORDER=xai,openai\n" in env and "TRIPSHOTS_AI_OFF=openai" in env and "evil" not in env
    st = server.ai_status()
    assert st["every"][:2] == ["xai", "openai"] and st["order"] == ["xai"] and st["using"] == "xai"
    x = st["providers"]["xai"]
    assert x["model"] == "grok-4-fast" and x["state"] == "ready" and x["on"] and not st["providers"]["openai"]["on"]
    assert "XAI_API_KEY" in server.SECRETS and server._shown("XAI_API_KEY") is True   # a key is never shown back
