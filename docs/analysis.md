# Analysing footage

`tripshots analyze` describes every photo and video on its own, without making a reel: what's in it, how good it
is technically, when and where it was taken, with which camera, on which trip, and who is in it. The result is one
record per file in a documented, versioned format (`tripshots.media/1`), so it can be used by:

- **TripShots itself.** Reels made later reuse the AI verdicts instead of asking again.
- **Your other apps,** such as a collage maker or an album builder. They can read the JSON from any language, or use
  the Python API.
- **Other AI tasks:** search, captioning, sorting, and agents (through MCP).

```bash
tripshots analyze ~/Pictures/Trips /Volumes/SSD/Footage     # or no folders: your footage folders
tripshots analyze sel:1a2b3c4d                              # a search result from `tripshots find`
tripshots analyze ~/Trips --no-ai                           # technical analysis only (fast, free, offline)
tripshots analyze ~/Trips --cached -o ~/Desktop/trips-index # export what's already analysed, no new work
```

In the app: **Library → Analyse my footage**. For agents: the `analyze_footage` and `search_media` MCP tools.

## What it produces

`~/.tripshots/analysis/<name>/` (or `-o DIR`):

| File | What |
|---|---|
| `media.jsonl` | One JSON record per file, one per line (format below) |
| `summary.json` | Counts, people, places, the most common tags, trips, number of near-duplicate groups, the AI backend used, how long it took |
| `schema.json` | The JSON Schema the records follow (also in the package: `tripshots/schemas/media.schema.json`) |

Analysis is **incremental** and cached by file content in the library. Running it again, or making a reel from the
same footage, only analyses files it hasn't seen. Moving or renaming files doesn't matter: a file's `id` comes from
its content.

## The analyzers

