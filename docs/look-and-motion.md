# Look and motion

Everything that moves on screen: transitions, beat-synced motion, text, framing, maps and effects. Each is on or off per style ([Styles](styles.md)) and stored per segment in the plan ([plan.json](plan-format.md)).

## Transitions and motion

Every reel is composited frame by frame, so movement is tied to the music:

* **Transitions at the cut:** `whip` (fast swipe with motion blur), `zoom_in`/`zoom_out` (punch through with radial blur), `spin`, `flash`, `glitch` (RGB split), `blur`, `dissolve`, `dip` and `leak` (warm film light washing across the frame while the shots dissolve under it; used between calm shots). Each is centred on the beat. Which ones are used depends on the song's energy at that moment. Energy changes and drops always get one. Other cuts get one at the style's `density`; the rest are hard cuts on the beat, which is what keeps it punchy.
* **Masked reveals, keyframed on the beat:** the next shot comes in through a shape, the way CapCut masking tutorials teach. `split`: a line swings round a corner of the frame, 45° on each beat (the four corners in turn). `vsplit`: a V opens from the middle of the bottom (or top) edge. Both snap on every beat inside the transition and hold in between, with a thin white edge along the mask. `iris`: a circle grows from the middle to the whole frame with a soft rim, a ripple running round it and a glow as it opens. They last whole beats (`transitions.beats`, default 2; `trans_params.steps` = the beats), and a reveal may take its shots whole, so one runs into the next. The `mask-reveal` style puts one on every cut: line reveals, then V reveals, then circles (`transitions.order`).
* **Paper shapes:** the next shot is built from pieces, each a plain cream block first and then the picture through it, with thin seams while it builds: `slats` (upright slats, left to right), `stripes` (stripes down the frame), `diamond` (a diamond from the middle, then the four corners round it). `frame`: the next shot as a window in the middle first, then panels round it (left, bottom, top, right); thin gaps between them keep showing the old shot like lines framing the window, until it snaps into the whole picture. With `motion.colour_in` (seconds) every shot arrives in black and white and its colour blooms in (segment `colour_in`). With `motion.silhouette`, the people in a shot (an upright figure the cut-out finds) flash paper-white for two frames as it lands (segment `silhouette`). The widescreen `shape-cut` style uses all of these.
* **Travel transitions:** `polaroid`: the next shot drops in as a print with a white border (deeper at the bottom), lands at a slight angle with a shadow, then opens out until its picture is the whole frame. `mirror`: the next shot opens out from the horizon line as its own reflection, a still lake below the line with a slight ripple, and the reflection settles into the real picture; best between wide views with water or a horizon. The `travel-diary` style uses both between places, with a passport-stamp title on each new place.
* **The grid:** plan `grid` {cols, alpha} (style `motion.grid`) lays a fine grid of light lines over the whole reel. `cells`: the next shot fills in cell by cell, spreading from one spot (a third of the cells show a soft block of their colour first). With `motion.mosaic`, one held shot of a person near the middle becomes a photo wall: the cells round them fill one by one with pictures of other moments of the trip, hold, and clear again (segment `mosaic`; the cells the person stands in, found with the cut-out, stay clear). The `grid-mosaic` style is this trend.
* **Strip collages:** split-screen kinds `rows2`…`rows9` and `cols2`…`cols9` (style `panels.kinds`): the frame in bands across or down it, each a different clip, thin black seams between them; they fill in on the beat and collapse into one shot. They work in upright and wide reels alike.
* **The person stays, the world changes** (style `motion.backdrop`: `places`, `colour` or `both`; segment `backdrop` {items, every}): on a held shot of a person who fills enough of the frame, on each beat the background becomes another place of the trip (one picture per landmark) or a flat colour from the shot's own palette, while the person (an upright figure the cut-out finds in every other frame, smoothed over time) stays; the last beat shows the real place again. No person found: the shot plays as it is. With `motion.backdrop_first`, the reel opens on it: the best clip of a person facing the camera (a selfie, walking toward the camera, posing, or a face the detector finds), big in frame and in the reel's own orientation, takes the first slot. By hand: the Shot tab's **Behind the person** (expert), or plan edit `backdrop` {segment, mode places|colour|off}.
* **Sideways reels** (`--orientation sideways`, style `frame.output: sideways`, plan `frame.rotate: 90`): the reel is made widescreen and written turned on its side in an upright 1080x1920 file, so it plays full-screen when the phone is turned (the "turn your phone" trend).
* **Beat punch:** a quick zoom bump on every beat in energetic sections. **Shake** hits on the drop.
* **Photos:** stronger Ken Burns that varies per photo: zoom in or out, pans left, right or up, and a slow rotating zoom.
* **Static video clips** get a slow push-in, so nothing sits dead still.

