"""The AIs TripShots can use for its creative calls, and the order "automatic" tries them in.

Standard library only: the app's server reads this on every visit to Settings. The clients themselves are in
ai.py. Most providers speak the OpenAI chat-completions protocol, so one client (ai.OpenAIChat) serves them all.

Settings in ~/.tripshots/.env:
    TRIPSHOTS_AI_ORDER=claude-cli,minimax,openai,...   the order automatic tries them in (unlisted ones go last)
    TRIPSHOTS_AI_OFF=deepseek,...                      set up, but not used by automatic
    <key_env>=...                                      each provider's key
    <model_env>=...                                    each provider's model (else `model`)
"""
from __future__ import annotations

import os

# id -> what it is. kind: cli (Claude Code), anthropic (Messages API, or compatible), openai (chat completions).
# think: extra answer room for models that reason before they answer (their thinking counts against the limit).
# vision: can look at pictures (judging footage needs it; text-only ones still write captions and choose effects).
PROVIDERS: dict[str, dict] = {
    "claude-cli": {"name": "Claude", "kind": "cli", "sub": "Your Claude Pro or Max plan, no key needed",
                   "model_env": "TRIPSHOTS_CLAUDE_MODEL", "model": "", "vision": True,
                   "site": "https://docs.claude.com/en/docs/claude-code/setup"},
    "api": {"name": "Claude API", "kind": "anthropic", "sub": "An Anthropic API key, pay per use",
            "key_env": "ANTHROPIC_API_KEY", "model_env": "TRIPSHOTS_MODEL", "model": "claude-sonnet-5-5",
            "vision": True, "site": "https://console.anthropic.com/settings/keys"},
    "minimax": {"name": "MiniMax", "kind": "anthropic", "sub": "An API key, pay as you go",
                "key_env": "MINIMAX_API_KEY", "model_env": "TRIPSHOTS_MINIMAX_MODEL", "model": "MiniMax-M3",
                "base_env": "MINIMAX_BASE_URL", "base": "https://api.minimax.io/anthropic", "vision": True,
                "site": "https://platform.minimax.io"},
    "openai": {"name": "OpenAI", "kind": "openai", "sub": "ChatGPT's models, an API key, pay per use",
               "key_env": "OPENAI_API_KEY", "model_env": "TRIPSHOTS_OPENAI_MODEL", "model": "gpt-5",
               "base": "https://api.openai.com/v1", "tokens": "max_completion_tokens", "think": 8000, "vision": True,
               "site": "https://platform.openai.com/api-keys"},
    "gemini": {"name": "Google Gemini", "kind": "openai", "sub": "A Google AI Studio key, with a free tier",
               "key_env": "GEMINI_API_KEY", "alt_key_env": "GOOGLE_API_KEY", "model_env": "TRIPSHOTS_GEMINI_MODEL",
               "model": "gemini-flash-latest", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "think": 4000,
               "vision": True, "site": "https://aistudio.google.com/apikey"},
    "xai": {"name": "xAI Grok", "kind": "openai", "sub": "An xAI API key, pay per use",
            "key_env": "XAI_API_KEY", "model_env": "TRIPSHOTS_XAI_MODEL", "model": "grok-4",
            "base": "https://api.x.ai/v1", "vision": True, "site": "https://console.x.ai"},
    "mistral": {"name": "Mistral", "kind": "openai", "sub": "A Mistral API key, with a free tier",
                "key_env": "MISTRAL_API_KEY", "model_env": "TRIPSHOTS_MISTRAL_MODEL", "model": "mistral-medium-latest",
                "base": "https://api.mistral.ai/v1", "vision": True, "site": "https://console.mistral.ai/api-keys"},
    "openrouter": {"name": "OpenRouter", "kind": "openai", "sub": "One key for hundreds of models",
                   "key_env": "OPENROUTER_API_KEY", "model_env": "TRIPSHOTS_OPENROUTER_MODEL", "model": "openrouter/auto",
                   "base": "https://openrouter.ai/api/v1", "vision": True, "site": "https://openrouter.ai/keys"},
    "deepseek": {"name": "DeepSeek", "kind": "openai", "sub": "A DeepSeek API key, low cost; text only",
                 "key_env": "DEEPSEEK_API_KEY", "model_env": "TRIPSHOTS_DEEPSEEK_MODEL", "model": "deepseek-chat",
                 "base": "https://api.deepseek.com/v1", "vision": False, "site": "https://platform.deepseek.com/api_keys"},
    "ollama": {"name": "Ollama", "kind": "openai", "sub": "A model running on this computer, free and private",
               "model_env": "TRIPSHOTS_OLLAMA_MODEL", "model": "", "base_env": "OLLAMA_BASE_URL",
               "base": "http://127.0.0.1:11434/v1", "vision": True, "local": True, "site": "https://ollama.com/download"},
}
DEFAULT_ORDER = list(PROVIDERS)


def _ids(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip() in PROVIDERS]


def order() -> list[str]:
    """Every provider, in the order automatic tries them: the saved order, then any it doesn't list yet."""
    saved = list(dict.fromkeys(_ids(os.environ.get("TRIPSHOTS_AI_ORDER"))))
    return saved + [p for p in DEFAULT_ORDER if p not in saved]


def off() -> set[str]:
    return set(_ids(os.environ.get("TRIPSHOTS_AI_OFF")))


def key(pid: str) -> str:
    p = PROVIDERS[pid]
    if not p.get("key_env"):
        return ""
    return os.environ.get(p["key_env"]) or os.environ.get(p.get("alt_key_env") or "") or ""


def model(pid: str) -> str:
    p = PROVIDERS[pid]
    v = os.environ.get(p.get("model_env", "")) or ""
    if pid == "api" and v.lower().startswith("minimax"):   # (TRIPSHOTS_MODEL once named MiniMax's model too)
        v = ""
    return v or p.get("model", "")


def base(pid: str) -> str:
    p = PROVIDERS[pid]
    return (os.environ.get(p.get("base_env", "")) or p.get("base", "")).rstrip("/")


def configured(pid: str) -> bool:
    """Set up enough to try (a key, or for Ollama a model chosen). Claude Code is checked in ai.py (its login)."""
    p = PROVIDERS[pid]
    if p["kind"] == "cli":
        return True
    if p.get("local"):
        return bool(os.environ.get(p["model_env"]))
    return bool(key(pid))


def settings_keys() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(secret settings, plain settings) the app may write for the providers."""
    secrets = tuple(dict.fromkeys(v for p in PROVIDERS.values() for k in ("key_env", "alt_key_env")
                                  if (v := p.get(k))))
    plain = tuple(dict.fromkeys(v for p in PROVIDERS.values() for k in ("model_env", "base_env") if (v := p.get(k))))
    return secrets, plain + ("TRIPSHOTS_AI_ORDER", "TRIPSHOTS_AI_OFF")
