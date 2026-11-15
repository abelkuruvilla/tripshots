"""Set one version everywhere a release reads it: the engine (pyproject, tripshots/__init__.py) and the desktop app
(package.json, Cargo.toml, tauri.conf.json).

The release workflow runs this with the version from the tag, so a release needs nothing but the tag; the versions
committed in the repository are only what local builds call themselves.

    python tools/set_version.py 0.2.0
    python tools/set_version.py --check 0.2.0   # fail when anything disagrees
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "pyproject.toml": (r'(?m)^version = "[^"]+"', 'version = "{v}"'),
    "tripshots/__init__.py": (r'__version__ = "[^"]+"', '__version__ = "{v}"'),
    "desktop/src-tauri/Cargo.toml": (r'(?m)^version = "[^"]+"', 'version = "{v}"'),
}
JSON = ("desktop/package.json", "desktop/src-tauri/tauri.conf.json")


def current() -> dict[str, str]:
    out = {}
    for f, (pat, _) in FILES.items():
        m = re.search(pat, (ROOT / f).read_text())
        out[f] = re.search(r'"([^"]+)"', m.group(0)).group(1) if m else "?"
    for f in JSON:
        out[f] = json.loads((ROOT / f).read_text())["version"]
    return out


def main(argv: list[str]) -> int:
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if len(args) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", args[0].lstrip("v")):
        print(__doc__)
        return 2
    v = args[0].lstrip("v")
    if check:
        bad = {f: x for f, x in current().items() if x != v}
        for f, x in bad.items():
            print(f"{f}: {x} (expected {v})")
        return 1 if bad else 0
    for f, (pat, rep) in FILES.items():
        p = ROOT / f
        p.write_text(re.sub(pat, rep.format(v=v), p.read_text(), count=1))
    for f in JSON:
        p = ROOT / f
        text = p.read_text()
        p.write_text(re.sub(r'("version"\s*:\s*)"[^"]+"', rf'\g<1>"{v}"', text, count=1))
    print(f"version {v}: " + ", ".join(current()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
