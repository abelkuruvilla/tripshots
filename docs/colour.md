# Colour grading

Every reel is colour graded shot by shot, like a colourist would, not with one filter on top:

1. **Each shot is measured**: its brightness range, its colour cast (read from the greys and whites in it, so a blue sky or a red wall doesn't count as a cast), its saturation.
2. **The AI colourist looks at the shots** (one contact sheet; verdicts are remembered per shot) and decides per shot: raise or lower exposure, fix white balance or keep it, and whether the light *is* the mood (sunset, blue hour, night, fog) so the look is applied gently and a sunset stays a sunset. With `look: auto` it also picks the look that suits the footage.
3. **A look is applied**: tone curve and contrast, black lift and highlight roll-off, split-tone tints in shadows / mid-tones / highlights, saturation, and hue moves (e.g. greens toward teal, skin toward orange), plus grain and vignette for film looks. Skies are protected so they never turn purple, and whites stay clean.
4. It's all baked into one small 3D LUT per shot that ffmpeg applies while rendering, so it costs no extra time. Shots from your phone, a drone and a camera end up matching.

## Flat log footage

Some cameras can film a flat "log" picture, which keeps more of the highlights and shadows: Apple Log on iPhone,
D-Log on DJI drones, S-Log3, V-Log, F-Log or C-Log3. TripShots turns such a clip into normal-looking video before
it does anything else with its colour (`camlog.py`). It decodes the maker's published log curve to scene light,
converts the colours to Rec.709 and rolls off the highlights the way film does. Grading then measures the
converted picture.

This happens automatically only when the file's camera can film log and the clip looks flat. A flat clip from an
unknown camera is never guessed at. To choose by hand:
- **Colour tab → Filmed in**, with **All clips** to apply it to the whole reel;
- the plan edit `{"op": "log", "segment": 3, "profile": "dlog"}`, where `"auto"` detects again, `null` means
  as filmed, and `"segment": "all"` changes every clip.

The conversions are written once as `.cube` files in `~/.tripshots/luts/camlog/`. They work with any editor
that reads LUTs.

D-Log M, Canon C-Gamut and DJI D-Gamut are not covered exactly:
- **D-Log M:** use D-Log, the nearest published curve.
- **C-Gamut and D-Gamut:** converted through Rec.2020, the nearest wide colour space.

## Layers: grading parts of the frame

After the primary grade (balance and look, one LUT per shot), each shot can have **layers**: corrections on parts
of the picture, the way a colourist adds windows and qualifiers as serial nodes in Resolve.

| Region | What it is |
|---|---|
| `sky` | everything above the skyline, clouds included (people against the sky are left out) |
| `subject` | the person or main subject, found in the frame a few times a second (faces, then a quick cut-out) |
| `skin` | skin tones on the people |
| `greens` | foliage and grass |
| `water` | sea, lakes and rivers below the sky |
| `ground` | the lower frame, feathered from the horizon (a graduated filter) |
| `edges` | everything around the subject (a relight / vignette that leads the eye) |

Each layer sets exposure, contrast, saturation, warmth, tint and hue for its region, through a soft mask that
follows the picture frame by frame without flicker. The AI colourist looks at every shot and proposes what that
frame needs ("bright cloud bank held back", "walkers lifted out of their own shade", "autumn aspens a touch
richer"); without an AI, rules on the thumbnail hold back bright skies, lift people in shade, keep skin natural and
ease the edges down. Layers are applied where frames are put together, so changing one never re-renders a shot
(about 25 ms a frame).

In the app: a reel's **Colour** tab > **Layers**: turn each on or off, change it, show its mask on the picture,
add or remove one, or go back to **Automatic**. In a plan: segment `layers`; `edit_plan`
`{"op": "layer", "segment": 3, "region": "sky", "exposure": -0.3, "saturation": 1.1}` (`"remove": true`,
`"on": false`, `"segment": "all"`), `{"op": "layers_auto", "segment": 3}`.

## Looks

Built-in looks (`tripshots looks`):

| Kind | Looks |
|---|---|
| Everyday | `natural`, `documentary`, `vivid` |
| Cinematic | `cinematic-film` (a feature film's print), `blockbuster` (strong teal and orange), `bleach-bypass` (silvery, little colour), `teal-orange`, `moody` |
| Travel | `coastal` (aqua water, white sand), `desert-warm` (red rock and sand), `alpine` (crisp whites, deep blue sky), `tropical` (lush greens, turquoise), `forest-moody` (deep woods, mist) |
| Light and film | `golden-hour`, `blue-hour`, `night-neon` (city at night), `portrait-film` (warm skin, soft contrast), `warm-film`, `faded-matte`, `nordic`, `black-and-white` |

Looks marked *film* finish like a print: highlights roll off softly instead of clipping and bright colours thin
out the way they do on film stock.

With `look: auto` the AI colourist picks from all of them, and your own (below), for what the footage shows and the
story it tells (beaches → coastal, red rock → desert-warm, snow and lakes → alpine, a road trip → cinematic-film).
Without an AI, the shots' tags decide (coast, desert, mountains, jungle, forest, sunset, night), then the light.

## Any LUT as a look

A look can also be a 3D LUT: a `.cube` file or a HaldCLUT image (`.png`), alone, in a folder, in a zip or at a link.
Each shot is balanced first (exposure, colour cast, tones), so shots from different cameras still match, and the LUT
goes on top at the look's strength, with skin kept closer to its own colour. Every LUT is measured on test colours:
`tripshots looks` says what it does in plain words ("cool blue shadows, warm highlights, muted colour"), the AI can
pick it, and LUTs made for log footage (a camera's flat profile) or that invert the picture are never picked on
their own.

```bash
tripshots looks add ~/Downloads/MyLUTs.zip            # .cube / HaldCLUT files, folders, zips or links
tripshots looks add grade.cube --name "Summer haze"
tripshots looks packs                                 # free packs that can be fetched
tripshots looks fetch gmic-creative                   # 33 creative LUTs from G'MIC (2 MB)
tripshots looks fetch film-simulation                 # RawTherapee's film emulations (about 300, 420 MB)
tripshots looks list --pack gmic-creative
tripshots looks remove --pack gmic-creative
tripshots make ~/Trips/Utah -m song.mp3 --look gmic-creative-late-sunset
```

The packs are downloaded from their authors' sites when you ask, never shipped with TripShots: neither states a
licence for the LUT files, so they are for your own reels (check with the authors before sharing the files). In the
desktop app: a reel's **Colour** tab > **More looks**. Imported LUTs live in `~/.tripshots/looks/lib`.

## Copying a reel's colour

```bash
tripshots make ~/Trips/Bali -m song.mp3 --look golden-hour           # pick a look
tripshots make ~/Trips/Bali -m song.mp3                              # look: auto (the AI picks)

# copy the colour of reels you like
tripshots look https://www.instagram.com/reel/AAA/ https://www.instagram.com/reel/BBB/ \
  --name dreamy --cookies-from-browser auto
tripshots make ~/Trips/Bali -m song.mp3 --look dreamy --grade-strength 0.9

# grade photos and videos on their own (copies; originals untouched) + before/after sheet
tripshots grade ~/Pictures/Bali --look dreamy -o ~/Pictures/Bali-graded
tripshots frame ~/Pictures/Bali -f post --look dreamy                # pop-out frames, graded
```

* A look copied from reels is matched colour by colour: each family (reds, oranges and skin, yellows, greens,
  cyans, blues) takes the references' hue and saturation, a family the references hardly have moves toward the one
  they use instead (blue skies turn teal-cyan when theirs are), and each tonal zone is taken to the references'
  tint from where the shot starts. Shots with people keep their shadows readable.
* `look` measures the reference reels' grade from their frames (it works best with 2–4 reels of the same creator) and the AI describes it in plain words. If the colour obviously comes from the scenes (every frame is a sunset), the tints are softened so your midday shots don't turn orange.
* `tripshots learn` also saves the references' colour as a look with the style's name, and the style uses it.
* In a style: `grade: {look: auto, strength: 0.75, ai: true}`. `look: none` turns grading off and uses the old `color:` settings (saturation, contrast, warmth, your own `.cube` LUT).
* Too strong or too weak? `--grade-strength 0.5` (subtle) … `1.0` (full).


---
[Docs home](README.md)
