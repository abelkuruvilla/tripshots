# Architecture

TripShots is a Python package (`tripshots/`) built around one pipeline. Every user interface (the CLI, the app,
the MCP server, `ask`) ends up running the same commands.

```
footage folders / sel:<id>
   │
   ▼
media.ingest ───────────── metadata, GPS, capture time, HEIC/HDR/rotation; cached per file in library.db
   │
   ▼
shots.analyze ──────────── scene cuts, sharpness, shake, motion, brightness; long clips split into chunks
   │  watch.py (optional) ─ Gemini watches clips: best moment, shake, tilt, audio, whip pans
   ▼
ai.score_shots ─────────── the AI judges each shot from a contact sheet: score, subject box, tags, hook/closer
   │
   ▼
music.analyze ──────────── beats, downbeats, energy curve, best window of the song
   │
   ▼
planner.build_plan ─────── cut grid on the beats → shot selection and order → layouts → transitions
   │  effects.py, grade.py  freeze-frame / colour split; per-shot colour LUTs
   │  text / typo / routemap overlays: hook, location, labels, maps
   ▼
plan.json + storyboard ─── the edit, reviewable and editable (planedit.py for safe edits)
   │
   ▼
render.render ──────────── each segment rendered by ffmpeg (encode.py picks hardware or libx264), then
   │                       composited frame by frame in Python: transitions, motion, text, maps, effects
   ▼
sound.mix_into ─────────── sound effects on the cue frames, ambience beds, clip sound, master to −14 LUFS
   │
   ▼
NAME.mp4 + cover, caption, .edl, .storyboard.md, sound sheet, upload copy
```

## Modules

| Module | Job |
|---|---|
| `cli.py` | Command line (`build_parser` defines every command); every command prints JSON |
| `tui.py` | The Textual app; runs the CLI in subprocesses |
| `pipeline.py` | `make`, `clone`, `render_plan`: glue between the stages |
| `config.py` | Paths, `.env`, styles (`DEFAULT_STYLE`), output folder |
| `library.py` | SQLite library keyed by file content (metadata, shots, AI verdicts) |
| `media.py` | Finding files, metadata, GPS, capture times, camera quirks |
| `shots.py` | Shot detection and technical metrics |
| `ai.py` | Backends (Claude CLI, Anthropic API, MiniMax) and the scoring / writing prompts |
| `music.py`, `fetch.py` | Beat tracking and energy; downloading reel sounds (yt-dlp) |
| `planner.py`, `panels.py`, `framing.py`, `motion.py`, `fx.py` | The edit plan, split screens, crops and tracking, motion, ffmpeg filters |
| `render.py`, `encode.py` | Segment rendering, frame compositing, encoder choice |
| `text.py`, `typo.py`, `mask.py` | Storyboards, animated typography, sky masks for titles behind the skyline |
| `grade.py` | Looks, per-shot correction, LUTs, copying a reel's colour |
| `effects.py` | Freeze-frame, colour split, the beat check |
| `routemap.py` | Animated route maps (HyperFrames, Natural Earth) |
| `sound.py` | Sound design: cues, takes, Openverse / earshot / library sounds, mixing, mastering |
| `learn.py`, `clone.py` | Learning a style from reels; cloning one reel shot for shot |
| `popout.py` | Pop-out frames (rembg cut-outs) |
| `watch.py` | Optional Gemini video watching; local whip-pan detection |
| `export.py` | EDL, OpenTimelineIO, storyboard.md |
| `catalog.py` | Finding footage by place / dates / people; trips; selections |
| `people.py` | Local face detection and recognition (YuNet + SFace) |
| `geo.py` | OpenStreetMap place names and place outlines (cached) |
| `mcp_server.py`, `jobs.py`, `planedit.py` | MCP server, background jobs, safe plan edits |
| `ask.py` | Plain-language requests → search → reel |

## Design rules

- **Never generate footage.** Every frame is the user's own; effects only move, crop, grade and overlay it.
- **Cache by content.** Anything expensive (metadata, shot analysis, AI verdicts, faces, Gemini logs, LUTs, maps)
  is keyed by file content or inputs, so re-runs only pay for what changed.
- **The plan is the interface.** Every decision is written to `plan.json` before rendering, so humans, agents and
  editors can review and change it.
- **JSON out, logs on stderr.** Every command's result is JSON on stdout; progress goes to stderr with a
  `[tripshots]` prefix. The app and the MCP jobs rely on this.
- **Fail soft.** Optional parts (Gemini, Openverse, maps, hardware encoding, place names) fall back and say so in
  the log instead of stopping a reel.
