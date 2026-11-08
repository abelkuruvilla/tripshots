---
name: tripshots
description: Make Instagram Reels from the user's own travel photos and videos with TripShots. Use when the user asks for a reel or short video of a trip, a place, a date range or the people in their footage ("a reel about my days in Yellowstone", "a reel of the photos I'm in", "my Lisbon trip with mom").
---

# TripShots: reels from the user's own footage

TripShots edits the user's existing photos and clips into a beat-synced 9:16 reel. It never generates footage.
The user isn't an editor: make the creative calls (shots, order, style, hook), show the result, offer one tweak.

Two ways to drive it, same steps:
- **MCP tools** (if a `tripshots` MCP server is connected): `status`, `find_footage`, `make_reel`, `job_status`,
  `edit_plan`, `render_reel`, ... Images (contact sheets, storyboards) come back in the tool results: look at them.
- **CLI** (shell access): every command prints JSON. Open the image files it names to look at them.

## 1. Know what's there
- `tripshots footage` (MCP `status`): the folders searched by default. None set? Ask where the photos/videos live
  (SSD, phone export) and set them: `tripshots footage ~/Trips /Volumes/SSD/Footage` (MCP `set_footage_folders`).
- `tripshots trips` (MCP `list_trips`): trips with dates, places, counts, per-day places. Use it for "last summer",
  "the Iceland trip", or when a place name is ambiguous.

## Analysis without a reel
When the user wants their footage described, sorted, searched or prepared for another app: `tripshots analyze
[folders]` (MCP `analyze_footage`) writes `media.jsonl` (one `tripshots.media/1` record per file: captions, tags, subjects,
scene, people, place, trip, focus, colours, near-duplicates). Search it with MCP `search_media` or
`tripshots.analysis.query`. Format: docs/analysis.md.

## 2. Turn the request into a search
`tripshots find [--place NAME] [--people NAME...] [--since YYYY-MM-DD] [--until ...] [--kind photo|video] [--text WORDS] --sheet`
(MCP `find_footage`). It saves a selection and prints its id, `sel:xxxx`.

| request | search |
|---|---|
| "my days in Yellowstone" | `--place "Yellowstone National Park"` (same-day phone clips without GPS are added automatically) |
| "pictures I'm in" | `--people me --kind photo` |
| "Lisbon with mom" | `--place Lisbon --people me mom` (both in frame; `--any-people` for either) |
| "last July" | `--since 2025-07-01 --until 2025-07-31` (check the year against `trips`) |
| "the beach day" | `trips` → pick the day → `--since D --until D` |

- Be specific with places ("Yellowstone National Park", not "Yellowstone"): it matches GPS against the real outline,
  plus folder names. Check `notes` in the result: it says what the place resolved to.
- **People.** `tripshots people list` (MCP `people_list`). "me" not known yet? Ask for 2-5 photos where they are the
  largest face: `tripshots people add me <photos...>` (MCP `people_add`). Or `tripshots people discover` (MCP
  `people_discover`), show the face sheet and ask who is who, then `tripshots people name c2 me` / `... c3 mom`.
  Recognition runs on this computer; nothing is uploaded.
- Look at the contact sheet. Fewer than ~8 files makes a thin reel: widen dates or drop a filter, and say so.

## 3. Plan, look, fix
`tripshots make sel:xxxx -m <music> [-s style] [-d secs] [--hook "TEXT"] --dry-run` (MCP `make_reel`, dry_run true).
- Music: a file the user has (`list_music`), or an Instagram reel link (its sound is used). No music = silent, 100 BPM.
- Every reel is planned as a story (hook in the first second, build, payoff on the drop, looping end) and checked by
  a critic; `format` picks montage, pov, list (numbered places, needs 3+ places), series ("Day N of") or reveal (auto by
  default). After posting, record how it did with `reel_results` so later reels lean towards what works.
- Style: beat-montage (energetic), pov-hook (story/text), cinematic (emotional, golden hour), slow-scenic (calm nature),
  split-beat (split screens). Hook: 7 words max, specific ("Old Faithful at 6am", not "Amazing trip").
- Look at the storyboard: strongest image first, no near-duplicates side by side, nothing blurry or dark, a calm wide
  shot last. Fix with `edit_plan` (MCP) or by editing the plan JSON: swap a slot's shot (candidates: MCP
  `shot_candidates`, CLI `tripshots scan sel:xxxx --top 40`), move/exchange slots, set hook text, transitions, speed.
  For impact, a moving clip can get a speed ramp on a beat (`{"op":"ramp","segment":4,"ramp":"slam"}`;
  velocity, slam, bullet, rush, impact, surge) or a speed-up (`{"op":"speed","segment":6,"speed":2}`). Keep calm
  scenic shots at real time or slow motion.
  Slot timing stays on the beat.

## 4. Render and hand over
`tripshots render <plan.json>` (MCP `render_reel`, then poll `job_status`: a few minutes). Give the user the mp4 path,
the cover and the caption. If the music is a commercial song, make the reel with `--upload-copy` (MCP `make_reel` upload_copy=true; automatic for
reel links): they post the `.nomusic.mp4` and add the same sound inside Instagram.
Offer one concrete follow-up ("a 15 s version", "open on the waterfall").

## 5. Finishing in Instagram's Edits (optional)
When the user wants to finish or post in Edits, or wants Instagram's licensed song: `tripshots edits package <plan>`
(MCP `edits_package`). It renders the picture with grade, motion, transitions, maps and skyline titles baked in, and
writes clips per shot, texts, `sound-effects.wav`, the song and `manifest.json`. If Edits' own MCP tools are connected
too, read the manifest, check the Edits tools you actually have, and build: new 9:16 project; clips at their `start`
(or `picture.mp4` at 0); each text as Edits text at its start/duration; `sound-effects.wav` at 0; the song from Edits'
library at `music.song_start`. Use the `staged` copy (Edits only opens files in its sandbox). Check preview frames
against the storyboard. Don't export or post unless asked. Otherwise `tripshots edits push` (needs a confirmed mapping,
see docs/edits.md), or give the user README.txt to do it by hand.

Plain-language shortcut without an agent: `tripshots ask "a reel about my days in Yellowstone"`.
