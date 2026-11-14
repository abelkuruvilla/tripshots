# plan.json reference

Every reel is described by a plan: `NAME.plan.json` next to the video. `make --dry-run` writes the plan without
rendering. Edit it (by hand, with `edit_plan` over MCP, or with Claude Code), then `tripshots render NAME.plan.json`.
Only segments whose content changed are re-rendered.

## Top level

| Key | Meaning |
|---|---|
| `version`, `style` | Plan format version and the style it was made with |
| `duration`, `tempo`, `beats`, `drops` | Length (s), BPM, beat times and drop times (s, reel time) |
| `music` | `{path, start, fade_out}`: the track, where in it the reel starts, fade at the end |
| `segments` | The shots, in order (below) |
| `overlays` | Text and maps (below) |
| `motion` | `beat_punch` (zoom bump per beat, e.g. 0.06), `punch_on` (energy levels), `shake_on_drop` (allows segment `shake: true` on fitting drops), `video_push`, `pulse` |
| `grade` | `{look, strength, why, grain, vignette}`; per-shot LUTs live on the segments |
| `color`, `text`, `photo_zoom`, `transition_duration` | Copied from the style at plan time |
| `freeze` | `{t, dur}`: hero freeze-frame on a drop. Delete to turn off |
| `loop` | `true`: the end dissolves into the first frame |
| `frame` | `{aspect, ar, canvas: [w, h], band}`: only on a wide reel. `canvas` `[1920, 1080]` = a horizontal file the picture fills; `[1080, 1920]` with `band` (px) = an upright file with the picture in a band. Change it with `make --orientation`, not by hand: shots are framed for it |
| `recipe` | `{id, source, structure, hold, frame, text, lens, own_sound, why}`: the reference recipe this reel follows (learned styles). For reading; the segments and overlays already carry it |
| `sound` | `{sfx, ambience, native, level_db, licenses}`; effects follow the edit on every render |
| `work` | The analysis cache folder (`shots_scored.json` lists every candidate shot) |

## Segments

Segments tile the timeline: each starts where the previous ends. `render` recomputes `out_start` from the `dur`s.
Keep durations whole frames (multiples of 1/30 s) and on the beat: swap shots, or merge two neighbours, rather than
changing lengths.

| Key | Meaning |
|---|---|
| `shot_id` | Which shot (ids from `tripshots scan` or `shots_scored.json`). Change it to swap the shot |
| `kind`, `src` | `video` / `photo` and the source file |
| `dur`, `out_start` | Length and start in the reel (s) |
| `in`, `speed` | Video: start time in the source (s) and speed (0.5 = slow motion, 2 = twice as fast; 0.2–4) |
| `ramp`, `ramp_hit` | Speed ramp instead of a constant speed: `velocity`, `slam`, `bullet`, `rush`, `impact`, `surge` ([Speed](look-and-motion.md#speed)); `ramp_hit` = seconds into the segment where it slams into slow motion (a beat) |
| `ramp_points` | A custom curve with `"ramp": "custom"`: `[[0, 1], [0.4, 0.3], [1, 1.5]]` = (fraction of the segment, speed), eased between points |
| `smooth` | Slow motion from clips under 50 fps: `flow` (default), `blend`, `off` |
| `layout` | `crop` (landscape cropped at `subject_x`), `pan` (pan across a wide frame), `fill` (already vertical), `blur_fill` (whole frame over a blurred copy; only when the style asks for it), `kenburns` (photos), `popout` (photo in a frame, subject steps out) |
| `wide` | `true` on a landscape shot too wide to crop upright (it pans instead); a reel made mostly of these is made horizontal |
| `subject`, `subject_x` | Subject box `{x0, y0, x1, y1, cx, cy}` in 0..1 source coordinates; crop centre (0 = left, 1 = right) |
| `pan_from`, `pan_to`, `pan_reverse` | Pan range across the source (0..1) and direction |
| `track` | `true`: the crop follows a moving subject |
| `kb` | Photos: `in`, `out`, `left`, `right`, `up`, `down`, `in_rot` |
| `trans_out` | Transition into the next segment: `null` (hard cut on the beat), `whip`, `zoom_in`, `zoom_out`, `spin`, `flash`, `glitch`, `blur`, `dissolve`, `dip` |
| `trans_dur`, `trans_params` | Transition length (s, centred on the cut); `whip: {"direction": "left\|right\|up\|down"}`, `spin: {"clockwise": true}` |
| `incam_out`, `incam_in` | In-camera whip: the cut sits inside the camera's own swing (`trans_out` is `null`). Delete `incam_out` and set `trans_out` to drop it |
| `rgb` | `true`: colour-split glitch on the first frames |
| `lut`, `grade_note` | This shot's colour LUT (`.cube`) and what the colourist saw. To regrade, re-run `make --look X --dry-run` instead of editing these |
| `level` | Song energy here: `calm`, `medium`, `intense` |
| `role`, `hold` | The slot's place in the story (`hook`, `setup`, `build`, `peak`, `release`, `ending`); `hold: true` marks a long opening shot that must stay one continuous clip. Both stay with the slot when its shot is swapped |
| `clone_of` | Clone plans: the reference shot this slot copies. Keep `dur`, only swap `shot_id` |

**Split-screen segments** have `panel` (`split2`, `split3`, `grid4`, `columns3`), `pmode` (`reveal` or `cycle`) and
`clips`: a list of `{rect, t0, t1, intro, <shot fields>}` with times relative to the segment.

## Overlays

| Type | Fields |
|---|---|
| `hook` | `text`, `start`, `duration`. Keep it to 7 words or fewer |
| `location` | `text`, `start`, `duration`, optional `gps` [lat, lon] (adds a coordinates line), or explicit `main` / `sub` / `coords` |
| `cta` | A closing line: `text`, `start`, `duration` |
| `label` | A short label on one shot: `text`, `start`, `duration`; optional `lead` (a small line above it, e.g. "Greetings from...") and `shots` (the shot ids it names; a recipe's labels are rewritten when those shots change) |
| `caption` | A subtitle or lyric line: `text`, `start`, `duration` |
| `map` | Route map: `mode` (`intro` / `tracker`), `start`, `duration`, `x`, `y`, `theme`, `title`, `stops` [`{name, region, ll}`], `beats` (intro), `keys` (tracker). Rebuilt from these fields at render time, so renaming a stop just works |

Any text overlay may carry its own `style`: `font`, `size`, `uppercase`, `anim` (`cut` = appears on the frame), `position`
(`upper`, `center`, `lower`), `color` [r, g, b] or `colors` [[r, g, b], ...] (one per letter, repeating), `line_gap`,
`exit`, `legible`, `fit` (share of the frame's width a short word grows to), `fixed` (keep the place on every shot),
`lead_font` / `lead_size` (the small line above a label), `y` (the middle of the line, 0 to 1 down the frame, instead
of the middle of its third: a line held across shots gets one when that keeps it off somebody's head). Recipes use it so the words look like the reference's
(overlay `recipe`: `lyric`, `tease`, `payoff`, `title`, `label`); edit it to restyle one line.

The text style comes from `text.preset` (`bold`, `editorial`, `minimal`, `handwritten`, `typewriter`);
`text.hook.position` can be `auto`, `upper`, `center`, `lower`. With `text.location.behind` on, the location title is
drawn behind the skyline; such an overlay should start at a segment start and end within that segment.
