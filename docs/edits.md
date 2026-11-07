# Finish in Instagram's Edits app

[Edits](https://www.instagram.com/edits/) is Instagram's video editor, and its Mac app has an automation
server that AI tools can drive. TripShots can hand a reel over to it, so you finish and post it in Edits.

The point is to keep TripShots' full edit and add what Edits does best:

| TripShots bakes into the picture | Stays editable in Edits |
|---|---|
| shot choice and order, cuts on the beat, colour grade, motion, beat punch, transitions, split screens, speed ramps, freeze-frame, colour split, in-camera whips, framing and tracking, route maps, titles behind the skyline | the hook, location, closing line and labels (as Edits text), the sound effects (their own track), the song (from Edits' library, so the post uses Instagram's licensed sound) |

Nothing is lost: everything Edits can't rebuild is already in the picture, and everything it can rebuild is left
for it.

## 1. Make the package

```bash
tripshots make ~/Trips/Yellowstone -m song.mp3 --dry-run     # or a sel:<id> search; check the storyboard
tripshots edits package reels/Yellowstone-beat-montage-<time>.plan.json
```

This renders the picture without the native text and without audio, and writes `NAME.edits/`:

| File | What |
|---|---|
| `picture.mp4` | The whole reel's picture, 1080×1920, 30 fps, no audio |
| `clips/NN-<shot>.mp4` | The same picture cut into one clip per shot, frame-exactly at the planned cuts. Laid end to end they play back like `picture.mp4`; transitions are split across the cut |
| `text/NN-<type>.png` | Each title as a transparent PNG in TripShots' own style, cropped, with its position in the frame |
| `sound-effects.wav` | Sound effects and ambience, timed to the edit (0:00 = start of the reel) |
| `music.m4a` | The song as used (trimmed, faded), as a fallback for Edits' library version |
| `manifest.json` | Everything above with its times: clips, texts (text, start, duration, animation, box), audio, music (title, where in the song the reel starts, tempo), the beats, the caption |
| `README.txt` | The same as a checklist, for building it by hand |

On a Mac with Edits installed, the package is also copied into Edits' sandbox
(`~/Library/Containers/com.burbn.basel.mac/Data/tmp/tripshots/`), because Edits can only open files there.
`--no-stage` skips that and `--no-clips` writes only `picture.mp4`. In the app, every planned or rendered reel has a
**Send to Edits** button.

## 2. Put it in Edits

There are three ways to get it onto an Edits timeline, from most hands-on to most automatic.

**By hand.** Open `README.txt`: new 9:16 project, `picture.mp4` (or the clips) at 0:00, each text at its time,
`sound-effects.wav` at 0:00, then the song from Edits' music library starting at the time it gives. The cuts are on
that song's beats.

**With an agent that's connected to both.** Add Edits' automation server to your agent next to TripShots (in
Edits: *Settings → Automation → Enable Automation Server*, then *Connect an AI client*). Then ask: *"Send my
Yellowstone reel to Edits."* The agent calls `edits_package`, reads `manifest.json`, looks at the Edits tools
it actually has, and builds the timeline. This is the most robust route, because the agent reads Edits' tool
descriptions live and adapts when Edits changes them. The [agent skill](../skills/tripshots/SKILL.md) has the steps.

**With `tripshots edits push`.** TripShots drives Edits' automation server itself:

```bash
export TRIPSHOTS_EDITS_TOKEN=<the token from Edits' Automation settings>
tripshots edits tools          # what this version of Edits offers -> ~/.tripshots/edits/tools.json
tripshots edits probe          # a draft mapping from TripShots' steps to those tools -> ~/.tripshots/edits/profile.json
# check the mapping (see below), set "confirmed": true
tripshots edits push reels/Yellowstone-beat-montage-<time>.edits
```

`push` creates a project, imports and places the clips (or `--picture` for one clip), adds each title
(as Edits text, or `--text-as image` for TripShots' PNGs), and adds the sound-effects track. The song is left to
add from Edits' library (`--music file` adds `music.m4a` instead, `--music none` skips it). It doesn't export or
post: you check it in Edits and post from there.

## The tool mapping

Meta doesn't document Edits' automation server, and its tools can change with any app update. So TripShots
doesn't ship tool names. `probe` reads the running app's tools and matches each of TripShots' steps (`new_project`,
`import`, `add_clip`, `add_text`, `add_audio`, `add_image`) to a tool by its name and description and by the
arguments it takes (a file path, a media id, a start time, a duration, text). The draft looks like this:

```json
{
  "confirmed": false,
  "steps": {
    "import":   {"tool": "importMedia", "args": {"path": "{file}"}, "save": {"media_id": "id"}, "time_unit": "s"},
    "add_clip": {"tool": "addClipToTimeline", "args": {"mediaId": "{media_id}", "startTime": "{start}", "duration": "{duration}"},
                 "time_unit": "s", "other_params": ["track"]}
  }
}
```

Before confirming it, check against `tools.json`:

- **`tool`**: the right tool for the step.
- **`args`**: which of its arguments gets which value. The values you can use are `{file}`, `{media_id}`,
  `{start}`, `{duration}`, `{text}` and `{project_id}`.
- **`time_unit`**: how the tool measures time: `s`, `ms` or `frames` (30 fps).
- **`save`**: where to find the new id in the tool's reply (a dotted path such as `id` or `media.id`).
- **`fixed`**: any other arguments the tool requires, with fixed values (for example `{"track": 0}`).

Then set `"confirmed": true`. `push` refuses to run an unconfirmed mapping. After an Edits update, run `probe`
again; if a mapping already exists, it writes `profile.draft.json` next to it so you can compare.

## Limits

- **Mac only, and Edits must be open, signed in, with the automation server on.** The connection is
  local (`http://127.0.0.1:19501/mcp` by default; `TRIPSHOTS_EDITS_URL` to change it).
- **Untested against the real app.** TripShots' side was tested against a stand-in server with made-up tool names
  (`tests/fake_edits.py`). Whether Edits has tools for placing clips at exact times, adding music from its library
  and so on depends on the version you have; `edits tools` shows it.
- **Text in Edits is Edits' style.** Placed as Edits text, titles use Edits' fonts and animations, not TripShots'.
  Use `--text-as image` (or the PNGs) to keep TripShots' look; then it isn't editable as text.
- **Posting** and trial reels aren't available through Edits' automation (as far as the community has found), so you
  post from the app.
