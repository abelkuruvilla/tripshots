# TripShots desktop app

A small [Tauri 2](https://tauri.app) shell (Rust + the system web view) with a Svelte UI. The work is done by the
TripShots engine, the same Python program as the `tripshots` command: the app starts it as
`tripshots serve` (a JSON API on 127.0.0.1 with a random token, see `tripshots/server.py`) and stops it when it
quits. Long work runs as engine jobs (`tripshots/jobs.py`), shared with the CLI and MCP agents.

```
desktop/
  src/                 Svelte UI (views/: Reels, Reel, Make, Ask, Styles, Activity, Settings, first-run Setup)
  src-tauri/src/       engine.rs: find / start / download + verify the engine;  integrate.rs: CLI and Claude
  src-tauri/tauri.conf.json   window, security policy, bundles, updater key
packaging/engine/      tripshots.spec (PyInstaller), package.py (bundle ffmpeg, smoke test, archive), manifest.py
.github/workflows/release.yml   tag vX.Y.Z -> engine + app for macOS/Windows/Linux in one GitHub release
```

## Develop

Needs Node 18+ and Rust (`rustup`). From `desktop/`:

```sh
npm install
TRIPSHOTS_ENGINE="$(which tripshots)" npm run tauri dev     # or a frozen engine: .../dist/tripshots/tripshots
```

Without `TRIPSHOTS_ENGINE` the app uses the engine it installed, then a `tripshots` on PATH (it must be a version
with `tripshots serve`; reinstall with `pip install .` after pulling). With none, it shows the first-run screen
that downloads the engine from the latest release.

Freeze the engine locally (from the repository root): `pip install pyinstaller` then
`pyinstaller packaging/engine/tripshots.spec --noconfirm` -> `dist/tripshots/tripshots`.

## How the engine is installed and updated

The app reads `https://github.com/<repo>/releases/latest/download/engine.json`:

```json
{"version": "0.2.0", "min_app": "0.2.0", "platforms": {"darwin-aarch64": {"url": "...", "sha256": "...", "size": 0, "signature": "..."}}}
```

It downloads this computer's archive, checks the SHA-256 and the minisign signature against the public key built
into the app (`plugins.updater.pubkey`, the same key that signs app updates), unpacks it into
`<app data>/engine/<version>/` and switches over only after all of that worked; the previous version is kept.
`min_app` stops an old app from installing an engine it doesn't understand. Settings > About checks for updates.

The release repository must be public (GitHub release downloads of a private repository need a login). To keep
the code private, publish releases to a separate public repository and build the app with
`TRIPSHOTS_ENGINE_MANIFEST=https://github.com/<owner>/<public-repo>/releases/latest/download/engine.json`, and point
`plugins.updater.endpoints` there too.

## Release

A tag is the whole release; nothing is run or committed locally. Any of these starts it:

- GitHub > Actions > release > **Run workflow**, version `0.2.0` (tags the selected branch as `v0.2.0`)
- GitHub > Releases > **Draft a new release**, new tag `v0.2.0` on `main`, Publish
- `git tag v0.2.0 && git push origin v0.2.0`

`release.yml` takes the version from the tag and writes it into the engine and the app inside CI
(`tools/set_version.py`), builds and smoke-tests the engine on 3 runners, signs and uploads it with `engine.json`,
builds the app (.dmg for Apple Silicon, .msi/.exe, .deb/.rpm/.AppImage) with `latest.json` for app
updates, and publishes the release with generated notes. About 30 minutes. Re-running it for the same version
rebuilds and replaces the files. An engine `X.Y.Z` declares `min_app: X.Y.0`, so patch releases of either side work
together; change the minor version when the engine API changes.

### Secrets (repository Settings > Secrets and variables > Actions)

| Secret | What |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | contents of `~/.tauri/tripshots.key` (created for this project; keep it safe: losing it means existing installs can't verify updates) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | contents of `~/.tauri/tripshots.key.password` |
| `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` | optional: sign and notarise the macOS app (needs an Apple Developer account). Without them the .dmg is unsigned and macOS asks users to allow it in System Settings > Privacy & Security |

Windows builds are unsigned until a code-signing certificate is added (Tauri: `bundle.windows.certificateThumbprint`
or a signing command); SmartScreen warns on unsigned installers.

## ffmpeg

Linux and Windows engines bundle static ffmpeg/ffprobe (BtbN builds, GPL, as separate programs with their licence;
source at ffmpeg.org) in `tripshots/bin/`, which the engine puts first on PATH. On macOS the engine uses Homebrew's
ffmpeg (`brew install ffmpeg`); Settings shows that hint when it's missing.
