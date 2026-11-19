# The effects library

TripShots has a library of transitions, text motions, text looks and shot effects. Each item records its
energy (calm, medium, intense), its mood and what it suits. `tripshots effects` lists the library
(`--json` for the full list, or `transitions`, `text` or `shot` for one part). In the desktop app, the Shot tab
shows each item drawn on your own shots.

| Part | Where it lives | What it is |
|---|---|---|
| Transitions | `motion.py` | 38 ways from one shot into the next: soft (dissolve, light-led `luma`, light leak, ripple), graphic (push, wipe, clock, blinds, card flip, paper shapes, reveals, halftone `dots`), trend (`film` strip roll, paper `tear`, 3D `cube`, reel `card` flick), punchy (zoom blur, shake, flash, RGB split, glitch, pixels, stretch) |
| Text motions | `hfx.py` | how a line comes in: rise, pull focus, film title, spread, typewriter, handwritten, decode, stamp, slam |
| Text looks | `typo.py` (`LOOKS`) | how the letters are drawn: neon, glow, outline (hollow), offset (a hard copy behind in the accent colour) |
| Shot effects | `vfx.py` | an effect on one whole shot: glow, dream, light leak, old film (`dust`), VHS, black and white, duotone, chromatic edges, beat flicker, mirror, handheld drift, tilt-shift |
| Signature moves | `fxlib.MOVES` | the big trend ideas, each first made as a style from reference reels: the photo wall (the grid cells round you fill with the trip's other places), grid lines, the backdrop swap (places or flat colours behind you, a new one on each beat), the silhouette flash, colour bloom (black and white into colour), the freeze-frame intro (the moment stops, you outlined in white like a sticker, the world grey), the clone trail (copies of you left where you stood on earlier beats), colour pop (you in colour, the rest black and white), spotlight (the lights go down round you), the camera roll opener (the phone's photo grid scrolls and one picture opens into the shot), the flash zoom (on the beats the picture snaps closer to the person's face in steps, a flash on each hit, following them as they move) |
| Page layouts | `pages.py` | the whole reel set on pages: the gallery print (each shot a photographic print on paper, a word or two above it, where and when in small captions under it) and the route split (each shot in a wide window, the place's name under it, the trip's route on a map below with a pin jumping to where it was filmed) |

### Where the trend moves come from

Each one follows how editors make it by hand (2026 CapCut, Premiere and After Effects tutorials, and the trend
pages they come from), done automatically:

| Move or transition | By hand | Here |
|---|---|---|
| Freeze-frame intro | freeze a frame on a beat, cut the person out, add a white outline, dim and blur the rest, a little zoom | `pose` {at, dur, outline}: on a beat clear of the transitions, held 1-4 beats; a camera click in the sound |
| Clone trail | a locked-off shot; freeze the subject at intervals, mask each one, stack the masks over the moving clip | `clones` {times, alpha}: a pose kept on beats over the first two thirds; only a still camera and a person big in frame |
| Colour pop, spotlight | black-and-white (or darkened) layer with the person masked out | `isolate` {kind pop/spotlight, amount}: the person followed every other frame, eased in |
| Camera roll | a screen recording of the camera roll, keyframed zoom into one photo that becomes the clip | `roll` {cells, target, dur}: a grid of the trip's photos scrolls and slows, then the cell opens to full screen, on the opening shot or the first shot of a new place |
| Flash zoom | keyframe a scale up onto the face on each beat (or cut to tighter crops), add a white flash frame or a flash overlay on each hit, re-centre the crop by hand as the person moves | `zoompunch` {times, zooms, flash, focus}: the last 2-4 beats before the cut, the zoom growing in even steps (or snapping back out on the last hit); the person's head is found with the cut-out every other frame and followed smoothly, else the shot's subject; a hit in the sound on each punch |
| Gallery print | photos placed on a white page in a mock-up template, a title above, captions in the corners, a page per beat | `pages.py` print: upright shots stand as 2:3 prints with the word across their top, wide ones lie as 3:2 prints with the word above; the word comes from the scene the AI saw (The Peaks, The Coast, From Above; none when unsure), captions are the landmark or state and the month; the hook's shot stays full screen |
| Route split | the clip in the top half, a screenshot of the route map below, a pin moved by hand per place | `pages.py` route: the shots go in the order they were filmed (each slot keeps its length), a stop per place 25 km apart, the pin on the stop, a camera without GPS takes the place of the trip's photo taken nearest in time (within three hours), else no pin; the hook becomes the first page's caption |
| Film strip, paper tear, cube, card, dots | overlay packs and 3D transforms in CapCut and After Effects | `motion.t_film`, `t_tear`, `t_cube`, `t_card`, `t_dots` |

The cut-out moves need a person big enough to cut out: the AI's shot size must not be wide (or the subject box
must be big). Where the cut-out finds nobody, the shot plays as it is.

