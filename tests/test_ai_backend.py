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
