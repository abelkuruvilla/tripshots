# Changelog

All notable changes to TripShots. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **Learned styles copy the reference, not just its timing.** `learn` now records the references' light and colour (used to choose shots that look like them, plus the kind of light and people the AI sees), their shape (a widescreen reference gives a cinematic letterbox reel with text in the bars), their camera speed, and fixes the format and hook-text behaviour; the look is applied at full strength (`grade.match: full`, also for clones). The story engine's rhythm follows the style's pace (a 4-beats-per-shot reference holds shots twice as long). `tripshots learn -n NAME` without links re-learns an existing style.

### Added
- **Story engine** ([docs](docs/storytelling.md)): every reel is planned as hook → setup → build → peak → release → ending instead of an even cut grid. Shot lengths vary on purpose (½ to 8 beats; cuts accelerate into the drop; the payoff is held), the best shots are cast into the hook, payoff and ending, shots with you are weighted up and one lands in the first 3 s, the opening settles from a push-in so something moves at once, and the ending is chosen to loop. `make --arc off` keeps the old grid.
- **Formats:** `--format auto|montage|pov|list|series|reveal` (numbered place cards, "Day N of", a slow reveal), with the AI writing three hook candidates per format, scored on clarity, curiosity and emotion.
- **Sound with words:** Gemini transcribes dialogue and lyrics with timings and the punchline; dialogue reels cut between lines, land the payoff on the punchline and show English subtitles (`--captions`). Optional offline transcription with faster-whisper.
- **Match cuts** from each clip's measured camera movement, and **2.5D parallax** for photos (Depth Anything V2 Small, downloaded once; an estimate otherwise; `--parallax`).
- **Critic:** every plan is scored on eight retention checks and fixed where possible before rendering, plus an AI storyboard review (`NAME.critic.json`, `--critic`).
- **Results:** `tripshots results add|sync` records how reels did (by hand or from the Instagram Graph API) and learns which formats and hook types work for your audience; MCP `reel_results`. Variants now test different ideas (format, opening, hook).

### Changed
- Text has minimum sizes so it reads on a phone, busy backgrounds get a shade behind the words, and a story reel's hook is fully on screen within about half a second.

### Changed
- **Clone picks shots by eye.** The AI now sees the reference shots and pictures of your candidate shots side by side (before, it only read your shots' tags), and is told to match light and mood first (golden hour to golden hour), then content and framing, and to prefer your video clips for a video reference. Candidates are pre-ranked by light and colour likeness to each reference shot. The reference description also records each shot's light, people and mood.
- **One shot per moment.** Photos of a burst, the photo and the clip of the same view, and chunks of one clip are grouped by picture likeness and capture time, and a clone (and `make`) uses each moment once while it has choice; the AI only sees one shot per moment.
- Clone shots move like the reference shots (Ken Burns direction and push in or out, pan direction), calm slots use real slow motion from 50 fps+ clips, and a black shot at the end of a reference becomes a fade to black instead of a 7-frame photo.

### Fixed
- Wide photos and clips slid sideways edge to edge in about a second and a half, so the person or the main subject drifted out of frame. Crops now hold the shot's focus (the person, else the most important subject that fits), pans and drifts are capped at about 6 % of the width per second around the subject, wide photos push in instead of sliding (only panoramas with no single subject travel), and the hook, payoff and ending always push in.
- The camera shake on drops hit every cut that landed on a drop, even in calm, cinematic reels and clones, where it looked like a glitch. It's now a deliberate choice per shot (`shake: true` in the plan): only on drops in intense sections of energetic reels, never on slow motion or under a freeze-frame, and a clone shakes only where the reference itself does (measured from the reference).
- The crop on moving-camera shots (drones, handheld) drifted toward whatever was bright and lost the subject; it now follows the subject the AI framed by matching it frame to frame. Shots with a person no longer pan across a wide view that starts or ends without them.

### Added
- **Speed effects:** five new speed ramps next to `velocity`: `slam` (into slow motion on the beat), `bullet` (a slow-motion hold), `rush` (speeds up into the next cut), `surge` (takes off) and `impact` (out of slow motion after a drop), plus custom curves (`ramp_points`). Ramps now slam into slow motion on a beat. Speed-ups (1.6–2.2×) with motion blur on moving clips in busy sections, and a speed effect around the biggest drop (`speed.drop`). Slow motion from 24/30 fps clips gets optical-flow in-between frames instead of stutter or ghosting, and ramps use 60 fps clips' full frame rate. New style section `speed`; `make --speed-ramps on|off|KINDS --speed-up --drop-speed --slowmo-smooth`; Make tab menus; plan edit op `ramp` (MCP `edit_plan`); `make_reel` takes `speed_ramps`, `speed_up`, `drop_speed`. The storyboard shows each shot's speed, exports carry it, and the sound design puts a whoosh where a ramp hits.

### Fixed
- Reel downloads (learn, clone, music, look) failed with bare yt-dlp errors such as `could not find brave cookies database`, then the generic "Still blocked with cookies" advice. TripShots now checks the browser first and says exactly what's wrong: not installed at the expected place (with Beta/Nightly builds and profiles it found), no Instagram login in that browser (a reel plays without one, a download doesn't), or macOS blocking the terminal (Safari needs Full Disk Access; Chromium browsers need the Keychain prompt allowed). New `--cookies-from-browser auto` uses the first browser that's logged in; Arc, Vivaldi and Opera are supported; only instagram.com's cookies are handed to yt-dlp, in a private temporary file. New `tripshots cookies [--login]` lists every browser's state, and `doctor` checks the configured one.
- Gemini watching hit `429 RESOURCE_EXHAUSTED` on free keys and lost clips. Requests are now paced across workers (`TRIPSHOTS_GEMINI_RPM`, default 10 a minute). On a per-minute limit every worker waits the time Gemini gives, the pace drops to fit the key's limit, and creeps back up after successes; other errors back off exponentially with jitter. A model whose daily quota is used up is swapped for the next one, and when all are, Gemini stops for the run with one clear message (watched clips stay cached).
- HDR footage (iPhone HLG, HDR10) looked flat with Homebrew's standard `ffmpeg`, which no longer includes `zscale` ("this ffmpeg lacks zscale; colors may look flat"). TripShots now falls back to lookup tables measured from its own zscale + tonemap chain, applied with `lut3d` (in every ffmpeg), so the colours are the same either way. `doctor` shows which HDR route is used.
- Gemini watching failed on every clip with `models/gemini-flash-latest is not found for API version v1` on newer google-genai versions. TripShots now uses the v1beta API (where the `-latest` aliases live), checks which models the key can use, switches to the next model at once on "not found", and stops Gemini for the run, with one log line, when no model or key works. The progress line now counts successes.

### Changed
- Automatic AI mode now chains every AI you've set up: Claude Code, then MiniMax, then the Anthropic API. A logged-out Claude Code is skipped, and if one AI stops working mid-run the next takes over. Before, MiniMax was only used when Claude Code wasn't installed at all.

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
