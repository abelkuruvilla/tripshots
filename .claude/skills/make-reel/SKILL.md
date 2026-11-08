---
name: make-reel
description: Make, review and refine an Instagram Reel from the user's travel footage with the TripShots CLI. Use when the user asks to make a reel or video from a trip folder, change one, or learn a style from reels they like.
---

# Make a reel with TripShots

The user isn't an editor and has said creativity isn't their strength. Make the choices yourself, then show them the result.

## 1. Gather inputs (ask only for what's missing)
- Footage: a folder, or a *search* when the request names a place, dates or people ("my days in Yellowstone",
  "the photos I'm in"): `tripshots find --place "Yellowstone National Park" --sheet` / `tripshots find --people me --kind photo --sheet`,
  look at the sheet, then use `sel:<id>` in place of folders. People need enrolling once (`tripshots people add me <photos>`
  or `people discover` + `people name c2 me`). Full mapping of requests to searches: `skills/tripshots/SKILL.md`.
- Footage folder(s): SSD path and/or phone export folder (`tripshots footage` remembers them).
- Music file. If there's none, suggest one at a similar tempo to a trending sound they like (see README, "Music and trending audio"). Without music the reel is silent at 100 BPM.
- Style. If they point at reels they like, run `tripshots learn <urls> -n <short-name> --cookies-from-browser chrome` first. Otherwise choose:
  - beat-montage: energetic music, many clips
  - pov-hook: they want text or a story hook
  - cinematic: slow or emotional music, golden-hour footage
  - slow-scenic: calm nature, few long clips
- Colour: if they show reels whose *colour* they like, run `tripshots look <urls> -n <name> --cookies-from-browser chrome` and pass `--look <name>`. Otherwise leave `auto` (the AI picks), or choose: golden-hour (warm sunsets, beaches), teal-orange (cinematic, cities, deserts), vivid (tropical, blue water), moody/nordic (mountains, fog, rain), warm-film / faded-matte (nostalgic, soft).

- Camera footage: Insta360/GoPro MAX raw files (.insv, 2:1 360 exports) are skipped. If the log says so, tell them to reframe in Insta360 Studio (Auto Frame) and add the flat exports. If `GEMINI_API_KEY` is set, Gemini watches each clip once (best moment, shake, tilt, whip pans); `tripshots doctor` shows whether it's on.

- If they point at ONE reel and say "like this" / "make this with my footage", use `tripshots clone <url> <folders> --dry-run`, look at `NAME.clone.jpg`, fix weak matches by swapping `shot_id` (keep `dur`), then `render`. Offer `--variants 3` when they want options to test.

## 2. Plan
```bash
tripshots make <folders> -m <song> -s <style> --dry-run -o reels/<name>.mp4
```
Read `reels/<name>.storyboard.jpg` and `reels/<name>.grade.jpg`. Check:
- The grade: skies blue (not purple/grey), blacks not lifted to mud, sunsets still warm, shots match each other. If too strong or the wrong mood, re-run the dry run with `--grade-strength 0.5` or another `--look`.
- Shot #1 is the most striking image (the hook decides whether people keep watching).
- No two near-identical shots back to back; nothing blurry, dark or tilted.
- The last shot is a calm, wide "ending" shot.
- Vertical crops keep the subject in frame. If not, adjust `subject_x` in the plan, or use `"layout": "blur_fill"`.

To swap shots, run `tripshots scan <folders> --top 40` to see the candidates, then edit `shot_id` in `reels/<name>.plan.json`.

## 3. Render and check
```bash
tripshots render reels/<name>.plan.json
for t in 0.5 1.5 3 6; do ffmpeg -loglevel error -y -ss $t -i reels/<name>.mp4 -frames:v 1 -vf scale=360:-2 /tmp/f_$t.jpg; done
```
Look at the frames. Is the text readable and not cut off, and is the colour natural (not grey or washed out)?

If the log says "speed: N ramp(s)", pull a frame at each ramp's hit (`out_start + ramp_hit`): it should be in slow motion on the beat, with no smeared or doubled edges.

If the log says "in-camera whip transition(s)", pull frames around that cut: it should land inside the blur of the swing, not on a sharp frame.

Also look at `reels/<name>.sound.jpg` (amber bars = the clip's own sound used as ambience): effects should sit on cuts/drops/text pops (not on every cut), the impact on the drop should be the loudest event, and the log line "sound: ... master -14 LUFS" should be near -14. If the log says effects are synthesized stand-ins, run `tripshots sounds --fetch` once.

## 4. Deliver
Give the mp4 path, the cover image, and the caption from `.caption.txt`. Remind them: if the song is commercial, mute it in Instagram and add the same or a trending sound from Instagram's library.
If they want to finish it in DaVinci Resolve or Premiere, point them at `reels/<name>.edl` (written automatically) or run `tripshots export reels/<name>.plan.json` for OTIO too.
Offer one or two concrete follow-ups, e.g. "make a 20s cinematic version" or "swap the opening for the waterfall".
