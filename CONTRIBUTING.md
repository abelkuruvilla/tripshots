# Contributing to TripShots

Thanks for helping. Bug reports, ideas, styles, docs and code are all welcome.

## Ground rules

- **TripShots edits people's own footage. It never generates footage.** Features that synthesise frames are out of scope.
- **Local first.** Anything that sends data off the computer must be optional, documented in
  [docs/privacy.md](docs/privacy.md), and fail soft when offline.
- **Never use licence-restricted media.** No NC/ND/SA audio, no fonts or models without a redistribution-friendly licence.
- Be kind: see the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

```bash
git clone <your fork> tripshots && cd tripshots
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,export]"
sudo apt install ffmpeg        # or brew install ffmpeg
tripshots doctor
```

## Tests

```bash
pytest -m "not slow"           # seconds: unit tests with synthetic footage
pytest                         # also renders one real reel end to end (~2 min)
python tools/gen_docs.py --check
```

The tests make their own footage with ffmpeg and use a throw-away `TRIPSHOTS_HOME`, so they never touch your
library. They don't need network access, an AI backend, face models or GPUs: network features are stubbed
(`tests/tripgen.py` seeds place outlines; face tests use fake embeddings). Please add a test with every fix or
feature.

## Code layout

See [docs/architecture.md](docs/architecture.md) for the pipeline and what each module does. A few conventions:

- Every command prints its result as JSON on stdout and logs to stderr via `util.log` (prefix `[tripshots]`). The
  app and the MCP jobs parse this, so keep it.
- Cache expensive work by file content (`library.content_key`) or by inputs, and bump a version constant when the
  cached format changes (`FACES_VERSION`, `RENDER_VERSION`, `PROMPT_VERSION`, …).
- Optional dependencies are imported inside the function that needs them, with a clear message when missing.
- Plans must stay beat-aligned: durations are whole frames at 30 fps. Use `planedit.py` for programmatic edits.
- Line length 120. Prefer plain, specific names and short docstrings that say *why*.

## Common contributions

- **A style:** add `tripshots/styles/<name>.yaml` (only the keys that differ from `DEFAULT_STYLE` in `config.py`),
  describe it in `docs/making-reels.md`, and check `tripshots make … -s <name> --dry-run` on real footage.
- **A transition:** implement it in `motion.py` (`apply_transition`), add it to the palette options and to
  `planedit.TRANSITIONS`, document it in `docs/look-and-motion.md` and `docs/plan-format.md`.
- **A command or option:** add it in `cli.build_parser`, then run `python tools/gen_docs.py`.
- **An MCP tool:** add it in `mcp_server.py` with a docstring written for an agent (what it does, when to use it,
  what each parameter means), then run `python tools/gen_docs.py`. Heavy work goes through `jobs.start`.

## Pull requests

1. Open an issue first for anything big, so we can agree on the approach.
2. Keep PRs focused; update docs and `CHANGELOG.md` (under *Unreleased*) with user-visible changes.
3. Make sure `pytest` and `python tools/gen_docs.py --check` pass.
4. For anything visual (grading, text, transitions), attach a storyboard or a few frames before and after.

By contributing you agree that your contribution is licensed under the project's [MIT licence](LICENSE).
