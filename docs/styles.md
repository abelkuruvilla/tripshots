# Styles

A style is a YAML file that sets the pace, transitions, motion, text, colour and sound of a reel. Built-in styles
are in `tripshots/styles/`; your own go in `~/.tripshots/styles/<name>.yaml` and can be used with `-s <name>`.
`tripshots styles` lists them.

Ways to get a new style:

- `tripshots learn <reel links or videos> -n my-style` measures reels you like (cut rhythm, beat sync, colour, text) — see [Making reels](making-reels.md#learn-a-style-from-reels-you-like).
- The app's **Styles** tab: **Edit…** saves your changes as your own copy.
- Copy a built-in file to `~/.tripshots/styles/` and edit it. A style only needs the keys it changes; everything else comes from the defaults below.

## Keys

| Key | Default | Meaning |
|---|---|---|
| `name`, `description` | | Shown in `tripshots styles` and the app |
| `duration.target` / `min` / `max` | 15 / 10 / 25 | Reel length in seconds (`-d` overrides `target`) |
| `music.window` | `auto` | Which part of the song: `auto` picks the most energetic window |
| `music.fade_out` | 0.8 | Fade at the end (s) |
| `cuts.beats_per_cut` | calm 4, medium 2, intense 2 | Beats per shot by song energy |
| `cuts.hook_beats` | 2 | Length of the opening shot in beats |
| `cuts.min_shot_sec` / `max_shot_sec` | 0.6 / 3.5 | Shot length limits |
| `cuts.energy_thresholds` | [0.35, 0.7] | Where calm / medium / intense start |
| `shots.min_score` | 6 | Lowest AI score (1–10) normally used |
| `shots.ordering` | `energy` | `energy` (strong shots on strong beats), `chronological`, `score` |
| `shots.max_per_source` | 3 | Most shots from one clip |
| `shots.slowmo` | true | Play 48 fps+ footage at half speed in calm parts |
| `layout.landscape` | `auto` | `auto`, `crop`, `pan`, `blur_fill` for landscape footage |
| `layout.photo_motion` / `photo_zoom` | `kenburns` / 1.12 | Photo movement and zoom |
| `transitions.palette` | per energy level | Which transitions may be used when |
| `transitions.density` | 0.5 | Share of ordinary cuts with a transition (0 = all hard cuts) |
| `transitions.speed` | 1.0 | <1 snappier, >1 slower |
| `transitions.at` | `sections` | Always put one at energy changes and drops |
| `transitions.in_camera` | true | Cut inside your own whip pans ([Look and motion](look-and-motion.md#in-camera-transitions)) |
| `motion.beat_punch` / `punch_on` | 0.05 / [intense] | Zoom bump per beat, and at which energy levels |
| `motion.shake_on_drop` / `shake_px` | true / 22 | Allow a camera shake on drops in intense sections (never in mostly calm reels, slow motion or a freeze) |
| `motion.video_push` | 0.06 | Slow push-in on static clips |
| `motion.freeze` / `rgb_split` | false / 0 | Freeze-frame on the biggest drop; share of hard cuts with a colour split |
| `motion.pulse` | | Bulge on intense beats (e.g. 0.1) |
| `grade.look` / `strength` / `ai` | `auto` / 0.75 / true | Colour look (`auto`, `none`, a preset, or your look), strength, AI colourist |
| `color.*` | | Used when `grade.look` is `none`: `saturation`, `contrast`, `brightness`, `gamma`, `warmth`, `vignette`, `sharpen`, `lut` (your own `.cube`) |
| `text.preset` | `bold` | `bold`, `editorial`, `minimal`, `handwritten`, `typewriter` |
| `text.font` | | Your own font file for everything |
| `text.hook` | mode `off` | `mode` (`off`, `ai`, `text`), `text`, `start`, `duration`, `position`, `font` |
| `text.location` | mode `first` | `mode` (`off`, `first`, `each`), `position`, `duration`, `coords`, `behind` (`auto`, `on`, `off`), `behind_font` |
| `text.cta` | mode `off` | Closing line: `mode` (`off`, `ai`, `text`), `text`, `duration` |
| `text.labels` | mode `off` | `ai`: a short label on each shot; `max` |
| `panels.use` / `kinds` / `mode` / `max` | 0 / all / `mixed` / 2 | Split screens: share of segments, which layouts, `reveal`/`cycle`/`mixed`, most per reel |
| `velocity.use` | 0 | Share of moving clips with a speed ramp ([Speed](look-and-motion.md#speed)) |
| `speed.ramps` | [velocity] | Which ramps: `velocity`, `slam`, `bullet`, `rush`, `surge` |
| `speed.fast` / `fast_max` | 0 / 2.5 | Share of moving clips sped up in busy sections, and the fastest speed |
| `speed.drop` | `off` | At the biggest drop: `rush`, `impact`, `both`, `off` |
| `speed.smooth` | `flow` | Slow motion from clips under 50 fps: `flow` (optical flow), `blend`, `off` |
| `loop` | false | Seamless loop |
| `popout.use` / `bg` / `variant` | 0 / `paper` / `auto` | Share of photos shown as pop-out frames |
| `route_map.mode` / `theme` / `title` / `max_stops` | `off` / `auto` / "" / 7 | Animated route map |
| `sound.sfx` / `ambience` / `native` | `on` / `on` / `auto` | Sound effects, ambience beds, the clip's own sound |
| `sound.level_db` / `licenses` | 0 / `cc0,pdm` | Effects level; which Openverse licences are allowed (`cc0,pdm,by` adds credited CC BY) |
| `caption.tone` / `hashtags` | | How the AI writes the caption, and how many hashtags |

The authoritative list, with comments, is `DEFAULT_STYLE` in [`tripshots/config.py`](../tripshots/config.py).
