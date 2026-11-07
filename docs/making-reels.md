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
| `NAME.mp4` | The reel: 1080×1920, 30 fps, H.264 + AAC, ready to upload |
| `NAME.cover.jpg` | Cover frame (from the hook shot) |
| `NAME.caption.txt` | AI caption + hashtags (only when an AI backend is used) |
| `NAME.storyboard.jpg` | Every shot in order with timing (in its graded colour), so you can review before posting |
| `NAME.grade.jpg` | Before / after of the colour grade for each shot |
| `NAME.plan.json` | The edit decision list. Change it and run `tripshots render` |
| `NAME.edl`, `NAME.storyboard.md` | The same edit for DaVinci Resolve / Premiere, and as a readable shot table (see [Finish in a real editor](#finish-in-a-real-editor)) |

## Styles that ship with it

| Style | Feel |
|---|---|
| `beat-montage` | Fast hard cuts every 1–2 beats, vivid grade. The classic viral travel montage. |
| `pov-hook` | Big AI-written POV headline in the first 3 s, then a medium-paced montage |
| `cinematic` | Long shots, slow motion, crossfades, warm grade with vignette |
| `slow-scenic` | Calm and chronological, one cut per bar, gentle pans, natural colour |
| `split-beat` | Split screens, speed ramps, bass-hit pulses and shot labels on a fast grid |

Make your own with `tripshots learn` (below) or by copying one: see [Styles](styles.md).

## Versions to test (`--variants`)

```bash
tripshots make ~/Trips/Iceland -m song.mp3 --variants 3
```

This makes three versions: each opens on a different strong shot, orders the middle differently, varies the transitions, and gets a hook from a different angle. `NAME.variants.jpg` shows them side by side with their hooks. It's made for Instagram's **trial reels** (shown to non-followers first): post two or three and keep the winner. Analysis, AI verdicts and grading are cached, so extra versions only cost render time.

## Learn a style from reels you like

```bash
tripshots learn https://www.instagram.com/reel/AAA/ https://www.instagram.com/reel/BBB/ \
  --name my-vibe --cookies-from-browser chrome
tripshots make ~/Trips/Iceland -m track.mp3 --style my-vibe
```

`learn` downloads the reels and finds every cut. It measures how many beats each shot lasts, what share of cuts land on the beat, the colour grade, and the first-shot length. Then it shows sampled frames to the AI, which describes the text hook, transitions and mood. The result is saved as `~/.tripshots/styles/my-vibe.yaml`, plain YAML you can tweak. Instagram usually needs your browser login for downloads, which is what `--cookies-from-browser` is for. You can also pass local `.mp4` files you saved.

## Edit by hand (or with Claude)

`NAME.plan.json` lists every segment: `shot_id`, `dur`, `in` (start time in the source), `speed`, `layout` (`crop`/`pan`/`fill`/`blur_fill`/`kenburns`), `subject_x` (where to crop, 0 = left, 1 = right) and `trans_out`. `overlays` holds the hook and location text. After editing:

```bash
tripshots render reels/Banff-beat-montage-2026....plan.json
```

To swap a shot, set `shot_id` to another id from `tripshots scan`. Only changed segments are re-rendered.

**Easiest:** open this folder in Claude Code and talk to it ("make a 15s reel from my Banff folder with this song, cinematic, and swap shot 4 for something with water"). `CLAUDE.md` and the bundled `make-reel` skill tell it how to drive TripShots and review the storyboard.

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
* **High-fps clips (60/120 fps):** half-speed slow motion in calmer sections (styles with `slowmo: true`)
* **Shaky or blurry clips:** pushed down or dropped. Long clips are split into chunks, and the steadiest, sharpest window is used.
* **Location labels:** from photo/video GPS via OpenStreetMap (cached), or `--location`
* **Instagram safe zones:** text stays out of the areas the Reels UI covers


---
[Docs home](README.md)