Tune it per style:

```yaml
transitions:
  palette: {calm: [dissolve, blur], medium: [whip, zoom_in], intense: [flash, spin, glitch]}
  density: 0.5      # share of ordinary cuts with a transition (0 = all hard cuts)
  speed: 1.0        # <1 snappier, >1 slower
  # order: [split, vsplit, iris]   # instead of the palette: one on every cut, these in turn through the reel
  # beats: 2                        # how long a masked reveal lasts, in beats
motion:
  beat_punch: 0.06  # zoom bump per beat (0 = off)
  punch_on: [medium, intense]
  shake_on_drop: true
  video_push: 0.06
```

## In-camera transitions

When you swung the camera fast on purpose (a whip pan), TripShots cuts **inside the swing** to the next shot as a plain hard cut, and starts the next shot mid-swing when it has one too, so the camera's own motion blur hides the cut. Gemini finds these, and without Gemini a local check does (a short spike of camera motion with smeared frames). Up to 3 per reel, at least 4 s apart; a whoosh is placed on the cut. Turn off with `transitions: {in_camera: false}` in a style.

## Split screens, speed ramps and other trending cuts

* **Split screens and grids:** `split2` (two stacked), `split3` (three strips), `grid4` (2×2) and `columns3` (three tall columns, used only for upright clips: landscape clips are stacked top to bottom as `split3` instead, so you still see the subject). In **reveal** mode the panels slide, wipe or pop in one per beat. In **cycle** mode, once all are on screen they keep cutting to new clips on each beat, like several videos playing side by side. Each panel is cropped around its own subject. Set `panels: {use: 0.4, mode: mixed}` in a style, or use `--split-screens lots|some|off`.
* **Speed ramps:** see [Speed](#speed) below.
* **Bass-hit pulse:** a bulge/"pop" distortion on beats in intense sections (`motion: {pulse: 0.1}`).
* **Labelled montage:** the AI writes a short label for each shot ("Golden hour", "Worth every mile"). `text: {labels: {mode: ai}}` or `--labels ai`.
* **Seamless loop:** the last moment dissolves into the first frame, so the reel replays without a visible restart (`loop: true` or `--loop`).
* The new **`split-beat`** style uses all of these.

## Speed

Changing a clip's speed gives a shot impact: slow motion lingers on a moment, a speed-up gives energy, and a
ramp from one to the other lands a hit on the beat. TripShots picks these itself from the style, only on
clips with real movement (drone, pans, walking, cars, water), and only where the clip has enough footage.

| Effect | What it does | Good for |
|---|---|---|
| **Slow motion** | Calm clips play at half speed | Water, birds, people, waves |
| **Speed-up** | Moving clips in busy sections play 1.6× (medium) to 2.2× (intense), with motion blur | Driving, walking, crowds, clouds |
| `velocity` ramp | Rushes in at 2.6×, slams into slow motion **on the beat**, speeds back out | The classic "velocity edit" |
| `slam` ramp | Real time, then slow motion from the beat to the end of the shot | A jump, a landing, a wave breaking |
| `bullet` ramp | A short slow-motion hold around the beat, then real time again | A moment frozen in passing |
| `rush` ramp | Real time, then speeds up to 3.2× into the next cut | Building into a drop or a whip |
| `surge` ramp | A slow start that takes off to 2.4× | Take-offs, drone lift-offs, running |
| `impact` ramp | Starts in slow motion and picks up to real time | The shot right after a drop |

**Smooth slow motion.** Footage shot at 50 fps or more gives real slow motion. Slower footage (24/30 fps)
gets in-between frames made with optical flow, so it glides instead of stuttering (`speed.smooth: flow`, the
default; `blend` cross-fades frames, `off` repeats them). Ramps use the clip's full frame rate, so 60 fps
clips stay sharp in their slow part.

**The drop.** `speed.drop` sets what happens around the song's biggest drop: `rush` (the shot before speeds
into it), `impact` (the shot on it starts in slow motion), `both`, or `off`.

