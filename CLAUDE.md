# TripShots: notes for Claude

This repo is a CLI that turns silent travel footage and photos into beat-synced Instagram Reels.
The user is not a video editor. Make the creative calls yourself, show the result, and offer one or two concrete tweaks.

## Commands
- `tripshots make <folders...> -m <song> [-s style] [-d secs] [--hook TEXT] [--location TEXT] [--dry-run] [-o out.mp4]`
- `tripshots scan <folders...> --top 30`: ranked shot list with ids, AI scores, tags and notes
- `tripshots render <plan.json> [-o out.mp4]`: re-render after editing the plan
- `tripshots learn <urls-or-files...> -n <name> [--cookies-from-browser chrome]`: create a style from reference reels
- `tripshots music <reel-url> [--cookies-from-browser chrome]`: download a reel's sound (cached) and report its BPM. `make -m <reel-url>` does this automatically, cuts from 0:00 and also writes `NAME.noaudio.mp4` for upload + in-app sound
- `tripshots library [--forget-ai|--wipe]`: per-file memory (metadata, shot analysis, AI verdicts) keyed by file content; reused by every run. `--rescore` on make/scan re-asks the AI
- `tripshots` (no args) or `tripshots ui`: the Textual app (tui.py) for the user; it shells out to the same CLI commands. State in ~/.tripshots/tui.json, settings in ~/.tripshots/.env
- `tripshots frame <photos|folders> [-f post|story|square|both] [--bg paper|blur|solid|dark] [--variant auto|top|bottom] [--border] [-o dir]`: pop-out frame stills (popout.py, rembg cut-out cached in library/masks). In reels, photo segments with `layout: popout` animate it (style `popout.use`)
- `tripshots look <urls|videos|photos|folders> -n <name>`: measure a reference grade into `~/.tripshots/looks/<name>.json`. `tripshots looks` lists looks; `tripshots grade <inputs> --look <name> [-o dir]` exports graded copies + before/after; `make --look <name|auto|none> [--grade-strength 0-1]`
- `make --route-map intro|tracker|both|off`: animated route map from GPS (routemap.py). It renders with HyperFrames (Node 22+, runtime in ~/.tripshots/hyperframes; `tripshots maps --setup`) to transparent PNG frames that render.py alpha-blends over the footage
- `tripshots clone <reel-url|video> <folders...> [--variants N] [--look X] [--keep-text] [--hype] [--dry-run] [-o out.mp4]`: shot-for-shot remake (clone.py). The reference is analysed once into ~/.tripshots/clone/ref_*/ (reference.json, slots.json, match_*.json); check `NAME.clone.jpg` (reference | your shot per slot) before rendering
- `make --variants N`: N versions (opening shot = k-th best hook shot, jittered order, transitions, hooks that avoid earlier ones) + `NAME.variants.jpg`
- Sound design (sound.py) runs after every render when plan `sound` is on: cues come from the plan (transitions, freeze, rgb, ramps, panels, popouts, maps) and the rendered text (word pop times). `tripshots sounds [--fetch]` shows/fills the sound pools (~/.tripshots/sfx: library/, openverse/, earshot/, index.json); `make/clone --sfx on|off --ambience on|off --sfx-level dB --sfx-licenses cc0,pdm[,by]`; `tripshots listen NAME.mp4` (earshot timeline, needs its models). Check `NAME.sound.jpg` and `NAME.sound.json` (cues, takes, licences, sync, master)
- `tripshots export <plan.json> [--edl --otio --md]`: hand the edit to Resolve/Premiere/FCP (export.py). `.edl` and `.storyboard.md` are written automatically next to every plan
- Gemini watch (watch.py, optional, `GEMINI_API_KEY`): `make/scan/clone --watch auto|gemini|off`. Adds `ai.watch` per shot {peak, score, motion, framing, stability, exposure, audio, energy, subject} and `incam` (whip pans; also found locally without Gemini). Cached in ~/.tripshots/library/watch/
- `--clip-sound auto|on|off`: a clip's own clean ambience replaces the library bed for that segment (sound.native_beds; reasons in `.sound.json` → `native`)
- `pytest -m "not slow"` (quick) / `pytest` (adds one real render). Tests make synthetic footage; keep them passing after changes
- `make/clone/render --encoder auto|hardware|software` (encode.py; env `TRIPSHOTS_ENCODER`): hardware H.264 (VideoToolbox / NVENC / Quick Sync) after a test encode, automatic libx264 fallback. Every render logs `encoder: ...` and `render took Ns`
- Finding footage (catalog.py): `tripshots find [--place NAME] [--people me mom] [--since/--until] [--kind photo|video] [--text W] [--sheet]` saves a selection; `make/scan/clone sel:<id>` use it. `tripshots trips` groups footage into trips. `tripshots footage <folders>` sets default roots (TRIPSHOTS_FOOTAGE). Selections in ~/.tripshots/selections/
- People (people.py, local OpenCV YuNet + SFace, models in ~/.tripshots/models): `tripshots people add me <photos>`, `people discover` (clusters + sheet), `people name c2 mom`, `people list|forget|who`. Faces cached per file in library/faces/
- Agents: `tripshots mcp` (stdio) / `tripshots mcp --http HOST:PORT` (TRIPSHOTS_MCP_TOKEN) exposes everything as MCP tools (mcp_server.py; long steps are jobs, jobs.py). `planedit.py` = safe plan edits (swap/move/exchange/text/transition/speed/frame/set) used by MCP `edit_plan`. `tripshots ask "..."` = plain language via the AI backend (ask.py). Portable agent skill: skills/tripshots/SKILL.md
- Edits (edits.py, docs/edits.md): `tripshots edits package <plan>` -> NAME.edits/ (picture.mp4 rendered with `render(native_text=True)` so hook/cta/labels/plain location titles aren't drawn, clips/ per segment, text/ PNGs, sound-effects.wav, music.m4a, manifest.json). `edits tools|probe|push` talk to Edits' undocumented automation server via a user-confirmed mapping in ~/.tripshots/edits/profile.json; never hard-code Edits tool names. Tests use tests/fake_edits.py
- The app's first tab is **Ask** (tui.AskTab): runs `tripshots ask`, sets footage folders, enrolls people
- Docs live in `docs/` (index: docs/README.md). `docs/cli.md` and `docs/mcp-tools.md` are generated: after changing a command or an MCP tool, run `python tools/gen_docs.py` (CI checks with `--check` on Python 3.13). `tests/test_docs.py` checks every relative link. User-visible changes go in CHANGELOG.md under Unreleased
- `tripshots styles`, `tripshots doctor`

Outputs sit next to the mp4: `.plan.json`, `.storyboard.jpg`, `.grade.jpg` (before/after), `.cover.jpg`, `.caption.txt`, and with sound design `.sound.jpg`, `.sound.json`, `.sfx.wav`, `.nomusic.mp4` (upload copy that keeps the effects).

## Workflow
Use the `make-reel` skill in `.claude/skills/make-reel/SKILL.md`. In short:
1. Run `make --dry-run`, then **look at the storyboard image** with the Read tool before rendering.
2. Fix weak spots by editing `plan.json`: swap `shot_id`s (get ids from `scan` or `<work>/shots_scored.json`), adjust `subject_x`, `speed`, `trans_out`, or the overlay text.
3. Run `render`, then pull 3–4 frames with ffmpeg and look at them, especially the hook in the first second and any text.
4. Give the user the mp4 path, the caption and the cover.

## Plan.json rules
- Segments tile the timeline. `render` recomputes `out_start` from `dur`. Keep durations multiples of 1/30 s and on beat: only swap shots, or merge two neighbours, unless asked otherwise.
- `layout`: `crop` (landscape cropped at `subject_x`), `pan` (slow pan across a wide frame), `fill` (already vertical), `blur_fill` (whole landscape frame over a blurred copy), `kenburns` (photos; `kb`: in/out/left/right).
- `speed` 0.5 = slow motion (only looks smooth on clips shot at 50 fps or more).
- `trans_out`: null = hard cut on the beat, or one of whip, zoom_in, zoom_out, spin, flash, glitch, blur, dissolve, dip. Optional `trans_dur` (seconds, centred on the cut) and `trans_params` (whip: `{"direction": "left|right|up|down"}`, spin: `{"clockwise": true}`).
- `kb` (photos): in, out, left, right, up, down, in_rot. Plan-level `motion`: `beat_punch` (zoom bump per beat, e.g. 0.06), `punch_on` (levels), `shake_on_drop`, `video_push`.
- Overlays: `{"type": "hook"|"location"|"cta", "text", "start", "duration"}`; location may carry `gps` [lat, lon] (shown as a coordinates line) or explicit `main`/`sub`/`coords`. Keep hooks at 7 words or fewer. The look comes from `text.preset` (bold, editorial, minimal, handwritten, typewriter); `text.hook.position` can be auto/upper/center/lower. With `text.location.behind` auto/on, the location title is drawn as a giant word behind the skyline (sky segmentation per frame, mask.py); give such an overlay a start at a segment start and a duration that ends within that segment.
- Split-screen segments: `{"panel": split2|split3|grid4|columns3, "pmode": reveal|cycle, "clips": [{rect, t0, t1, intro, <shot fields>}]}` (times relative to the segment). Video segments may have `"ramp": "velocity"`. Plan-level `loop: true`. Overlays may include `{"type": "label"}` per shot. Motion `pulse` = bulge on intense beats.
- Framing per segment: `subject` {x0,y0,x1,y1,cx,cy} (normalised source coords; Ken Burns zooms toward it), `layout` crop/pan/blur_fill/fill, `pan_from`/`pan_to` (0..1 across the source; `pan_reverse: true` flips direction), `track: true` follows a moving subject. To reframe a shot, edit `subject` or `subject_x` and re-render.

- Colour (grade.py): every segment / panel clip carries `lut` (a per-shot .cube in ~/.tripshots/luts) and `grade_note` (the light). Plan-level `grade` {look, strength, why, grain, vignette}. To regrade, re-run `make --look X --dry-run` (fast; analysis is cached) rather than editing LUT paths. Check `.grade.jpg`: skies should stay blue, blacks not grey, sunsets still warm.

- Route map: overlays `{"type": "map", "mode": "intro"|"tracker", "start", "duration", "x", "y", "theme": dark|light, "title", "stops": [{name, region, ll}], "beats" (intro, local s), "keys" (tracker: [local s, stop index])}`. The HyperFrames HTML is built from this at render time (routemap.overlay_html) and cached by content, so renaming a stop or changing the title/theme in plan.json + `render` just works. Delete an overlay to drop the map. Intro cards sit in a gap with no other text.

- Clone plans: segments carry `clone_of` (reference shot id, e.g. R03) and keep the reference's exact `dur`; don't change durations, only swap `shot_id`. Overlays carry `clone_of` (the original text). `music.path` is the reference's own sound (start 0).
- In-camera whips: a segment with `incam_out` {type, at, src} ends in the middle of the camera's own swing (hard cut, `trans_out` null); the next may have `incam_in: true`. To drop one, delete `incam_out` and give `trans_out` a value. Raw 360 files (.insv, 2:1 equirect) are skipped on purpose: they need reframing in Insta360 Studio first.
- Effects: plan-level `freeze` {t, dur} (hero freeze on a drop), segment `rgb: true` (colour-split on its first frames). Remove them to turn them off. Every render logs a beat check (cuts within 1 frame of the plan, cuts on a beat).

- Sound: plan-level `sound` {sfx, ambience, level_db, licenses}. Sound effects follow the edit automatically, so changing transitions/freeze/text and re-rendering re-designs them. Don't add sounds on plain hard cuts; never use NC/ND/SA-licensed audio.

## Style YAML
Styles live in `tripshots/styles/` (built-in) and `~/.tripshots/styles/` (user). Keys are documented in `config.py: DEFAULT_STYLE`.
To change the look permanently, copy a style to `~/.tripshots/styles/<name>.yaml` and edit it.
