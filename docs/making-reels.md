# Making reels

The everyday loop: point TripShots at footage and a song, check the plan, render, post. Every command here prints JSON, so scripts and agents can use it too.

## The basic commands

```bash
# 1. Make a reel. Point it at one or more folders (SSD + phone export).
#    Subfolders are searched automatically (Day1/, drone/, DCIM/100MEDIA/...).
tripshots make "/Volumes/SSD/Trips/Banff" ~/Pictures/BanffPhone --music ~/Music/track.mp3

# Many folders? Put them in a text file, one per line, and pass it with @
tripshots make @banff-folders.txt -m track.mp3

# Narrow it down: only these dates, skip some subfolders or files
tripshots make /Volumes/SSD/2026 -m track.mp3 --since 2026-07-01 --until 2026-07-09 \
  --exclude '*/timelapse/*' --exclude 'DJI_*.JPG'

# 2. Pick a look
tripshots styles
tripshots make ~/Trips/Banff -m track.mp3 --style cinematic -d 20

# 3. Add a text hook, or fix the location label
tripshots make ~/Trips/Banff -m track.mp3 --style pov-hook --location "Moraine Lake, Alberta"
tripshots make ~/Trips/Banff -m track.mp3 --hook "POV: you woke up at 4am for this"

# Preview the plan only (fast, no render)
tripshots make ~/Trips/Banff -m track.mp3 --dry-run

# See what the AI thinks of your footage
tripshots scan ~/Trips/Banff --top 20
```

**Everything is remembered per file, forever.** TripShots keeps a library in `~/.tripshots/library` with each file's metadata, its local shot analysis and thumbnails, and the AI's verdict on every shot. Files are recognised by their content, not their path, so the library still applies if you combine folders differently, add a few new clips, filter by date, rename a folder, or the SSD mounts under another name. Only footage the AI has never seen is sent to it. Each run prints how many files were already known and how many shots were already judged.

```bash
tripshots library               # what's stored: files, shots, AI verdicts, disk use
tripshots make ... --rescore    # ask the AI again about these shots (e.g. after switching backend)
tripshots library --forget-ai   # drop all stored AI verdicts, keep the footage analysis
tripshots library --wipe        # start completely fresh
```

Instead of folders you can pass a search result: `tripshots find --place Lisbon` prints `sel:<id>`, and `tripshots make sel:<id> -m song.mp3` uses exactly that footage. See [Finding footage](finding-footage.md).

## What you get per reel

