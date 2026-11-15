"""Write engine.json, the manifest the desktop app reads to install and update the engine.

    python packaging/engine/manifest.py --version 0.2.0 --repo owner/name --dir artifacts/ [--min-app 0.2.0]

Reads every <archive>.json (from package.py) and its <archive>.sig (minisign, from `tauri signer sign`) in --dir,
and points each platform at its file on the GitHub release for tag v<version>.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--repo", required=True, help="owner/name of the repository the release is on")
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--min-app", default=None,
                    help="oldest app version that understands this engine (default: this minor version, X.Y.0)")
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", type=Path, default=Path("engine.json"))
    a = ap.parse_args()
    platforms = {}
    for meta_file in sorted(a.dir.rglob("tripshots-engine-*.json")):
        meta = json.loads(meta_file.read_text())
        sig = next(a.dir.rglob(f"{meta['file']}.sig"), None)
        if sig is None:
            raise SystemExit(f"no signature for {meta['file']}: sign it with `tauri signer sign`")
        platforms[meta["platform"]] = {
            "url": f"https://github.com/{a.repo}/releases/download/v{a.version}/{meta['file']}",
            "sha256": meta["sha256"], "size": meta["size"], "signature": sig.read_text().strip()}
    if not platforms:
        raise SystemExit(f"no engine archives in {a.dir}")
    # an engine patch release works with any app of the same minor version: the API only changes in a minor one
    min_app = a.min_app or ".".join(a.version.split(".")[:2] + ["0"])
    man = {"version": a.version, "min_app": min_app, "notes": a.notes, "platforms": platforms}
    a.out.write_text(json.dumps(man, indent=2))
    print(f"{a.out}: engine {a.version} for {', '.join(sorted(platforms))}")


if __name__ == "__main__":
    main()
