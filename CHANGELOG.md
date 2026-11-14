# Changelog

All notable changes to TripShots. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Horizontal reels.** A wide picture no longer sits between black bars in an upright file: when the style or the recipe is wide (`frame.aspect` 4:3, 16:9, 2.39:1), or every shot is landscape and most can't be cropped upright, the reel is made as a real 1920×1080 file with the picture filling it. Text, safe areas, the storyboard, the QA check, the cover and the Edits package follow the frame, and the lettering is larger so it still reads when the phone shows the video small. `make --orientation auto|vertical|horizontal` (MCP `make_reel(orientation=)`, style `frame.output`) decides it by hand: `vertical` keeps the old letterbox, `horizontal` makes any reel wide. The plan records it as `frame.canvas`.
- **A learned style keeps each example's recipe.** A style learned from several reels used to keep only their average, so seven different ideas became one even montage. `learn` now also saves one recipe per example (style key `recipes`): its cut (a long opening shot and then a burst, flashes and then steady shots, even shots, a montage), its exact shot lengths, its picture shape, and what its words do (the song's lyrics one word at a time, a tease line and then the payoff, one title for the whole reel, a title per shot, subtitles, none) with their lettering, colour and place. `make` follows one recipe per reel: the example whose sound you use, else the one that fits the song best. `--recipe N` picks one, `--recipe off` uses the style's average (style: `story.recipe`; MCP `make_reel(recipe=...)`). The app's Styles tab lists a style's recipes. Re-learn older styles with `tripshots learn -n NAME`.
- **A long opening shot is one continuous clip.** When the recipe opens on a hold (several seconds on one shot), it is cast from a single moving clip long enough to play at normal speed, never a photo or a slowed short clip, and the AI looks at the best candidates end to end before choosing.
- **A reel's own sound keeps its own cut.** With the sound of the reel you learned from (`-m <reel link>`), the music starts at 0:00 and the cuts sit exactly where that reel cuts, so the drop lands where it was made to.
- **Text that looks like the example's.** A recipe's words carry their own lettering: tall narrow capitals get a condensed face, the colour is the example's ("pale yellow", "cream", "golden yellow"...), and words cut in when the example's do. Lyrics shown one word at a time stay on one line instead of jumping about, and words set on the picture keep off the person or subject of the shot.
- **A series from one trip doesn't repeat itself.** Every rendered reel is remembered (`~/.tripshots/history.json`); the next `make` marks down the shots earlier reels showed, the opening shot most, and shots from the same moment with them. Re-rendering replaces a reel's own note and a deleted reel is forgotten. `make --fresh off`, style `shots.fresh`, MCP `make_reel(fresh=...)`.
- **Labels like the example's.** A recipe whose example names every shot ("Greetings from... UTAH") now does that with your footage: one name per shot from what is known (the landmark the AI recognised, the park or town from the GPS, the state), a small lead line above big letters, postcard letters in several colours when the example's are. Shots with a known place are preferred, and the reel is told place by place.
- **Reels spread over the whole trip:** shots from a place already in the reel are marked down, so a long trip isn't told from one afternoon (`shots.place_variety`, 0 turns it off).
- **Footage with titles already on it** (an exported edit, a screen recording, a saved reel) is recognised by the AI (`issues: burned-in-text`) and kept out of reels, where the old words would sit under the new ones.