```yaml
velocity: {use: 0.3}                # share of moving clips with a ramp
speed:
  ramps: [velocity, slam, rush]     # which ramps to pick from
  fast: 0.2                         # share of moving clips sped up in busy sections
  fast_max: 2.2
  drop: both                        # rush | impact | both | off
  smooth: flow                      # flow | blend | off
```

From the command line: `--speed-ramps on|off|velocity,slam`, `--speed-up on|off`,
`--drop-speed rush|impact|both|off` and `--slowmo-smooth flow|blend|off`; in the app, the Make tab's speed
menus. To change one shot, edit the plan ([plan.json](plan-format.md)) or ask an agent; for example
`{"op": "ramp", "segment": 4, "ramp": "slam", "hit": 0.5}` or `{"op": "speed", "segment": 6, "speed": 2}`.
The storyboard shows each shot's speed or ramp; a whoosh lands where a ramp slams into slow motion.

| Style | Ramps | Speed-ups | Drop |
|---|---|---|---|
| `beat-montage` | velocity, slam, rush on 30% | 20% | both |
| `pov-hook` | velocity, rush, surge on 20% | 35% | rush |
| `cinematic` | slam, bullet on 25% | none | impact |
| `split-beat` | velocity, slam on 35% | 15% | off |
| `slow-scenic` | none | none | off |

## Hype effects and the beat check

* **Camera shake on a drop** (`motion: {shake_on_drop: true}`): a short jolt when a cut lands on a drop. It is used only where it fits: a drop in an intense section of a reel that isn't mostly calm, on a shot playing at real speed or faster, and not where a freeze-frame already hits. A clone shakes only where the reference shakes. The plan marks those segments `shake: true`; delete it to drop one.
* **Freeze-frame**: on the song's biggest drop the picture freezes for about half a second with a white flash, a push-in and a little shake, then carries on. On in `beat-montage`, `pov-hook` and `split-beat` (`motion: {freeze: true}`).
* **Colour-split glitch**: a short RGB split on some hard cuts (`motion: {rgb_split: 0.3}` = 30% of them).
* **Beat check**: after every render, TripShots finds each hard cut in the finished video and reports how many land within one frame of the plan and on a beat ("beat check: 12/12 measurable cuts within 1 frame").

## Steady shots

Handheld clips wobble, and in a calm, held shot the wobble reads as a mistake. TripShots measures how much each
clip shakes (its own motion analysis, the AI's "shaky" note, and Gemini's steadiness rating when Gemini is set up).
In the shots that need it, the part of the clip the reel uses is stabilised before rendering:

- with ffmpeg's **vidstab** (two passes: measure the camera's path, then follow a smoothed version of it, zoomed just
  enough to hide the edges), when the ffmpeg in use has it (`tripshots doctor` says so);
- otherwise with TripShots' own stabiliser: corners tracked from frame to frame, the camera's path smoothed over about
  a second, and each frame moved back onto it, zoomed in at most 12% so no edge shows.

A deliberate pan or push stays; only the shake is taken out. Each clip is stabilised once and cached
(`~/.tripshots/cache/stab/`), so editing the plan never redoes it.

```yaml
shots:
  stabilize: auto   # auto: shaky clips in calm or held shots (never one with an added camera shake) | on: every shaky clip | off
```

