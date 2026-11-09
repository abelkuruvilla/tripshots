"""Agent skills that work well next to TripShots (`tripshots skills`).

TripShots is often driven by an AI agent (Claude Code, Codex, Cursor: see skills/tripshots/SKILL.md and the MCP
server). These skills teach that agent the video tools around it. TripShots itself uses HyperFrames (route maps,
motion text) and borrows ideas from the others, but runs without any of them installed.
Install them with the `skills` installer (npx skills add OWNER/REPO), which puts them where your agent looks.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

COMPANIONS = [
    {"name": "hyperframes", "source": "heygen-com/hyperframes", "license": "Apache-2.0",
     "marker": ["hyperframes", "hyperframes-registry"],
     "what": "HTML-to-video: titles, captions, transitions, maps and ~450 registry blocks. TripShots renders its "
             "route maps and motion text with it; with the skill an agent can build custom title cards, end cards "
             "or overlays for a reel."},
    {"name": "remotion", "source": "remotion-dev/skills", "license": "Remotion licence (free for individuals and "
     "small teams; companies need a paid licence)", "marker": ["remotion-best-practices", "remotion"],
     "what": "React-based video. Useful for an agent building its own intro/outro or data animations; TripShots "
             "doesn't depend on it."},
    {"name": "one-take", "source": "KaranO-Dev/one-take-skill", "license": "MIT", "marker": ["one-take"],
     "what": "Launch/promo videos on HyperFrames with a strict QA pass. TripShots' `qa` checks follow it; the skill "
             "helps an agent make a matching promo or trailer around a reel."},
    {"name": "lemo-opuscar", "source": "lemomo-ai/lemo-opuscar", "license": "MIT", "marker": ["lemo-opuscar"],
     "what": "Short films drawn in code in 43 styles, with a director's guide and self-checks. TripShots' "
             "DIRECTOR.md follows its pattern; the skill can make an illustrated intro or map-style opener."},
]
DIRS = [Path.home() / ".claude" / "skills", Path.cwd() / ".claude" / "skills", Path.home() / ".agents" / "skills",
        Path.cwd() / ".agents" / "skills", Path.home() / ".codex" / "skills"]


def installed(c: dict) -> str | None:
    for d in DIRS:
        for m in c["marker"]:
            if (d / m / "SKILL.md").exists():
                return str(d / m)
    return None


def status() -> list[dict]:
    return [{**{k: c[k] for k in ("name", "source", "license", "what")}, "installed": installed(c),
             "install": f"npx skills add {c['source']}"} for c in COMPANIONS]


def install(name: str) -> int:
    """Run the skills installer for one companion (interactive: it asks which agent to install for)."""
    c = next((c for c in COMPANIONS if c["name"] == name), None)
    if c is None:
        raise SystemExit(f"unknown skill {name!r}; choose from: {', '.join(x['name'] for x in COMPANIONS)}")
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("needs Node.js (npx): `brew install node`, then run again")
    return subprocess.call([npx, "-y", "skills", "add", c["source"]])
