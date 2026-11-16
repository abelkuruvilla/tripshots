# Changelog

All notable changes to TripShots. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Picture in picture and keyframes.** In the editor, **On top** puts another shot in a corner from the playhead. It has its own lane on the timeline, can be moved and sized, and fades in and out with rounded corners and a soft shadow. **Zoom and position** keyframes move the picture inside a shot (a slow push in, a pan across), eased between keyframes. Plan edits: `pip_add`, `pip_edit`, `pip_delete`, `keyframe`.
- **Flat log footage made normal.** Apple Log, DJI D-Log, Sony S-Log3, Panasonic V-Log, Fujifilm F-Log/F-Log2 and Canon C-Log3 clips are converted to normal video before grading, using the makers' published curves. This is automatic when the camera films log and the clip looks flat; it can also be set per clip in the Colour tab (**Filmed in**) or with the plan edit `log` (docs/colour.md).
- **The effects library, chosen by AI.** 33 transitions (13 new: push, wipe, clock, pixels, film burn, zoom blur, shake, card flip, blinds, RGB split, ripple, stretch, light-led dissolve), 12 shot effects (glow, dream, light leak, old film, VHS, black and white, duotone, chromatic edges, beat flicker, mirror, handheld drift, tilt-shift), text looks (neon, glow, outline, offset) and the animated text motions, each described by its energy, mood and what it suits (`tripshots effects`, MCP `list_effects`). At the end of `make`, the AI picks a transition for each cut, a motion and look for each line of text, and an effect for a shot or two. The style's number of transitions is kept, with at most three kinds per reel, and a reason is recorded for each choice (`make --effects auto|ai|rules|off`; docs/effects.md).
- **Effect pickers in the editor.** The Shot tab shows every transition and effect drawn on your own shots, filtered by energy, with an amount slider and **Choose effects with AI**. The Text tab gains **Motion** and **Look**. Plan edits: `effect`, `auto_effects`.
- **Preview your edits in motion.** The editor's new **Preview** plays the edited reel before the full render (`tripshots render --draft` writes `NAME.draft.mp4`: no sound effects, text without its animation). Its clips are cached for the real render, so that render is quicker afterwards.
- **Freeze frame, reverse and trim from the start.** In the editor (Expert), **F** holds the frame at the playhead for a second, **R** plays a clip backwards, and dragging a shot's left edge trims its start while the end of the clip stays put. Plan edits `freeze`, `reverse` and `trim` do the same for agents (MCP `edit_plan`).
- **Carousel posts from a reel.** `tripshots carousel NAME.plan.json` turns the reel's best shots into 1080x1350 slides coloured like the reel. The cover carries the hook and where it was taken, slides are numbered, `--handle` adds your handle, and the last slide lists the route.
- **Better caption checks.** `tripshots caption` now also flags search keywords missing from the caption, more than one ask (or none), links, generic hashtags, a hashtag or emoji in the first words, and clichés. Em dashes and invisible characters are removed from the AI's caption; the joiners Malayalam and Hindi need are kept.
- **Your voice file.** `tripshots caption` follows `~/.claude/instagram/voice.md` (shared with the Instagram agent skills) when it exists.
- **"vs usual" in `tripshots results`:** each reel's views against your median reel, and which reels beat it 3x or more (also in MCP `reel_results`).
- Hook lines are marked down for greetings, video preambles, emoji and hashtags, and up for a number or a name near the start.
- `tripshots skills` lists the Instagram agent skills (`npx skills add Jakeschincariol/instagram-agent-skill`).
- **Story grammar, from editors' rules.** After casting, middle shots are swapped so that every cut changes something you can see (size, light, colour or subject), shot sizes alternate, each new place opens on a wide view, and no camera move runs three times in a row. The opening, payoff and ending never move. The plan records `story.grammar`; turn it off with `story: {grammar: false}`.
- **A beat of black before the payoff.** After the song's held breath into an intense payoff, the last three or four frames before the hit go black (`motion.blackout`: `auto`, `on`, `off`).
- **Travel transitions and titles.** `polaroid`: the next shot drops in as a print and opens into the scene. `mirror`: the next shot opens from the horizon as its own reflection. Text motions `decode` (letters resolve out of random glyphs) and `stamp` (a passport stamp slams down). Both transitions are in the Shot tab.
- **New style `travel-diary`:** places in order, a stamp on each new place, prints and reflections between places, the payoff out of a beat of black.
- The critic's director notes gain story and shot-grammar rules. [Where the craft comes from](docs/craft-sources.md) lists the editing skills (graded safe in awesome-claude-video-skills) these ideas were read from; no code was taken.
- **Stabilising shaky clips.**
  - Handheld and shaky clips can be stabilised before they are rendered. TripShots uses ffmpeg's two-pass vidstab when the ffmpeg in use has it, and otherwise its own stabiliser, which tracks corners, smooths the camera's path over about a second and zooms in at most 12% to hide the moving edges.
  - A deliberate pan stays; only the shake goes. Each clip is stabilised once and cached in `~/.tripshots/cache/stab/`.
  - Style `shots.stabilize`: `auto` (the default) stabilises shaky clips in calm or held moments and never a shot given an added camera shake; `on` stabilises every shaky clip; `off` none. `cinematic`, `slow-scenic`, `grid-mosaic`, `mask-reveal` and `shape-cut` use `on`.
  - `make --stabilize`, MCP `make_reel stabilize`, plan edit `stabilize` and **Stabilise this clip** in the app's Shot tab. `tripshots doctor` says whether vidstab is available.
