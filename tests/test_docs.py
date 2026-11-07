"""Every relative link in the docs points at a file (and heading) that exists."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = [p for p in ROOT.rglob("*.md") if not any(x in p.parts for x in (".venv", "node_modules", ".pytest_cache"))]


def _slug(h: str) -> str:
    h = re.sub(r"[`*_]", "", h.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def _anchors(p: Path) -> set[str]:
    text, out = p.read_text(), set()
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for h in re.findall(r"(?m)^#{1,6} (.+)$", text):
        out.add(_slug(h))
    return out


def test_relative_links_resolve():
    bad = []
    for p in MD:
        text = re.sub(r"```.*?```", "", p.read_text(), flags=re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"^[a-z]+:", target) or target.startswith("<"):
                continue
            path, _, anchor = target.partition("#")
            dest = (p.parent / path).resolve() if path else p
            if not dest.exists():
                bad.append(f"{p.relative_to(ROOT)} -> {target}")
            elif anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
                bad.append(f"{p.relative_to(ROOT)} -> {target} (no such heading)")
    assert not bad, "\n".join(bad)