Every reel can use all of it. You don't have to choose the grid or swap style, or give a reference reel, to get a
photo wall or a backdrop swap: the director below offers the moves to any reel whose footage can carry them.

## The effects director

`make` ends with the effects director (`fxlib.direct`). The AI is shown the reel:
- each shot's role, length, music level and what it shows;
- where the cuts fall, and which ones the style already gave a transition;
- the lines of text;
- the library.

It then picks a transition for each cut, a motion and look for each line of text, an effect for a shot or
two, and up to two signature moves, with a reason for each one. TripShots checks the answer:
- only items from the library are used;
- the number of transitions stays about where the style put it;
- at most three kinds of transition appear in one reel;
- at most two shots get an effect (style `effects.max_shot_effects`);
- a move only goes on a shot that can carry it, and the AI is told which those are. The photo wall needs a held
  shot of a person mid-reel; the backdrop swap needs a clip of a person big in frame, held for at least three beats;
  the silhouette flash needs people; the freeze-frame intro, colour pop and spotlight need a person big in frame; the
  clone trail also needs a still camera; the camera roll opens the reel or a new place; the flash zoom needs two
  beats clear of the transitions and a person or one clear subject. The page layouts take the whole reel: an upright
  reel without letterbox bars and not made from a recipe, for the route footage from three places or more. At most two kinds of move
  are used (`effects.max_moves`). A move the style already does (the `grid-mosaic` style's wall, for example)
  isn't offered again.
- the AI also sets each choice up for this reel, within limits: a transition's direction (push, whip, wipe, cube,
  film, tear, ...: `fxlib.TRANSITION_PARAMS`), and a move's settings (how many beats a freeze holds, how many clones,
  how strong the colour pop or spotlight, how long the camera roll, the grid's size, the flash zoom's hits, how close it
  gets, its flash colour and whether it aims at the face or the whole person: `fxlib.MOVE_SETTINGS`). Values
  out of range are clipped, unknown ones dropped.

Without an AI, one move is still chosen by rules when the reel plainly has what it needs:
- you in frame on an upbeat song get the backdrop swap;
- a held shot of you mid-reel on a calmer song gets the photo wall;
- you on the drop of an upbeat song (100 BPM or more) get the flash zoom;
- you on the payoff of a fast song (110 BPM or more) get the freeze-frame intro;
- otherwise the payoff blooms into colour.

Lines of text you styled yourself are left alone. A style that orders its own transitions, and reels made from a
recipe, keep their transitions.

- `make --effects auto` (default): the AI chooses when one is set up; otherwise the style's own choices stand.
- `--effects rules`: rules choose instead of the AI, by the music's energy and what the next shot shows (warm
  light into a sunset, water into water, punch on a drop).
- `--effects off`: no director.
- `make --page print|route|off` (or style key `page: {kind, paper, theme}`) puts every shot on a page without asking
  the director; `off` keeps pages out. Plan edit `{"op": "page", "kind": "route"}` / `"off"`, and
  `{"op": "page", "segment": 3, "title": "Big Sur", "left": "...", "right": "...", "label": "..."}` for one page's words.
- Style key `effects`: `{use, transitions, text, shots, moves, max_shot_effects, max_moves}` (`moves: false`
  keeps a style free of them).

What was decided is kept in the plan (`effects`: by, summary, changes, why; the moves also in `moves`). It is shown in the editor's Shot
tab, where **Choose effects with AI** runs the director again (plan edit `auto_effects`, MCP `edit_plan`). Choosing
again takes out the moves it chose before; ones a style or you set stay.

## By hand

- Plan edits: `{"op": "transition", "segment": 3, "to": "push"}`, `{"op": "effect", "segment": 3, "id": "glow",
  "amount": 0.5}` (`id: null` removes it), and `{"op": "edit_text", "index": 1, "motion": "stamp", "style":
  {"look": "neon"}}`.
- MCP: `list_effects` returns the library.
- Desktop: the Shot tab has a transition picker and an effect picker, both filtered by energy, with an amount
  slider. The Text tab has **Motion** and **Look**.