- **Strip collages, backdrop swaps and sideways reels.**
  - Split screens can be strip collages: `rows2`–`rows9` / `cols2`–`cols9`, filling in on the beat, in upright and wide reels.
  - `motion.backdrop` keeps a person still while the background swaps to other places of the trip, or to flat colours from the shot, on each beat. It is used only on an upright figure the cut-out finds.
  - `--orientation sideways` makes a widescreen edit turned on its side in an upright file, for "turn your phone" reels.
  - New styles `swap-strips` and `turn-phone`. `swap-strips` opens on a clip of you facing the camera (`motion.backdrop_first`).
  - The plan edit `backdrop`, and **Behind the person** in the app's Shot tab, put the swap on any clip of you.
  - Short reels made on a short reference sound can still have a strip moment.
  - The stutter check leaves out shots with a photo wall or a background swap.
- **The grid trend.**
  - A fine grid of light lines over the whole reel (plan `grid`).
  - The `cells` transition fills the next shot in cell by cell, spreading from one spot, with soft colour blocks on the way.
  - A photo wall (`motion.mosaic`): mid-reel, the cells round you fill with pictures of other moments of the trip, one per moment, hold, and clear again; the cells you stand in stay clear.
  - The new `grid-mosaic` style puts it together, in 4:3 with an 8x6 grid like the trend.
- **4:3, 4:5 and square reels.** `--orientation 4:3` (1440x1080), `4:5` (1080x1350) or `1:1` (1080x1080), or style `frame.output`: the picture fills that shape.
- **`make --light golden|sunset|blue|day|night`** holds a reel (and its photo wall) to shots in that light, from what the AI saw in each shot. It prefers them instead when too few are.
- Styles without the story planner also use one shot per landmark, and the photo wall shows each landmark once and none the reel already shows.
- **Masked reveals on the beat, and a style built on them.**
  - Three new transitions: `split` (a line swings round a corner, 45° on each beat), `vsplit` (a V opens from the bottom or top edge) and `iris` (a circle grows from the middle with a soft rim, a ripple and a glow).
  - The line and the V snap on every beat and hold in between, with a thin white edge, the way CapCut masking tutorials keyframe them.
  - The new `mask-reveal` style puts one on every cut (line reveals, then V reveals, then circles) via style `transitions.order` and `transitions.beats`.
  - Also available in the app's Shot tab and through `edit_plan` `transition`.