`cinematic`, `slow-scenic`, `grid-mosaic`, `mask-reveal` and `shape-cut` use `on`. For one reel use
`make --stabilize on|off`; for one shot, **Stabilise this clip** in the app's Shot tab (expert) or plan edit
`stabilize` {segment, on}.

## Framing the subject

* When the AI judges a shot, it also returns a **subject box** (the peak, waterfall, person, car…). Shots judged before this feature fall back to on-device saliency detection. Run `--rescore` once to get AI boxes for them.
* **Landscape to 9:16:** the crop holds on to the shot's focus: the person when there is one, else the most important subject that fits the vertical window (the AI lists subjects by importance). Only a wide view with no single focus pans, and slowly: at most about 6 % of the picture's width per second, around its middle, so it reads as a camera move rather than a slide. A frame far too wide to crop is treated the same way (segment `wide: true`); the whole frame over a blurred copy (`blur_fill`) is used only when the style asks for it (`layout.landscape: blur_fill`), and a reel made mostly of such shots is made horizontal instead.
* **Photos** push in on their focus; sideways drifts stay small and pass through it. The hook, the payoff and the ending always push in. Only true panoramas (wider than 2.2:1) with no single subject travel across.
* **Moving subjects** (a car, a boat, someone walking) on a steady camera are tracked, and the crop follows them smoothly.
* **Photos:** the Ken Burns zoom pushes toward the subject and is capped so the subject never gets cropped out.

## Typography

Text is animated per frame and timed to the music. Five presets pair fonts with animations (`text.preset` in a style):

| Preset | Look |
|---|---|
| `bold` | Heavy condensed caps (Anton). Hook words pop in **on the beat**. Location as a title card: big name, tracked region, GPS line. |
| `editorial` | Serif italic (Playfair) lines slide up from a mask. Elegant serif title card. |
| `minimal` | Small tracked sans (Montserrat) whose letter-spacing opens up. One-line location with coordinates. |
| `handwritten` | Marker and script fonts that scale in. |
| `typewriter` | Monospace, typed letter by letter. |

### Motion text (HyperFrames)

With the HyperFrames runtime installed (`tripshots maps --setup`, Node.js 22+; the route map uses the same one), the
hook, location, labels and closing line are animated in a real browser instead of frame by frame, which allows soft
focus and blur. TripShots still decides what the words say, their font, size and position; only the animation
changes. Captions keep the classic animation. Pick with `text.motion` in a style, `--text-motion` on `make`, `clone`
and `render`, or `"motion"` on one overlay in the plan:

| Motion | What it does | `auto` uses it for |
|---|---|---|
| `rise` | words rise into place out of a blur, one after another | editorial hooks, bold locations |
| `focus` | each line resolves from a soft focus pull | minimal hooks |
| `tracking` | letters close in from wide spacing out of a haze | minimal locations |
| `typewriter` | typed letter by letter behind a blinking caret | typewriter |
| `slam` | words drop in from large and land with a three-frame shake, on the beat | bold hooks and labels |
| `write` | written on from left to right with a soft pen edge | handwritten |
| `cinema` | the title fades up and drifts, the line under it tracks in | editorial locations |
| `decode` | letters resolve left to right out of flickering random letters and digits | (pick it) place names, coordinates |
| `stamp` | the title slams down as a passport stamp: red letters in a bordered cream box, at an angle, with a landing shake | the `travel-diary` style |

