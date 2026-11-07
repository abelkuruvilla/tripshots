# Changelog

All notable changes to TripShots. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- When Claude Code isn't logged in, `make` and `analyze` stop at the start with how to log in, instead of retrying every contact sheet and printing raw JSON. A login that fails mid-run stops further AI calls at once. `doctor` shows Claude Code's login status. Error messages from Claude Code show just its message.

### Added
- **Standalone analysis:** `tripshots analyze` (app: Library → Analyse my footage; MCP `analyze_footage`, `search_media`) writes one `tripshots.media/1` record per file (JSON Schema included): file, media, capture time, camera, place, trip, people, and per shot technical quality (edge-based focus, exposure, clipping, contrast, colour, palette, perceptual hash, camera motion), near-duplicate groups, faces and an AI description. Python API `tripshots.analysis.load` / `query`.

### Changed
- One AI pass now serves both catalogue and reels: the prompt (version 2) adds caption, description, up to 12 tags, subjects with boxes, scene, setting, time of day, weather, people, visible text, landmark, aesthetic and issues. Reels keep using older stored verdicts; `analyze` re-asks for them.
- A video shot's thumbnail is now its sharpest, steadiest frame rather than the middle one (shot analysis version 5: footage is re-decoded once).

### Added
- **Finish in Instagram's Edits app:** `tripshots edits package` renders the picture with everything TripShots does baked in and writes clips per shot, titles (data + styled PNGs), the sound-effects track, the song and a manifest; `edits tools` / `probe` / `push` build the timeline through Edits' automation server with a mapping you confirm. MCP tools `edits_package`, `edits_status`, `edits_push`; **Send to Edits** in the app.

## [0.1.0] - 2026-11-03

First public release.

### Added
- **Reels from your own footage:** shot detection and AI shot judging (Claude subscription via Claude Code, Anthropic API, MiniMax, or none), beat-tracked cut grid, five styles, variants for trial reels, style learning from reference reels, editable `plan.json` with storyboards.
- **Finding footage:** `find` by place (GPS inside OpenStreetMap outlines, folder and place names, same-day clips without GPS), dates, people and kind; `trips`; selections (`sel:<id>`) usable by `make`, `scan` and `clone`.
- **People:** local face recognition with OpenCV YuNet + SFace: `people add`, `discover`, `name`, `forget`, `who`.
- **AI agents:** MCP server (`tripshots mcp`, stdio or HTTP with a bearer token) with background jobs, images in results and safe plan edits; portable agent skill (`skills/tripshots/SKILL.md`); `tripshots ask` and the app's Ask tab for plain-language requests.
- **Look and motion:** transitions on the beat, beat punch, shake, split screens, velocity ramps, freeze-frame, colour split, in-camera whip cuts, subject framing and tracking, animated typography, titles behind the skyline, pop-out frames, animated route maps (HyperFrames).
- **Colour:** per-shot grading with an AI colourist, eight looks, copying the colour of reference reels, graded photo/video export.
- **Sound:** real sound effects placed on cue frames (library, Openverse CC0, earshot), ambience per place, the clip's own sound when clean, mastering to −14 LUFS, upload copies for Instagram sounds.
- **Camera handling:** Insta360/GoPro/DJI quirks, capture times from file names, HDR tone mapping, HEIC, Live Photos, duplicates.
- **Optional Gemini video watching:** best moments, shake, tilt, audio type, whip pans.
- **Editor exports:** CMX3600 EDL, OpenTimelineIO, storyboard.md.
- **Hardware encoding:** VideoToolbox, NVENC, Quick Sync with automatic libx264 fallback.
- **Clone mode:** remake one reel shot for shot with your footage.
- The full-screen terminal app, `doctor`, tests and CI, documentation.

### Changed
- The project was renamed from *reelmaker* to TripShots. `install.sh` moves `~/.reelmaker` to `~/.tripshots` and `REELMAKER_*` settings are still read.