| Analyzer | How | Runs where |
|---|---|---|
| **File and media** | ffprobe / Pillow: size, dimensions, orientation, duration, frame rate, HDR, audio, 360° | Your computer |
| **Capture time** | EXIF / QuickTime metadata, or the file name (`DJI_2025…`, `PXL_…`, `VID_…`), with time-zone correction; `captured.source` says which | Your computer |
| **Camera** | EXIF make, model, lens, focal length, aperture, shutter, ISO, flash; QuickTime make / model / software for videos | Your computer |
| **Shots** | A photo is one shot. A video is split at scene cuts and into chunks of at most 8 s; each shot's thumbnail is its sharpest, steadiest frame | Your computer |
| **Technical quality** | Per shot: focus (edge sharpness), brightness and exposure, clipped highlights and shadows, contrast, colourfulness, warmth and tint, dominant colours, a perceptual hash; for videos, camera motion | Your computer |
| **Near-duplicates** | Shots whose perceptual hashes differ by ≤ 8 of 64 bits share a `similar_group` (bursts, the same view twice, re-exports) | Your computer |
| **Faces and people** | YuNet + SFace face detection and recognition ([Finding footage](finding-footage.md#people)); names for people you've taught it | Your computer |
| **Place** | GPS → place name (OpenStreetMap, cached) | Sends GPS to OpenStreetMap (`--no-places` / `TRIPSHOTS_OFFLINE=1` to skip) |
| **Trip** | Files grouped into trips by time and distance, like `tripshots trips` | Your computer |
| **AI description** | Your AI backend looks at contact sheets of the shots and returns a caption, description, tags, subjects with boxes, scene, setting, time of day, weather, people count and activity, visible text, landmark, an aesthetic score, issues, and the reel judgements | Small stills go to your AI backend (`--no-ai` to skip) |
| **Gemini watch** (optional) | With `GEMINI_API_KEY`: the best instant, shake, tilt and the kind of sound in each video | 480p proxies go to Google |

### How reliable each part is

- **Focus** (`technical.sharpness`, 0–1, and `sharpness_label`: blurry / soft / sharp) judges how crisp the
  strongest edges are, so a smooth sky or a plain wall isn't marked blurry just for having little detail.
  - Calibrated on real photos measured at 480 px wide: crisp photos are 0.65–1.4 on `edge_sharpness`, and a 2-pixel
    blur brings them down to 0.2–0.6.
  - Very small images that were upscaled read as softer than they are.
- **Exposure, colour and palette** are plain measurements of the pixels. `exposure_label` is a guide: a night sky
  is "dark" on purpose.
- **AI description** is as good as the backend.
  - With Claude it reads signs, recognises famous landmarks and artworks, and counts people.
  - It is told never to guess a landmark it isn't sure of, and to describe only what is visible.
  - Compare `ai.issues` (what the AI saw) with `technical` (what was measured) when they disagree.
- **Faces** are missed when they're small, in profile, or covered by sunglasses or hats. `faces` lists only the
  faces that were found; `ai.people.count` is the AI's own count, which also includes people facing away.
- **Video shots** depend on scene-cut detection. A fast whip pan inside one take may not be split; the in-camera
  whip detection (watch.py) finds those for reels.

## The record

```json
{
  "schema": "tripshots.media/1",
  "id": "9f2c…",                          // from the file's content: stable across moves and renames
  "path": "/Volumes/SSD/Yellowstone/DJI_0042.MP4", "name": "DJI_0042.MP4", "kind": "video",
  "file":     {"size": 184233211, "modified": "2025-07-12T18:20:11", "extension": "mp4"},
  "media":    {"width": 3840, "height": 2160, "orientation": "landscape", "aspect": 1.7778,
               "duration": 24.5, "fps": 29.97, "hdr": false, "has_audio": true, "codec": null, "equirect": false},
  "captured": {"time": "2025-07-12T10:15:00", "day": "2025-07-12", "source": "metadata"},
  "camera":   {"make": "DJI", "model": "Mini 4 Pro"},
  "location": {"lat": 44.4605, "lon": -110.8281, "place": "Old Faithful, Wyoming"},
  "trip":     {"id": "trip-2025-07-12", "from": "2025-07-12", "to": "2025-07-14"},
  "people":   {"faces": 0, "names": []},
  "shots": [{
    "id": "9f2c…@0.000", "t0": 0.0, "t1": 8.0, "duration": 8.0, "best_moment": 5.25,
    "thumbnail": "~/.tripshots/library/thumbs/9f2c…_00000000b.jpg",
    "technical": {"sharpness": 0.94, "sharpness_label": "sharp", "edge_sharpness": 0.72, "laplacian_var": 412.0,
                  "brightness": 0.52, "exposure_label": "normal", "highlights_clipped": 0.002, "shadows_clipped": 0.0,
                  "contrast": 0.41, "colorfulness": 0.38, "warmth": 0.12, "tint": -0.03, "temperature_label": "neutral",
                  "palette": [{"hex": "#6f8fb2", "share": 0.41}, …], "dhash": "c3e1f0f8d8cc8484",
                  "camera_motion": {"label": "moving", "pan": 0.006, "shake": 0.0011, "activity": 0.02}},
    "ai": {"source": "claude-cli", "version": 2,
           "caption": "Old Faithful erupting into a clear blue sky, seen from the air",
           "description": "An aerial view of Old Faithful geyser mid-eruption …",
           "tags": ["geyser", "eruption", "steam", "aerial", "blue sky"],
           "subjects": [{"label": "geyser plume", "box": [0.38, 0.12, 0.61, 0.78]}],
           "scene": "aerial", "setting": "outdoor", "time_of_day": "morning", "weather": "clear",
           "people": {"count": 0, "activity": ""}, "text": "", "landmark": "Old Faithful",
           "aesthetic": 9, "issues": [], "usable": true},
    "faces": [],
    "similar_group": null,
    "uses": {"reel": {"score": 9, "role": "hook", "mood": "dynamic", "motion": "drone",
                      "subject_x": 0.5, "subject_box": [0.38, 0.12, 0.61, 0.78], "note": "eruption from above"}}
  }],
  "analyzed": {"at": "2026-11-07T04:10:00", "generator": "tripshots", "versions": {"shots": 5, "technical": 3, "ai": 2}}
}
```

Field notes:

- **Boxes** (`subjects[].box`, `faces[].box`, `subject_box`) are `[x0, y0, x1, y1]` as fractions 0–1 of the
  picture, origin top-left.
- **Times** (`t0`, `t1`, `best_moment`, `faces[].t`) are seconds from the start of the file.
- **Scales:**
  - `ai.aesthetic` is 1–10 as a photograph anyone would want to keep.
  - `uses.reel.score` is 1–10 as a reel shot. A calm, perfect landscape can score high on aesthetic and lower as a
    reel opener.
  - `technical` values are 0–1 unless named otherwise. `warmth` and `tint` are about −1 to 1.
- **Without an AI description,** `ai.version` is 0 and the descriptive fields are `null`; `tags` and `issues` are
  then empty. This is the case with `--no-ai` or no backend, and the shot still has `technical`, `faces` and `uses`.
- **Enumerations** (`scene`, `time_of_day`, `weather`, `issues`, `setting`, camera `motion`) are listed in
  `schema.json`.
- **`uses`** holds judgements for one app. Other apps can add their own keys there in their copy of the data.

## Using it from other apps

**Any language.** Read `media.jsonl` line by line; validate against `schema.json` if you like. For example, with
`jq`:

```bash
# sharp, good-looking photos from one day, best first
jq -c 'select(.kind=="photo" and .captured.day=="2025-07-12") | .shots[0] as $s
       | select($s.technical.sharpness_label=="sharp" and ($s.ai.aesthetic // 0) >= 7)
       | {path, caption: $s.ai.caption, aesthetic: $s.ai.aesthetic}' media.jsonl
```

**Python.**

```python
from tripshots import analysis

for rec in analysis.load("~/.tripshots/analysis/Trips-1a2b3c"):   # a folder or a media.jsonl
    shot = rec["shots"][0]
    print(rec["path"], shot["ai"]["caption"], shot["technical"]["sharpness_label"])

# or search the latest analysis
picks = analysis.query(text="lake sunrise", min_aesthetic=7, sharp_only=True, kind="photo")
```

**A collage maker (like SCRL)** usually needs:
- **Choosing photos:** `ai.aesthetic`, `technical.sharpness_label`, `ai.usable` and `ai.issues`. Keep one photo per
  `similar_group` so near-duplicates don't sit side by side.
- **Grouping:** `trip.id` and `captured.day` for a page per trip or day, and `location.place` for titles.
- **Cropping:** the `subjects` and `faces` boxes are the parts a crop must keep. `media.orientation` and `aspect`
  say which frame shapes a photo can fill.
- **Matching colours:** `palette` and `temperature_label`, for pages whose photos go together or a background that
  suits them.
- **Labels:** `ai.caption` for captions, `ai.landmark` and `ai.text` for labels.
- **People pages:** `people.names` and `faces[].name`.

**Agents.** Over MCP, `analyze_footage` runs the analysis as a background job and `search_media` searches it,
returning compact records, or full ones with `full=true`.

## Versions and re-running

- **The schema id** `tripshots.media/1` stays the same for additive changes (new optional fields). A breaking change
  bumps it to `/2`, and the change is described in the changelog.
- **Analyzer versions** (`analyzed.versions`): when an analyzer improves, its version goes up and the next run
  redoes just that part.
  - **AI descriptions:** shots described by an older prompt are asked again by `analyze`. Making a reel keeps using
    the stored ones.
  - **Shot detection, thumbnails and technical metrics:** recomputed locally, without AI calls.
- `--rescore` asks the AI again about every shot; `tripshots library --forget-ai` drops all stored AI verdicts.