`off` keeps the classic animation. Without the runtime, `auto` quietly keeps it too. Each title is rendered once
(about 10 s) and cached in `~/.tripshots/cache/text/`. The animations follow text primitives from the
[HyperFrames registry](https://github.com/heygen-com/hyperframes) (Apache-2.0).

* Text is placed automatically in the calmest band of the frame (sky, water), away from the subject, inside Instagram's safe zones. A soft shade is added behind it on bright skies.
* **Location titles name what people recognise:** a famous spot inside a park ("Glacier Point, Yosemite National Park"), else the national park or protected area ("Yosemite National Park, California"), else a famous spot nearby (one with a Wikipedia entry), else the town; a county only when there is nothing else. Parks and landmarks come from OpenStreetMap. A title always names the shot it is over. Wrong anyway? `--location "Name, Region"`, or `--no-location` for none.
* Three kinds of text: the **hook** (first seconds, AI-written or `--hook`), the **location** (from GPS or `--location`, with a coordinates line; `location: {coords: false}` hides it), and an optional closing **CTA** (`cta: {mode: ai}`, e.g. "Save this for your next road trip").
* Fonts are bundled under the SIL Open Font License / Apache 2.0 (`tripshots/fonts/`). Use your own with `text.hook.font: /path/to/font.ttf`.

## Title behind the subject

With the `bold`, `editorial` and `handwritten` presets, the location title becomes a giant place name **tucked behind the skyline**. It rises up from behind the mountains, and peaks, trees, buildings or a lighthouse overlap the letters. TripShots finds the sky on every frame (no AI model, no upload) and puts the foreground back over the text, so it holds up while the shot pans.

* It's used only when the shot has clear sky and the letters really overlap the land. Otherwise the regular title card is shown.
* The title starts with a shot and ends with it, so a cut never re-slices the letters with a different skyline.
* Turn it off with `text: {location: {behind: off}}`, or force it with `on`. `behind_font` picks the font (`anton`, `bebas`, `dmserif`, `marker`, …).

## Pop-out frames (subject steps out of the photo)

The photo sits in a frame on a paper (or blurred, soft-colour or dark) background, and the person or subject **breaks out of the frame**: head and shoulders above the top edge, or legs and the rock they stand on spilling below the bottom edge. The variant is chosen automatically from where the subject is.

```bash
tripshots frame ~/Pictures/BigSur -f post            # 4:5 images for a feed post / carousel
tripshots frame best.jpg -f both --bg blur --border  # post + story, blurred background, white print border
```

* In the app, use the **Frames** tab.
* In reels, set `popout: {use: 0.4}` in a style and photos with one clear subject become animated shots: the frame settles in, then the subject steps out on the beat.
* The cut-out uses **rembg** (MIT, IS-Net model) on your Mac. The model downloads once (~170 MB) and each photo's cut-out is remembered. Photos without one clear subject (a pure landscape) are skipped.

## Animated route map (optional)

TripShots can draw your trip as an animated map on top of the reel, using the GPS in your photos and clips:

* **intro**: a big map card early in the reel. The route draws itself stop to stop, each stop pops in **on the beat** with its name, and the card ends with "6 STOPS · 1,208 KM".
* **tracker**: a small map in the top-left corner for most of the reel. A dot jumps to where each shot was taken and the place name changes with it.
* **both**: the intro card, then the tracker.

```bash
./install.sh --maps                                   # one time: Node.js + HyperFrames (~100 MB)
tripshots make ~/Trips/Portugal -m song.mp3 --route-map intro
tripshots make ~/Trips/Portugal -m song.mp3 --route-map both
```

* Stops come from the GPS and capture times of all your footage: shots taken close together become one stop, and at most 7 stops are shown. Names come from OpenStreetMap, the same lookup as the location titles.
* The map is drawn offline from Natural Earth data (coastlines, lakes, rivers, country and state/province borders). No map tiles are downloaded and nothing is uploaded. The theme follows the text style (dark for `bold`, light paper for `editorial`/`minimal`), or set `route_map: {theme: dark|light}`.
* It's rendered by [HyperFrames](https://github.com/heygen-com/hyperframes) (HeyGen's open-source HTML-to-video renderer) as a transparent layer and laid over the graded footage. Your footage itself never goes through the browser. Telemetry is turned off. Each map is cached, so re-renders are instant.
* In a style: `route_map: {mode: intro, theme: auto, title: "Southern Iberia"}` (`title` overrides the heading, which by default lists the countries or states).
* Footage without GPS (some cameras, screenshots, edited exports) is ignored. If nothing has GPS, the reel is made without a map.


---
[Docs home](README.md)
