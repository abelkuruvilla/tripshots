# Configuration

Settings live in `~/.tripshots/.env` (created by `install.sh` from [`.env.example`](../.env.example); the app's
Settings tab writes it too). A `.env` in the current folder is read first. Real environment variables always win.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `TRIPSHOTS_BACKEND` | `auto` | AI backend: `auto`, `claude-cli`, `api`, `minimax`, `none` ([AI backends](ai-backends.md)) |
| `TRIPSHOTS_CLAUDE_MODEL` | Claude Code's default | Model for the `claude-cli` backend (`sonnet`, `opus`, …) |
| `TRIPSHOTS_MINIMAX_MODEL` | `MiniMax-M3` | Model for the `minimax` backend |
| `TRIPSHOTS_MODEL` | a Claude model | Model for the `api` backend (a `MiniMax-…` value still sets MiniMax's model, as before) |
| `CLAUDE_CODE_OAUTH_TOKEN` | | A long-lived Claude Code token from `claude setup-token`, for setups where Claude Code's own login isn't reachable |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | | For the `api` backend |
| `MINIMAX_API_KEY`, `MINIMAX_BASE_URL` | | For the `minimax` backend |
| `GEMINI_API_KEY` | | Optional Gemini video watching |
| `TRIPSHOTS_WATCH` | `auto` | `auto` (on when a key is set), `gemini`, `off` |
| `TRIPSHOTS_GEMINI_MODEL`, `TRIPSHOTS_GEMINI_FALLBACK` | `gemini-flash-latest`, `gemini-2.5-flash` | Gemini models |
| `TRIPSHOTS_GEMINI_RPM` | 10 | Gemini requests a minute. TripShots slows down further when Gemini reports a lower limit; raise it on a paid key |
| `TRIPSHOTS_FOOTAGE` | the app's recent folders | Folders `find`, `trips`, `ask` and agents search (separated by `:`; `;` on Windows) |
| `TRIPSHOTS_MUSIC` | | Folders with music that `ask` and agents can choose from |
| `TRIPSHOTS_OUT` | `./reels` (the app and the MCP server: `~/Movies/Reels` on macOS, `~/reels` elsewhere) | Where new reels are written when no `-o` is given |
| `TRIPSHOTS_ENCODER` | `auto` | `auto`, `hardware`, `software`, `videotoolbox`, `nvenc`, `qsv` |
| `TRIPSHOTS_HWACCEL` | `1` | `0` turns off hardware *decoding* on Macs |
| `TRIPSHOTS_COOKIES_BROWSER`, `TRIPSHOTS_COOKIES_FILE` | | Browser (or cookies.txt) for Instagram downloads |
| `TRIPSHOTS_EDITS_URL` | `http://127.0.0.1:19501/mcp` | Edits' automation server ([Finish in Edits](edits.md)) |
| `TRIPSHOTS_EDITS_TOKEN` | | Its token, from Edits' Automation settings |
| `TRIPSHOTS_EDITS_STAGE` | Edits' sandbox folder | Where packages are copied so Edits can open them |
| `TRIPSHOTS_MCP_TOKEN` | | Bearer token for `tripshots mcp --http` (required beyond localhost) |
| `TRIPSHOTS_OFFLINE` | | `1`: no network lookups (Openverse, place names) |
| `TRIPSHOTS_HOME` | `~/.tripshots` | Where everything below is stored |
| `OPENVERSE_API` | `https://api.openverse.org/v1` | Openverse endpoint (for mirrors / tests) |

`REELMAKER_*` variables from before the project was renamed are still read.

## What is stored where

Everything lives under `~/.tripshots/` (`TRIPSHOTS_HOME`). All of it can be deleted; it is rebuilt when needed.

| Path | What |
|---|---|
| `.env` | Settings |
| `tui.json` | The app's remembered choices (folders, music, where reels go) |
| `library/` | Per-file memory, keyed by file content: metadata, shot analysis, thumbnails, AI verdicts (`library.db`), photo stills, cut-out masks, faces (`faces/`), Gemini logs (`watch/`) |
| `cache/` | Per-run work folders (shot lists, proxies, rendered segments). Safe to delete any time |
| `styles/`, `looks/`, `luts/` | Your styles, colour looks, and the per-shot LUTs |
| `people/` | Who you've taught it (`people.json`: names and face embeddings) and the last discover result |
| `models/` | Face models |
| `selections/` | Saved `find` results and their contact sheets |
| `analysis/` | `tripshots analyze` results: `media.jsonl`, `summary.json`, `schema.json` per run |
| `jobs/` | Background jobs started by agents (command, log, result) |
| `edits/` | Edits' tool list (`tools.json`) and your mapping to it (`profile.json`) |
| `music/`, `sfx/` | Downloaded reel sounds; sound-effect pools (`library/` is yours to fill) |
| `hyperframes/`, `clone/`, `learn/` | Route-map runtime; analysed reference reels |
| `geocode_cache.json`, `geocode_search.json` | Cached place names and place outlines |

Clear things with `tripshots library --forget-ai` (AI verdicts only), `tripshots library --wipe` (the whole
library), or by deleting the folders above.