- **Paper-shape cuts and colour that blooms in.**
  - Three more transitions build the next shot from pieces, each a cream paper block before the picture shows through: `slats`, `stripes` and `diamond`.
  - `motion.colour_in` makes each shot arrive in black and white and bloom into colour.
  - `frame` builds the next shot as a centred window, then panels round it, with thin gaps still showing the old shot, until it snaps whole.
  - `motion.silhouette` flashes the people in a shot paper-white for two frames as it lands. Only upright figures are used, so a car or a rock never flashes.
  - The new widescreen `shape-cut` style uses all of these.
  - The stutter check no longer counts the frames inside transitions.
- **Cut to the song as it is, not to a metronome.**
  - Every song is read for where it has a beat to cut on. Beatless stretches (a pad intro, an ambient bridge, a quiet outro) hold their shots longer, melt them together with soft dissolves and don't pulse; segment `beatless`.
  - The song's climaxes are found (loudness, attack and brightness rising together) and the payoff goes on the biggest one. When the song goes quiet just before it, the shot before the payoff holds that breath and cuts cleanly on the hit (segment `breath`). The build into it shows something new every 1 to 1.5 s.
  - A reel speaks in at most three kinds of transition.
- **Movement that carries across every cut.** The camera at the end of each shot and the start of the next is measured. A pan left cut into a pan right, a push-in into a pull-back, or a fast move that stops dead is fixed where it can be: a Ken Burns move or a pan follows the camera, or a clip starts a moment earlier or later. Plan `continuity` lists what still jars, and the critic checks it.
- **The editor's habits, learned.**
  - `learn` measures where the references put a cut against the beat (a frame early, on the off-beat) and copies a clear habit; the beat check reports the reel's own offset.
  - It fits the references' camera moves to named eases; Ken Burns moves and pans follow the most common one (style and segment `ease`).
- **A critic that works in rounds.** Each round a fresh AI reviewer marks what is wrong as a blocker (fixed) or polish (noted). The next round first checks the changes with before/after proof and undoes any that made the reel worse. It stops when nothing blocks, when the list stops shrinking, or after `story.critic_rounds` rounds (default 3; the last only checks).
- **Notes on the finished reel.** `tripshots revise PLAN --note "12.3: too dark"`, MCP `revise_reel`, and the app's **Notes** tab (press N: it pauses, you say what you see, pins show on the timeline, send them together). The AI turns them into safe edits with a still of each moment (plain rules without an AI), renders again and says what it did for each note (`NAME.revise.json`).
- **More checks after every render.** `flash` (a stray bright frame), `cut_light` (a jarring brightness jump across a hard cut), `stutter` (repeated frames in a moving shot). A render that writes no new file now stops with an error instead of leaving the old video in place.
- **Reference reels recorded off a phone screen.** `learn` and `clone` cut the reel out of the phone's interface (keeping its own letterbox) and fix phase-cancelled stereo before measuring.
- **Subtitles in groups the eye takes in:** a long line is split into 2-3 words when said fast, up to 6 when slow, only while each group stays long enough to read.
- **Posting.** `tripshots post NAME.mp4 --platforms instagram,tiktok [--at ... --tz ...] [--send]` through Upload-Post. It is a dry run unless `--send`, takes only reels whose checks passed, and never sends the same post twice. MCP `post_reel`.
- **Grading parts of the frame, like a colourist.** Each shot gets layers after the primary grade, each with its own exposure, contrast, saturation, warmth, tint and hue:
  - Regions: sky (above the skyline, clouds included), subject (found in the frame from faces or a quick cut-out), skin, greens, water, ground (a graduated filter) and edges (a relight around the subject).
  - The AI colourist looks at each frame and proposes what it needs; without an AI, rules hold back bright skies, lift people in shade and ease the edges down.
  - Masks follow the picture frame by frame without flicker, and layers are applied while compositing (about 25 ms a frame), so editing one never re-renders a shot.
  - In the app: Colour > Layers, with a mask view on the picture.
  - Plan edits `layer` and `layers_auto`; segment `layers`.
