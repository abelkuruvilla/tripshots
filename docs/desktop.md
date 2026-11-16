# The desktop app

TripShots for macOS, Windows and Linux: your reels in a gallery, a player with the caption and the sound to add,
a timeline where you swap any shot, new reels from folders and a reel link, Ask, learning styles, and settings.
The app itself is small (a system web view, no bundled browser); the engine that analyses footage and renders
reels is downloaded once on first launch and updates on its own.

## Install

Download the installer for your computer from the latest release:

| | File |
|---|---|
| Mac (Apple Silicon) | `TripShots_<version>_aarch64.dmg` |
| Windows | `TripShots_<version>_x64-setup.exe` or `.msi` |
| Linux | `.deb`, `.rpm` or `.AppImage` |

Intel Macs aren't supported: libraries the engine needs (numba, onnxruntime) no longer ship for them.

On first launch, **Download the engine** fetches it (about 200 MB; it is checked against TripShots' signature before
it's used). On a Mac, install ffmpeg once with `brew install ffmpeg`; the Windows and Linux engines include it.

## What's where

- **Reels**: every reel in your reels folder and `~/.tripshots/reels`, newest first. Pinned reels come first,
  then collections, then folders. Show all, upright, wide, plans not rendered yet, reels edited since their render,
  favourites, or one collection. Each reel's **⋯** menu can:
  - pin it or make it a favourite;
  - put it in a collection (a trip, a series);
  - rename it (every file of the reel moves with it, its undo history too);
  - duplicate its plan to try something else;
  - move it to the Trash.

  `tripshots reels` and MCP `manage_reel` do the same.
- **Make** (⌘2): **From a trip** lists your trips; pick one, then one reel per day or per place
  (`tripshots split-trip`), filed in the trip's collection. **Describe it** ("a reel with all my drone footage"): TripShots finds the footage, picks one of your
  styles and a sound, and makes it; or **Choose it yourself**: footage, sound (a reel link, so its cut and sound
  are used, or an audio file), style, shape, up to four versions, an opening line. **Plan first** gives the
  storyboard in about a minute. The job shows here step by step (reading the request, finding footage, choosing
  shots, planning, rendering, sound and checks), with what it understood and found, any question it asks, and
  **Open the reel** at the end.
- **A reel** is an editor on one screen: the viewer, an inspector with tabs, and the timeline along the bottom.
  Click a shot to jump to it; the swap button on a shot replaces it with one of the best shots of the same footage
  without moving the cuts. **Render the changes** makes the new version. Every change can be undone (⌘Z / Ctrl+Z,
  ⇧⌘Z to redo), and removing something offers Undo right away.
  - **Your edit / Last render**: *Your edit* shows a still of the reel at the playhead as it stands now, with its
    words and colour as the render will make them (motion and transitions left out), so changes show at once.
  - **Text**: every line of text. Select one to change its words, when it starts and how long it stays, its
    font (the bundled faces and about a hundred open fonts, each shown in its own face), size, colour, where it
    sits (top, middle, bottom, or click the picture where it should go), how it comes in (pop, slide, fade, grow,
    typewriter, spread, rise, cut), capitals, see-through letters and a small line above it. **Add text** puts a
    new line at the playhead; ⌫ removes the selected one. On the timeline, drag a line to move it or its right
    edge to change how long it stays.
  - **Colour**: the reel's look, each one shown on the shot itself (the built-in looks and the ones you made with
    `tripshots look` or learned from reels, or None), its strength, grain and a vignette; and for the selected
    shot, or the one at the playhead, its own corrections on top of the look: exposure, contrast, saturation,
    warmth, tint, shadows, highlights (double-click a slider to reset it), whether it takes the look at all, and
    **Use on every shot**. The look strip filters built-in looks, yours and each LUT pack; **More looks** adds your
    own LUT files (`.cube`, HaldCLUT images, zips) or fetches a free pack. **Hold to compare** (or hold Space on it) shows the shot as filmed; **Before and after**
    splits the viewer between the shot as filmed and your edit, with a divider to drag (or move with ← →).
  - Under the viewer, **Your edit** shows a still of the edit at the playhead, **Preview** plays the edits in
    motion (a quick render, `tripshots render --draft`: no sound effects, text without its animation; its clips
    are the ones the real render reuses), and **Last render** plays the finished reel.
  - **Notes**: watch the reel, and where something is off press **N** (or **Note** under the viewer): it pauses
    and you say what you see ("too dark", "swap this for the canyon", "the words cover her face"). Each note is
    pinned to that moment (a dot on the timeline, a still in the list) and kept until you **Send** them all at
    once: the reel is edited to match (`tripshots revise`) and rendered again, and the tab then says what was done
    for each note.
  - **Post**: what to upload and which sound to add, then the caption, with the length of its first line (about
    125 characters show before "more"). **Write it for reach** writes the post (`tripshots caption`): a hook
    first line that names the place, search keywords worked into the words (Instagram search reads captions),
    one ask that brings sends or saves, 3 to 5 specific hashtags (Instagram's limit is 5), alt text, a first
    comment to pin and two other opening lines to pick from. **Voice** sets the tone ("funny and short").
  - **Expert** (the switch in the header) adds the **Shot** and **Sound** tabs and timeline editing: zoom, the
    beats on the ruler, drag a shot to another place, drag its right edge to change its length (it snaps to the
    beat; hold Alt for single frames) or its left edge to trim its start (the end of the clip stays where it
    was). **Shot**: move it earlier or later, split at the playhead (S), hold the frame at the playhead for a
    second (F, a freeze frame), play the clip backwards (R), **On top** (another shot in a corner from the playhead: a
    picture in picture with its own lane on the timeline, where you drag it or its end; select it to place it in a
    corner or anywhere, size it and set its length), **Zoom and position** (set zoom and where the picture sits, then
    **Keyframe here**; the picture moves smoothly between keyframes, e.g. a slow push in onto a face), repeat,
    replace, add a shot after it, remove it, its length, which part of the clip plays, speed and speed ramps, the
    transition into the next shot and an effect on the shot (pickers that draw each one on your own shots, filtered
    by energy; with no shot selected, **Choose effects with AI**: see [the effects library](effects.md)), framing (crop, pan, whole frame). **Sound**: where the song starts, the music
    level, its fade out and the beat punch. Space plays, ← → step a frame (⇧ a second). Later text moves with the
    cuts; subtitles and lyrics stay with the song.
- **Styles** (⌘3): yours, then the built-in ones, each with **Make a reel**. **Learn a style** takes reel links
  (each becomes a recipe); **Add examples** grows one of yours.
- **Activity** (⌘4): everything being made, rendered or learned, with its state in words, its steps and its log. Jobs started from the command line or by
  an AI agent show up here too, and reels they make appear in the gallery.
- **Settings > AI**: which AI makes the creative calls (Automatic, Claude, MiniMax, Claude API, None) and, for
  each one, the steps to set it up with links and a **Test** button: Claude Code is installed and logged in from a
  Terminal window the app opens (`claude auth login`, your Pro/Max plan, no key), MiniMax and the Claude API take a
  key from their sites, and Gemini (optional, a free key from Google AI Studio) watches clips. The gallery says so
  when no AI is set up.
- **Settings**: footage, reels and music folders; the browser to borrow your Instagram login from;
  **Command line** (puts `tripshots` on your PATH) and **Claude** (adds TripShots to Claude Desktop's MCP servers
  and gives the `claude mcp add` line for Claude Code); app and engine updates.

## The command line and agents

The app's engine is the full `tripshots` program. After Settings > Command line > Install, every command in
[Commands](cli.md) works in a terminal, and `tripshots mcp` serves the [MCP tools](mcp-tools.md). The app, the
command line and agents share `~/.tripshots` (library, styles, memory of earlier reels).

## For developers

Building, the engine API, releases and signing: [desktop/README.md](../desktop/README.md).
