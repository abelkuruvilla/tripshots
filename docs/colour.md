# Colour grading

Every reel is colour graded shot by shot, like a colourist would, not with one filter on top:

1. **Each shot is measured**: its brightness range, its colour cast (read from the greys and whites in it, so a blue sky or a red wall doesn't count as a cast), its saturation.
2. **The AI colourist looks at the shots** (one contact sheet; verdicts are remembered per shot) and decides per shot: raise or lower exposure, fix white balance or keep it, and whether the light *is* the mood (sunset, blue hour, night, fog) so the look is applied gently and a sunset stays a sunset. With `look: auto` it also picks the look that suits the footage.
3. **A look is applied**: tone curve and contrast, black lift and highlight roll-off, split-tone tints in shadows / mid-tones / highlights, saturation, and hue moves (e.g. greens toward teal, skin toward orange), plus grain and vignette for film looks. Skies are protected so they never turn purple, and whites stay clean.
4. It's all baked into one small 3D LUT per shot that ffmpeg applies while rendering, so it costs no extra time. Shots from your phone, a drone and a camera end up matching.

Built-in looks (`tripshots looks`): `natural`, `teal-orange`, `golden-hour`, `warm-film`, `moody`, `nordic`, `vivid`, `faded-matte`.

```bash
tripshots make ~/Trips/Bali -m song.mp3 --look golden-hour           # pick a look
tripshots make ~/Trips/Bali -m song.mp3                              # look: auto (the AI picks)

# copy the colour of reels you like
tripshots look https://www.instagram.com/reel/AAA/ https://www.instagram.com/reel/BBB/ \
  --name dreamy --cookies-from-browser chrome
tripshots make ~/Trips/Bali -m song.mp3 --look dreamy --grade-strength 0.9

# grade photos and videos on their own (copies; originals untouched) + before/after sheet
tripshots grade ~/Pictures/Bali --look dreamy -o ~/Pictures/Bali-graded
tripshots frame ~/Pictures/Bali -f post --look dreamy                # pop-out frames, graded
```

* `look` measures the reference reels' grade from their frames (it works best with 2–4 reels of the same creator) and the AI describes it in plain words. If the colour obviously comes from the scenes (every frame is a sunset), the tints are softened so your midday shots don't turn orange.
* `tripshots learn` also saves the references' colour as a look with the style's name, and the style uses it.
* In a style: `grade: {look: auto, strength: 0.75, ai: true}`. `look: none` turns grading off and uses the old `color:` settings (saturation, contrast, warmth, your own `.cube` LUT).
* Too strong or too weak? `--grade-strength 0.5` (subtle) … `1.0` (full).


---
[Docs home](README.md)