- **Looks copied from reels now look like the reels.**
  - `tripshots look <reels>` also measures each colour family's hue and saturation. A look made this way moves your shots family by family: teal-cyan skies when the references have them, olive greens, golden light.
  - Each tonal zone is taken to the references' tint from where the shot starts, so blue-white snow under a golden look turns golden. The move is capped, so warm sand doesn't turn cyan.
  - The look is applied fully rather than as a hint.
  - Faces in shade stay readable.
- **More looks, and any LUT as a look.**
  - Twelve new built-in looks. Cinematic: `cinematic-film`, `blockbuster`, `bleach-bypass`. Travel: `coastal`, `desert-warm`, `alpine`, `tropical`, `forest-moody`. Light and people: `night-neon`, `blue-hour`, `portrait-film`, `documentary`, `black-and-white`.
  - The film looks finish like a print: soft highlight roll-off, and bright colours thin out.
  - `tripshots looks add` turns any `.cube` file or HaldCLUT image (files, folders, zips, links) into a look. Each shot is balanced first so shots still match, the LUT goes on top at the look's strength, and skin keeps more of its own colour.
  - Every LUT is measured and described in plain words. LUTs made for log footage, or that invert the picture, are never picked automatically.
  - `tripshots looks fetch gmic-creative` (33 creative LUTs) or `film-simulation` (RawTherapee's film emulations) downloads a free pack on request; they are not shipped with TripShots, since no licence is stated for redistributing them.
  - `look: auto` chooses among all of these for what the footage shows (coast, desert, mountains, jungle, forest, sunset, night), with or without an AI.
  - In the app: filters and search on the look strip, and **More looks** in the Colour tab. MCP `colour_looks`.
- **Edit a reel's words, and a timeline editor in the app.** The reel page shows a still of your edit at the playhead (the shot's cached picture with the text laid out exactly as the render will), so changes show without rendering. Every line of text can be changed: words, start and length, font (bundled faces and the open-font library, previewed in their own face), size, colour, position (bands or a click on the picture), animation, capitals, see-through letters, a small line above; lines can be added and removed and dragged on the timeline. An **Expert** switch adds a timeline editor: drag shots to reorder, drag an edge to change a shot's length (snaps to the beat), split, repeat, remove, insert a shot, which part of a clip plays, speed and ramps, transitions, framing, and the music's start, level and fade. Every edit can be undone and redone. New plan edits (`planedit`, MCP `edit_plan`): `add_text`, `edit_text`, `delete_text`, `duration`, `slip`, `split`, `delete`, `duplicate`, `insert`, `music`; MCP `plan_texts`; plan `music.gain_db`; overlay type `text`. API: `/api/still`, `/api/fonts`, `/api/font`, `/api/undo`, `/api/redo`.
- **Colour grading in the editor.** The reel page's Colour panel picks the reel's look (built-in, made with `tripshots look`, learned, or none) with its strength, grain and vignette, and corrects one shot on top of it: exposure, contrast, saturation, warmth, tint, shadows, highlights, or no look at all; corrections can go on every shot. The preview shows the grade from the source right away, and Hold to compare shows the shot as filmed. Plan edits `grade` and `adjust` (MCP `edit_plan`), segment `adjust` / `no_grade`, `/api/still?raw=1`.
- **Captions written for reach** (`tripshots caption PLAN [--tone] [--extra]`, MCP `write_caption`, the app's **Write it for reach**): a hook first line under 125 characters naming the place, search keywords worked into the caption, one ask for a send, a save or an easy comment, 3 to 5 specific hashtags, search keywords, alt text, a first comment to pin and two other opening lines, from what the reel shows (never invented). Saved as `NAME.caption.txt` (ready to paste) and `NAME.social.json`. Without an AI an honest caption is built from the places and subjects.
- **Desktop app for macOS, Windows and Linux** (`desktop/`, Tauri 2 + Svelte): a gallery of your reels, a player with the caption and the sound to add, a timeline where any shot can be swapped and re-rendered, new reels, Ask, learning styles, an activity view of every job (also those from the CLI and agents), and settings. The app is small; the engine is downloaded once from the release, checked against TripShots' signature, and updated on its own. Settings puts `tripshots` on the command line and adds TripShots to Claude Desktop (MCP). See [docs/desktop.md](docs/desktop.md). The window moves by dragging its top edge and zooms on a double-click there, like other Mac apps. Light and dark themes (System, Light or Dark, in Settings and the sidebar), timecode in mono throughout, a timeline with an ember playhead that follows the video.
- **Ask makes the reel you asked for.** "A reel with all my drone footage" now finds drone footage (new `find --camera drone|phone|action|camera`, told from the camera model, what the AI saw and camera file names), picks one of your learned styles and one of its reference reels as the sound (so the reel follows that reel's cut and words, avoiding sounds your recent reels used), and renders it. It no longer leaves a reel silent or plans without rendering in the app. When nothing matches it says what it searched for and asks one question, and the app's Ask screen shows what it understood, what it found (with a contact sheet), progress, the question with a reply box, and Open the reel.
- **AI setup in the desktop app** (Settings > AI): the status of Claude Code, MiniMax, the Claude API and Gemini, step-by-step setup for each with links, Terminal buttons that install and log in to Claude Code, key fields that save and remove keys, a Test that sends one short request, and the choice of which AI makes the creative calls. The gallery points there when no AI is set up. API: `GET /api/ai`, `POST /api/ai/test`.
- **`tripshots serve`**: the app's local API (JSON over HTTP on 127.0.0.1 with a token): status, settings, reels and their timelines, media with byte ranges, plan edits, captions, and the same background jobs as the MCP server.
- **Frozen engine and releases**: `packaging/engine/` builds the engine with PyInstaller and packages it (ffmpeg bundled on Windows and Linux, smoke test, signed archive, `engine.json` manifest); `.github/workflows/release.yml` builds and publishes the engine and the app for all platforms from a version tag (`tools/set_version.py`).
- Background jobs work in the frozen engine and on Windows.
- **A reference's own words, exactly.** `learn` now reads every piece of text a reference puts on screen (reftext.py): a small text detector (PP-OCRv4, ONNX, ~5 MB, fetched once) finds each line and when it is up, and the AI copies the words from close-ups, in their own language and spelling, telling them apart from signs in the scene and watermarks. A reel made on that reference's sound shows those words at their own times, place, size and colour. Lyrics and subtitles are never transcribed from the sound any more, and anything only partly readable is left out: a recipe reel shows the reference's words exactly, or none.
- **Fonts like the reference's.** A library of about a hundred open fonts (Google Fonts, SIL OFL; serif, rounded, condensed, script and Malayalam/Tamil faces) is fetched once into `~/.tripshots/fonts/gf`; the AI compares the reference's lettering with each of them setting the same words and the closest is used for the reel's text. Text whose lettering nothing in the library resembles (hand-drawn titles) is left out rather than shown in a standard face. Fonts are named `gf:Family:weight` in styles and plans.
- **Postcard letters you can see through.** A labels reference with colourful postcard lettering gets block capitals filled with the footage itself (saturated), a light rim, a dark extruded edge and a yellow script "Greetings From..." line (overlay style `fill: picture`, `lead_color`).
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
- **The desktop app, redesigned** (with the unslop and ui-ux-pro-max skills):
  - **Make** replaces New reel and Ask: describe the reel or choose everything yourself, and the job's progress shows on the same page in named steps, with the question it asks and Open the reel.
  - **Before and after** in the Colour tab splits the viewer between the shot as filmed and your edit, with a divider you drag or move with the arrow keys.
  - **A reel opens as an editor on one screen**: the viewer, an inspector with Text, Colour and Post tabs (Expert adds Shot and Sound), and the timeline always in view. The Colour tab shows each look on your own shot.
  - Removing a shot or a line offers Undo right away, and every drag on the timeline has a button too.
  - **Styles** lists yours first, with Make a reel on each, and learning a style moves into a side sheet.
  - **Activity** says each job's state in words and shows its steps.
  - Settings save as you change them and have a section index.
  - The gallery filters upright, wide, plans and edited reels.
  - ⌘1 to ⌘4 move between the sections and ⌘, opens Settings. Contrast is checked in both themes, and the keyboard reaches everything.
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
- **A long series uses the whole trip.** The shown-before memory only counted the last 12 reels, so a series of 30 reels from one trip forgot its first reels and went back to the same top-scored clips (31 reels used 294 of 6,770 usable shots; the later reels were almost all repeats). Every remembered reel of the same footage now counts (up to 300).
- **A universal note is shown as written.** When the copywriter keeps all of a reference's own words (they fit any trip), the reel shows them exactly as and when the reference does; keeping one line ("this is") no longer copies the rest ("the faroe islands").
- **No line of our own over someone else's lyrics:** a lyrics reference whose words can't be copied gets no text.
- **Loudness:** after lifting a quiet master, peaks that AAC pushes over -1 dBTP are trimmed again.
- **Parallax no longer bends people.** Photo parallax moved every pixel by its own depth, so a person (nearer at the feet than the head) was sheared. Things that stand out in front now move as one flat layer; only the background just outside them stretches.
- **Titles name the trip:** a title modelled on a reference title in another language (\"Engotta\") is no longer a lone word like \"Touched\"; it names our trip, place or season.
- **Balanced lines:** a title that needs two lines splits them evenly ("The urge to / keep driving."), never one word hanging under a full line.
- **One landmark, once:** a reel no longer shows the same landmark twice from different angles (two Half Domes), neither from the planner nor from the AI critic's swaps.
- **Recipe reels follow their example more closely:** the style's averaged split screens are left out of a single example's cut; subtitles appear only for the stretch the example subtitles (a spoken opening, not the song after it), and an example that shows no words over its own voice gets none; a tease the example leaves unanswered ends in three dots ("Just us, the rig, and the..."); a pause in the lyrics ("…") is not shown as a word.
- **Text that clashes with the picture:** a coloured line (an example's red over a red rock) gets an outline and a soft shade behind it.
- **Grey openings:** a nearly colourless clip is marked down as a long opening hold, and the opening, the turn and the last shot of a colourful reel never go to a grey shot.
- **One text at a time:** a recipe whose example shows its own words (a note, a title, the lyrics) no longer gets subtitles of its voice underneath saying the same thing; a run of answer lines is written no longer than the example's, so each can be read in the time it is up.
- **Subtitles stay put:** consecutive subtitle lines no longer overlap for a moment, which made the next line jump to another part of the screen.
- **Loudness:** a peaky song that the limiter held down is lifted into its remaining headroom, so the master lands at -14 LUFS instead of around -16.

### Fixed
- The light-leak transition was drawn in blue instead of amber (its colours were in the wrong channel order).
- **Malayalam and other complex scripts in the app's engine.** The packaged engine couldn't find its own text-shaping library, so vowel signs came apart from their letters ("ഓരോ" drawn as "ഓരേ ാ"). It now finds it at start-up (only that library, and never passed on to ffmpeg); `tripshots doctor` reports `shaping`, and a release can't be packaged without it.
- **Words that disappeared on bright pictures.** Light lettering is now shaded on every frame where what is behind it is bright (pale sky, sunlit aspens, white rock), including a line held across several shots, not just on its first frame.
- **Words across a face.** A line, even one placed at the reference's own height, now moves off a face in the shot.
- **A title too long for its band** (a reference's title card rewritten as one long line) is set smaller to fit on screen and stays long enough to read every word.
- **The swap opening** now opens on a person big in the frame. The AI's subject boxes come as lists and weren't being read, so a far drone shot could be picked and the background swap never showed.
- **Gemini watch** switches to the next model at once when one answers "not found" or its daily quota is used up, instead of waiting on the request pacer first.
- **Mastering a reel whose encode overshot its peaks** turned the whole mix down and stopped there, leaving it around -16 LUFS; it now lowers the limiter's ceiling instead and keeps -14 LUFS. Music turned down in the editor is made up in the master rather than making the reel quieter.
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
