# Reels that hold viewers

A reel isn't a slideshow. Viewers decide in about a second and a half whether to stay, stay for a question they
want answered, and send a reel to friends when it gives them a moment, a feeling or something useful. So TripShots
plans every reel as a little story and checks it like an editor before it renders.

The research behind this (Instagram's ranking signals, hook timing, an eye-tracking study on scene cuts, what
travel creators do) is summarised in the design doc *TripShots: making reels that stop the scroll*.

## The arc

| Part | What it does | How it's cut |
|---|---|---|
| **Hook** | The most striking moment first (a flash-forward of the payoff), or a tease in the `reveal` format. A short line of text is on screen from the third frame, all words in by half a second. | One shot, about 1–2 s. It starts slightly pushed in and settles within 0.45 s, so something moves at once |
| **Setup** | Where we are: an establishing shot, you arriving | A medium pace |
| **Build** | Shots get shorter and shorter into the drop | 2, 2, 1, 1, 1, ½, ½ beats |
| **Peak** | The payoff on the song's drop (or the dialogue's punchline): the best shot | Held 4–8 beats (at least 2 s); slow motion when the clip was shot at 50 fps or more |
| **Release** | The energy after the drop | Varied lengths: quick runs into a held shot |
| **Ending** | A held closer that looks like the opening, so the reel loops | At least ~2 s |

The log shows the plan, for example `story: hook 1.5s · setup 2 (1.0-2.0s) · build 3 (0.5-1.0s) · peak 2.0s ·
release 4 (0.5-2.0s) · ending 2.0s`, and every segment in the plan carries its `role`.

**Who goes where.** The hook, the peak and the ending are cast first, from the whole selection: the hook wants a
striking, moving shot; the peak the best shot (dynamic, people, a slow-motion-capable clip); the ending a calm
closer whose colours match the opening. Shots with you in them are weighted up for all three (`people_first`),
and when the hook isn't you, a good shot of you goes into the first three seconds. One shot per moment: bursts and
the photo and clip of one view count once.

**Turn it off** with `make --arc off` (the older even cut grid) or `story: {arc: off}` in a style.

## Formats

`make --format auto|montage|pov|list|series|reveal` (default `auto`):

| Format | Opening line | What changes |
|---|---|---|
| `montage` | A curiosity gap or a feeling ("I almost skipped this stop") | The arc as above |
| `pov` | "POV: …", held over the opening | Chosen automatically for dialogue and voice-over sounds |
| `list` | "3 stops in Utah you can't skip" | Shots grouped by place, a numbered card per place ("1 · Horseshoe Bend"), the best place last. Needs footage from at least 3 places (from GPS). Built for sends and saves |
| `series` | "Day 4 of our West Coast road trip" | The day number comes from your capture dates; a recognisable stem for a run of reels |
| `reveal` | A tease ("Wait for the last one") | Opens on something intriguing, not the best shot; the best shot is held back for the payoff |

`auto` picks `pov` for dialogue, `list` when the footage covers 3+ places, else `montage`; once your results show a
clear winner (below), it leans towards that.

## Hooks and text

The AI writes three opening lines for the format, scores each for clarity, curiosity and emotion, and a quick
rule check (short, concrete, no clichés) adds its view; the best one is used and the others are listed in the
log and in `plan.json` (`story.hooks`). Text sizes have floors so they read on a phone (hook 88 px, labels 64,
captions 54 at 1080 wide), and busy backgrounds get a soft shade behind the words.

## Sound with words

When `GEMINI_API_KEY` is set, Gemini listens to the sound and returns every line with its timing, an English
translation and the punchline (cached per file; [optional offline transcription](#offline-transcription)). Then:

- **Dialogue** (a film scene, a voice-over): one shot per line, cut in the pause after it; the payoff shot lands
  on the punchline; English subtitles appear when the dialogue isn't English (`--captions original|english|off`).
- **Songs**: the beat rhythm stays, and the payoff lands on the hook line when it sits mid-reel. No lyrics on
  screen unless you ask (`--captions original`).

The hook line is written to set up the words, so the picture answers them.

### Offline transcription

With `pip install faster-whisper`, sounds are transcribed locally when Gemini isn't set up (no punchline then).

## Movement

- **Match cuts.** The camera's movement in each clip is measured; neighbouring middle shots are reordered so the
  movement continues across the cut, whip transitions swipe the way the camera was going, and a soft dissolve
  between two shots moving the same way becomes a clean cut. Segments carry `flow` and `match: "motion"`.
- **Photos in depth.** Photos get a 2.5D parallax: a depth map (Depth Anything V2 Small, about 27 MB, downloaded
  once to `~/.tripshots/models`; or an estimate from the picture when it can't be downloaded) lets the foreground
  slide against the background. Flat pictures keep the plain zoom. `--parallax off` to turn it off.

## The critic

Before rendering, every plan is checked like an editor would (`NAME.critic.json`, and a line in the log):

| Check | Weight |
|---|---|
| Something moves in the first 0.5 s | 15 |
| A hook line of 7 words or fewer, on screen by 0.2 s | 15 |
| Shot lengths vary (longest ≥ 2.5× shortest, no long run of equal lengths) | 15 |
| A person within the first 3 s, when the footage has one | 10 |
| A held payoff after the middle | 10 |
| No moment twice, no clip twice in a row | 10 |
| At most half the shots static | 10 |
| The ending loops (or closes with a line) | 15 |

It fixes what it can (the hook punch, the hook's timing, a shot of you moved early, repeats swapped apart, the
loop). With an AI backend it also looks at the storyboard and may apply up to three swaps or a better hook line.
`--critic rules` skips the AI review, `--critic off` skips it all.

## Variants test ideas

`make --variants 3`: the second variant changes the format (a montage becomes a reveal, a list a montage), the
third opens on a different shot with a different hook; each result names its idea. Post them as Trial reels to see
which holds non-followers.

## Learning from your results

```bash
tripshots results add reels/West-Coast-….mp4 --views 1200 --avg-watch 6.1 --sends 14 --saves 9
tripshots results            # every reel, its score, and what's working so far
tripshots results sync       # read them from Instagram instead (see below)
```

A reel's score is 60 % watch-through (average watch time / length) and 40 % sends per view (2 % = full marks).
Scores are grouped by format and hook type, pulled towards your average so one lucky reel doesn't decide. Once
there are at least 5 scored reels and 2 for the leading format, `--format auto` leans towards it. Stored in
`~/.tripshots/results.json`. Agents: the `reel_results` MCP tool.

**From Instagram directly** (a professional account): create a Graph API access token with
`instagram_basic` and `instagram_manage_insights`, then set `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_USER_ID`.
`results sync` reads your recent reels' insights (views, reach, shares, saves, likes, comments, average watch time)
and matches them to the reels TripShots made by their caption.

---
[Docs home](README.md)