| File | What it is |
|---|---|
| `NAME.mp4` | The reel: 1080×1920 (or 1920×1080 for a [horizontal reel](#horizontal-reels)), 30 fps, H.264 + AAC, ready to upload |
| `NAME.cover.jpg` | Cover frame (from the hook shot) |
| `NAME.caption.txt` | AI caption + hashtags (only when an AI backend is used) |
| `NAME.storyboard.jpg` | Every shot in order with timing (in its graded colour), so you can review before posting |
| `NAME.grade.jpg` | Before / after of the colour grade for each shot |
| `NAME.plan.json` | The edit decision list. Change it and run `tripshots render` |
| `NAME.qa.json`, `NAME.qa.jpg` | Quality checks on the finished file (format, length, loudness, black/frozen/silent stretches, text in the safe area and readable) and a contact sheet of 12 frames. See [Checks after every render](#checks-after-every-render) |
| `NAME.text.json` | Every title as it was laid out: where, how big, for how long, how it animates |
| `NAME.edl`, `NAME.storyboard.md` | The same edit for DaVinci Resolve / Premiere, and as a readable shot table (see [Finish in a real editor](#finish-in-a-real-editor)) |

## Styles that ship with it

| Style | Feel |
|---|---|
| `beat-montage` | Fast hard cuts every 1–2 beats, vivid grade. The classic viral travel montage. |
| `pov-hook` | Big AI-written POV headline in the first 3 s, then a medium-paced montage |
| `cinematic` | Long shots, slow motion, crossfades, warm grade with vignette |
| `slow-scenic` | Calm and chronological, one cut per bar, gentle pans, natural colour |
| `split-beat` | Split screens, speed ramps, bass-hit pulses and shot labels on a fast grid |
| `mask-reveal` | Every shot comes in through a shape on the beat: line and V reveals with a white edge, then growing circles with a glow (no text) |
| `swap-strips` | Widescreen: you hold still while the places of the trip swap behind you on the beat, then strip collages of clips |
| `turn-phone` | A widescreen edit turned on its side ("turn your phone"): strip collages, you against flat colours, white silhouette flashes, paper slats and stripes |
| `grid-mosaic` | 4:3. A fine grid over the reel, shots filling in cell by cell, and a photo wall of the trip round you mid-reel |
| `shape-cut` | Widescreen and editorial: each shot built from cream paper pieces (slats, a diamond, stripes), arriving in black and white before its colour blooms in |
| `travel-diary` | A scrapbook of the trip: each place opens wide and lands with a passport stamp, prints drop in and open into the next place, lakes arrive as their own reflection, and the payoff comes out of a beat of black |

Make your own with `tripshots learn` (below) or by copying one: see [Styles](styles.md).

## Holding a reel to one light

`make --light golden` uses only shots in golden light (golden hour, sunset and sunrise), the photo wall's pictures
too; `sunset`, `blue` (blue hour and night), `day` (morning to afternoon) and `night` work the same way. The light
is what the AI saw in each shot when it judged it. When fewer than about 40 shots are in that light, they are
preferred instead of required (style `shots.light`).

## Horizontal reels

Instagram plays horizontal video too, so a wide picture gets a wide file instead of black bars in an upright one:

```bash
tripshots make ~/Trips/Iceland -m song.mp3 --orientation horizontal
```

| `--orientation` | What you get |
|---|---|
| `auto` (default) | 1080×1920 upright. 1920×1080 horizontal when the style or the recipe you follow is wide (`frame.aspect` 4:3, 16:9, 2.39:1), or when every shot is landscape and most of them can't be cropped upright |
| `horizontal` | Always 1920×1080: the picture fills the frame, upright clips are cropped around their subject |
| `vertical` | Always 1080×1920: a wide picture sits in a band with the words in the bars (the old letterbox) |

The text is laid out for the wide frame and set larger, because a phone held upright shows a horizontal video small. Split screens and pop-out frames are upright layouts and are left out. A style can fix the shape with `frame: {output: horizontal}`.

## Versions to test (`--variants`)

```bash
tripshots make ~/Trips/Iceland -m song.mp3 --variants 3
```

This makes three versions: each opens on a different strong shot, orders the middle differently, varies the transitions, and gets a hook from a different angle. `NAME.variants.jpg` shows them side by side with their hooks. It's made for Instagram's **trial reels** (shown to non-followers first): post two or three and keep the winner. Analysis, AI verdicts and grading are cached, so extra versions only cost render time.

## Several reels from one trip

Just make them one after another. Each rendered reel is remembered, and the next one is cut from other shots: it
opens on a different shot and leaves out what the earlier reels showed (unless the footage is nearly used up, when
the best shots come back). With a learned style, give each reel a different example to follow (`-m <reel link>` or
`--recipe N`), so the series also differs in shape: one opens on a long shot, one names every place, one is cut to
the lyrics. `--fresh off` makes a reel as if it were the first. More: [A series from one trip](storytelling.md#a-series-from-one-trip).

## Learn a style from reels you like

```bash
tripshots learn https://www.instagram.com/reel/AAA/ https://www.instagram.com/reel/BBB/ \
  --name my-vibe --cookies-from-browser auto
tripshots make ~/Trips/Iceland -m track.mp3 --style my-vibe
```

`learn` downloads the reels and finds every cut. It measures how many beats each shot lasts, what share of cuts land on the beat, the colour grade, and the first-shot length. Then it shows sampled frames to the AI, which describes the text hook, transitions and mood. The result is saved as `~/.tripshots/styles/my-vibe.yaml`, plain YAML you can tweak.

A learned style copies more than timing:
- **Taste.** The references' light and colour (and the kind of light and of people the AI sees in them: golden backlight, people seen from behind) steer which of your shots are chosen, so a moody golden-hour reference doesn't get your bright blue-sky postcards.
- **Shape.** A widescreen reference makes a [horizontal reel](#horizontal-reels): a 1920×1080 file the picture fills (`frame: {aspect: 16:9}`).
- **Look.** The references' grade is applied at full strength (`grade: {match: full}`): every shot is taken into the mood, not just tinted.
- **Pace and movement.** Shots are held as long as the references hold theirs, and pans move as slowly as the references' camera (`layout.pan_speed`).
- **Format and text.** The format is fixed (no numbered place cards in a cinematic reel), and the references' own text decides whether a hook line appears.
- **Taste is a nudge, not a filter.** What looks like the examples is preferred *among your own shots*, by a bounded amount: a clearly better shot still wins, and a reel is still spread over the places of the trip.

- **How it holds attention** (the style's `attention` profile). Different reels earn attention differently, so nothing here is a fixed recipe; it is measured from your examples:
  - *rhythm over time*: where the reference cuts fast and where it holds, in each eighth of its length. Your reel follows the same shape on its own song's beats;
  - *the opening*: how long the first shot is held and what it shows (a person, a wide view, a detail, movement);
  - *the payoff*: where the long hold sits;
  - *the shot mix*: the share of wide views, people and details;
  - *speed, reveal, loop*: slow motion or speed changes, whether the best view is held back, whether the end flows into the start.

  The check before rendering judges the reel against this profile: a calm style may hold its shots, a fast one may not drag.

- **One recipe per example** (the style's `recipes`). Averages lose the trick that made each reel catching, so every example is also kept whole: how it is cut (a long opening shot and then a burst of short ones; flashes and then steady shots; even shots; a montage), its own shot lengths, its picture shape, and what its words do (the song's lyrics one word at a time; a tease line and then the payoff; one title for the whole reel; a title per shot; none), with their lettering, colour and place. Each reel you make follows **one** recipe:
  - with the sound of one of the examples (`-m <that reel's link>`), that example's recipe, cut for cut: the music starts at 0:00 and the cuts sit where the original's do;
  - with any other song, the recipe that fits the song best (its length, tempo, and whether it has words);
  - `--recipe 3` asks for the third example's, `--recipe off` for the style's average. `learn` prints the list, and so does the app's **Styles** tab.

  A recipe that opens on a long hold needs one continuous, moving clip of that length. If your footage has none, the best clip is slowed to cover it and the log says so.

**Several examples per style.** A style is what its examples have in common, so 2–3 similar reels give a steadier profile than one. Add more any time: `tripshots learn <new links> -n my-vibe --add`, or in the app's **Styles** tab **Add example reels…**. The tab shows each learned style's examples and its attention profile in one line, and **Re-learn** rebuilds it from the saved examples (nothing is downloaded again). Keep different kinds of reels in different styles.

**Reels recorded off a phone screen work too.** A screen recording of a reel is the reel inside the phone's interface:
the status bar, the buttons, the caption and the counts. Before it is measured, the reel's 9:16 window is cut out
around the moving picture (a letterbox inside the reel is part of its look and stays), and sound whose left and
right cancel each other out (some recordings) is fixed, so the beat can be heard. The cleaned copy is kept in
`~/.tripshots/learn/clean/`; reels downloaded normally are used as they are.

Styles learned before this version don't have these: re-learn one with `tripshots learn -n my-vibe` (no links: it uses the reels it was learned from, already downloaded). Instagram usually needs your browser login for downloads, which is what `--cookies-from-browser` is for. You can also pass local `.mp4` files you saved.

## Checks after every render

After each render TripShots checks the file the way an editor would before posting, and logs what failed:

| Check | Passes when |
|---|---|
| format | 1080×1920 (1920×1080 for a horizontal reel), about 30 fps, H.264 video and AAC sound |
| length | 3 to 90 seconds (longer reels are shown less) |
| loudness | about -14 LUFS (-16 to -12) with true peaks at or under -1 dBTP |
| black, frozen, silence | no black picture over 0.4 s, no frozen picture over 1.2 s (the plan's freeze frame excepted), no silent gap over 1 s under music |
| text_safe | every title clear of Instagram's buttons, name and caption |
| text_size | hook at least about 88 px tall at 1080 wide, labels 64, captions 54 |
| text_time | each line on screen for at least its words at 3.5 a second, plus half a second |
| flash | no single white frame or exposure pop the plan didn't ask for (flash transitions and the freeze excepted) |
| cut_light | no jump of more than about a third of the brightness range across a hard cut (bright noon straight into a dark room) |
| stutter | no repeated frames inside a moving shot: a variable-frame-rate phone clip, or slow motion without in-between frames, hitches |

The results are in `NAME.qa.json`; `NAME.qa.jpg` shows 12 frames with their times. A render that doesn't write a
new file stops with an error, so a failed re-render never hands back the previous video. Run them again on any video with
`tripshots qa NAME.mp4` (MCP `check_reel`). The set of checks follows the [one-take](https://github.com/KaranO-Dev/one-take-skill) skill's QA pass.

## Edit by hand (or with Claude)

`NAME.plan.json` lists every segment: `shot_id`, `dur`, `in` (start time in the source), `speed`, `layout` (`crop`/`pan`/`fill`/`blur_fill`/`kenburns`), `subject_x` (where to crop, 0 = left, 1 = right) and `trans_out`. `overlays` holds the hook and location text. After editing:

```bash
tripshots render reels/Banff-beat-montage-2026....plan.json
```

To swap a shot, set `shot_id` to another id from `tripshots scan`. Only changed segments are re-rendered.

**Easiest:** open this folder in Claude Code and talk to it ("make a 15s reel from my Banff folder with this song, cinematic, and swap shot 4 for something with water"). `CLAUDE.md` and the bundled `make-reel` skill tell it how to drive TripShots and review the storyboard.

**Notes on the finished reel.** Watch it, and where something is off say what you see, pinned to that moment:

```bash
tripshots revise reels/NAME.plan.json --note "3.5: way too dark" --note "12.1: swap this for the canyon" \
  --note "0:18 the words cover her face"
```

Each note is tied to the shot and the text on screen at its time. The AI gets a still of the reel at every note
and the other shots available, and answers with safe plan edits (a shot swapped, colour, text, framing, speed);
without an AI, plain rules handle the common ones (brighter, darker, warmer, cooler, replace this shot, cut it,
faster, slower, remove the text). The reel is rendered again (`--no-render` to only edit the plan), every edit
can be undone, and `NAME.revise.json` says what was done for each note. In the app: the **Notes** tab
([desktop app](desktop.md)); MCP `revise_reel`.

**Posting.** `tripshots post NAME.mp4 --platforms instagram,tiktok [--at 2026-12-01T18:00 --tz Europe/Madrid]`
posts through [Upload-Post](https://upload-post.com) (set `UPLOAD_POST_KEY` and `UPLOAD_POST_USER` in
`~/.tripshots/.env`). It is a dry run that shows what would be posted unless you add `--send`; it takes only reels
whose checks passed (`--force` otherwise), uses the caption written for the reel and its hook as the title, and
never sends the same post twice (`--again` to repost). MCP `post_reel` (always a dry run first).

The full plan format is in [plan.json reference](plan-format.md). Agents can use `edit_plan` instead of editing JSON: see [AI agents](agents.md).

## Finish in a real editor

Every plan is also written as `NAME.edl` (CMX3600: source file, in/out, speed changes, comments for tripshots-only effects) and `NAME.storyboard.md` (a shot table you can read or paste anywhere). For DaVinci Resolve, Premiere or Final Cut:

```bash
tripshots export reels/NAME.plan.json            # .edl + .otio + .storyboard.md
tripshots export reels/NAME.plan.json --otio     # just OpenTimelineIO (pip install opentimelineio)
```

Import the EDL (Resolve: File → Import → Timeline) or the OTIO, point it at your footage folder, and the cuts, in-points and slow motion line up with the music track. Text, the grade, maps, split screens and the freeze are TripShots' own drawing: they come across as comments and markers, not rebuilt effects.

To finish a reel in Instagram's Edits app instead (text, sound effects and the song stay editable there), see [Finish in Edits](edits.md).

## Action cams, drones and 360 cameras

* **Insta360 / GoPro MAX:** raw `.insv` / `.insp` files and full equirectangular exports (2:1, 2880 px wide or more) are skipped with a note: reframe them first in Insta360 Studio (Auto Frame) or GoPro Player and drop the flat export in the folder.
* **GoPro / DJI preview files** (`.LRV`, `.LRF`, `.THM`) are ignored, so they never show up as low-res duplicates.
* **Capture times from file names** (`DJI_20260501123000_…`, `VID_20260501_124500`, `PXL_…`) when a camera wrote no date, or wrote UTC: when the metadata and the file name differ by a whole time-zone offset, the file name (local time) wins, so drone and phone shots of the same afternoon sort together.

## What it handles for you

* **Messy folders:** any number of source folders, searched recursively. It skips hidden files, macOS `._` sidecar files on exFAT SSDs, iPhone Live Photo motion clips, reels it made earlier, and exact duplicate copies (the same clip on the SSD and in the phone export). Clips shorter than 1 s are skipped too.
* **iPhone HDR (HLG) and HDR10:** tone-mapped to SDR, so footage doesn't look grey or washed out on Instagram
* **Rotated phone video, HEIC photos, EXIF orientation**
* **Landscape to vertical:** the AI says where the subject is (`subject_x`) and the crop follows it. Panoramas become slow pans.
* **Photos:** smooth sub-pixel Ken Burns (no zoompan jitter)
* **Hardware video encoding:** on a Mac, encoding uses the Mac's built-in video engine (VideoToolbox); on a PC, an NVIDIA (NVENC) or Intel (Quick Sync) encoder. Each is tested once with a real 1080×1920 encode before it's used, and if it fails mid-render the rest of the render switches to libx264 by itself. `--encoder auto|hardware|software` (or `TRIPSHOTS_ENCODER`, or the app's Settings tab); `tripshots doctor` shows which one is in use. Software encoding gives slightly smaller files at the same quality; Instagram re-encodes every upload anyway.
* **High-fps clips (60/120 fps):** half-speed slow motion in calmer sections (styles with `slowmo: true`). 24/30 fps clips get optical-flow in-between frames when slowed down, and speed ramps and speed-ups are placed on the beat ([Speed](look-and-motion.md#speed))
* **Shaky or blurry clips:** pushed down or dropped. Long clips are split into chunks, and the steadiest, sharpest window is used.
* **Location labels:** from photo/video GPS via OpenStreetMap (cached), or `--location`
* **Instagram safe zones:** text stays out of the areas the Reels UI covers


---
[Docs home](README.md)