### Changed
- **Learned taste no longer beats a clearly better shot.** A style's preferred light and colour used to be able to outrank the AI's quality score. It is now a bounded nudge measured against your own footage (what looks most like the examples *among your shots*), and it also learns whether the examples are made of video or photos (`taste.footage`).
- **Titles and teases follow the example.** A recipe's title is built like the example's ("USA 2026" → "West Coast 2026") and stays for the same share of the reel; a tease and its answer read as one sentence; the critic no longer replaces such a line with a hook of its own.
- A camera without GPS (drone, action camera) takes the position of the phone picture closest in time, so its shots can be named too.
- **Cover:** the cover still is no longer taken in the middle of a sentence (one word of a lyric or half a tease). It shows the title once it has arrived, else a clean frame of the opening shot.
- **`render` after a reel-sound `make`** writes the upload copy again (`.nomusic.mp4` / `.noaudio.mp4`) and repeats the posting note, so the copy you post is never an older cut.
- The storyboard of a wide reel shows the picture, not black bars.
- **The storyboard shows what the reel shows:** each tile is the moment of the clip that the cut really uses (it used to be the clip's best frame, which could be a different view). The AI critic looks at the same sheet.
- **Auto never adds bars:** a style learned from square or 4:5 examples makes a full-screen upright reel; 4:3 and wider make a horizontal one. Only `frame.output: vertical` keeps a band between bars.
- **No strips in an upright reel:** a landscape clip too wide to crop is no longer shown whole over a blurred copy (a strip between two soft bars). It holds its person, or drifts slowly across the middle of the view; `layout.landscape: blur_fill` in a style still asks for the old look. A reel made mostly of such shots is made horizontal instead.
- **The best shots get the time.** The turn of a reel goes to one of its best-looking shots, the longer slots get the better shots (also after the critic's swaps), and the memory of earlier reels only chooses among shots about as good as the best one for the opening and the ending.
- **One view, once.** The view an opening shot held is not shown again later in the reel, and one kind of view (three waterfalls, four roads) doesn't keep coming back.
- **Grey shots in a colourful reel:** a nearly colourless shot (steam, fog, a white sky) has to be clearly better than a colourful one to get in, never opens, turns or closes a colourful reel, and isn't offered to the AI critic as a spare. Neither is an upright clip or photo for a horizontal reel.
- **A line held across several shots** (a title, a tease's answer) stays inside the safe area on every one of them, sits in the third of the frame that is freest over all its shots, and at a height that keeps it off somebody's head (overlay style `y`).
- **Labels reels:** the places are balanced over the regions of the trip, one kind of name is used throughout, counties are never used as a name, the name sits in the third of the frame its shots leave free, and the small lead line ("Greetings from...") is big enough to read.
- **The critic keeps a place-by-place reel in order:** its swaps stay inside a chapter.
- **Captions and lines stick to the facts:** the Instagram caption never puts a place in the wrong state, what it says about the light is said of the right shot, and it is written again when the critic changes the shots. A tease's answer names what the reel shows, and a line that trails off does so with three dots.
- **Colour:** a grade at most doubles a flat scene's own contrast (haze and fog used to come out harsh).
- **Balanced lines:** a title that needs two lines splits them evenly ("The urge to / keep driving."), never one word hanging under a full line.
- **One landmark, once:** a reel no longer shows the same landmark twice from different angles (two Half Domes), neither from the planner nor from the AI critic's swaps.
- **Recipe reels follow their example more closely:** the style's averaged split screens are left out of a single example's cut; subtitles appear only for the stretch the example subtitles (a spoken opening, not the song after it), and an example that shows no words over its own voice gets none; a tease the example leaves unanswered ends in three dots ("Just us, the rig, and the..."); a pause in the lyrics ("…") is not shown as a word.
- **Subtitles stay put:** consecutive subtitle lines no longer overlap for a moment, which made the next line jump to another part of the screen.
- **Loudness:** a peaky song that the limiter held down is lifted into its remaining headroom, so the master lands at -14 LUFS instead of around -16.

### Fixed
- **Editing a plan:** swapping, moving or exchanging shots keeps each slot's place in the story (`role`, the opening hold), reframes the new shot for a letterbox picture, and drops an in-camera whip that belonged to the old footage (which also left a whoosh on a plain cut).
- Drone clips with a clock but no time zone were sorted hours away from the phone footage of the same moment.
- **`learn` when the AI runs out of usage:** it used to keep asking, save the examples it could not look at as "no text", and replace the style's description with timing only. It now stops at the first refusal, marks those recipes as not read yet (`unread`; auto prefers recipes that were read), keeps the description the style already had, and ends with how many examples are left. `tripshots learn -n NAME` finishes the job: what was read is kept.

### Added
- **Attention profile per learned style.** `learn` measures how each reference holds attention (rhythm over its length, opening hold and shot, where the payoff is held, shot mix, speed, reveal, loop) and saves it as the style's `attention`. The story rhythm follows that curve on the song's beats, casting opens the way the references open and keeps their shot mix, and the critic judges pace against the style's own references instead of one general rule.
- **More examples per style:** `tripshots learn <links> -n NAME --add`; the app's Styles tab shows a learned style's examples and profile, with **Add example reels…** and **Re-learn**.
- **Critic:** a hook that names a landmark shown only later is caught, and the reel opens on that shot instead.

### Fixed
- **"landmark lookup skipped (HTTP Error 502)":** the park/landmark lookup now retries a busy Overpass server and moves on to other public Overpass servers (`TRIPSHOTS_OVERPASS` puts your own first). When none answers, the town name is used for that run only and the place is looked up again next time instead of being kept.

### Fixed
- **Location titles said the county** ("Mariposa County") instead of what you filmed. They now name the famous spot or national park first ("Glacier Point, Yosemite National Park", "Yosemite National Park, California"), from OpenStreetMap, and fall back to the town, then the county. Earlier lookups are redone once.
- **A location title could name a different shot:** when a title had to move off a split screen, it kept the split screen's place over the next shot (a desert county over El Capitan). It now names the shot it is over.
- **Side-by-side columns with landscape clips:** `columns3` showed a tenth of each landscape clip. Landscape clips are now stacked top to bottom (`split3`).

### Added
- **Subtitles in any language:** `--captions` takes `off`, `original` (the words in their own script), or a language name or code (`english`, `malayalam`, `hindi`, `es`...); other languages are translated by the AI backend and cached. In the app: a **Subtitles** choice on the make tab.
- **Fonts for other scripts** (`scripts.py`): Malayalam, Devanagari, Tamil, Telugu, Kannada, Bengali, Gujarati, Gurmukhi, Arabic, Hebrew, Thai, Greek and CJK text uses a font with those letters (your own in `~/.tripshots/fonts`, the computer's, or Noto Sans fetched once), shaped with Raqm.

### Fixed
- **The hook and subtitles drawn on top of each other:** the hook moves up when subtitles run under it, and any title that would cover another on screen at the same time moves to a free band.
- A font given as a path kept its case (paths were lower-cased, which broke on case-sensitive disks).

### Fixed
- **Gemini watch with new keys:** Google no longer serves `gemini-2.5-flash` to new users. The fallback is now `gemini-flash-lite-latest`, `-latest` aliases are no longer discarded because Google doesn't list them, and when every configured model fails the next available Flash model is tried before giving up.
- **`--no-location` now means no place names anywhere:** no location title, no place names in the AI hook, and no numbered place list. Also on `clone` (drops the reference's place titles) and as `TRIPSHOTS_NO_LOCATION=1`; the app's clone tab has a **No place names** switch.

### Added
- **Motion text with HyperFrames.** With the HyperFrames runtime installed, hooks, location titles, labels and closing lines animate in a browser: `rise` (out of a blur), `focus`, `tracking`, `typewriter` (with a caret), `slam` (lands with a shake), `write` (pen reveal) and `cinema`. `text.motion` / `--text-motion` (auto picks one per text preset; off keeps the classic animation). TripShots still lays the words out; only the animation changes.
- **`leak` transition:** warm film light washing across a dissolve, used between calm shots (cinematic, slow-scenic and the default calm palette).
- **Checks after every render** (`qa.py`, `tripshots qa`, MCP `check_reel`): format, length, loudness and true peak, black/frozen/silent stretches, text inside the safe area, readable size and time on screen; `NAME.qa.json` and a contact sheet `NAME.qa.jpg`. Every render also writes `NAME.text.json`.
- **Director's notes:** `tripshots/DIRECTOR.md` plus a per-style `direction`, read by the critic's AI review; built-in styles have one and `learn` writes one.
- **`tripshots skills`:** companion agent skills (HyperFrames, Remotion, one-take, Lemo-Opuscar), what each adds, whether installed, and `--install`.

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
