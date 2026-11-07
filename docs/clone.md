# Clone a reel shot for shot

`learn` copies a reel's general style. `clone` copies **one specific reel**: its exact cuts, pacing, sound, colour and on-screen text, filled with your own footage.

```bash
tripshots clone https://www.instagram.com/reel/XXXX/ ~/Trips/Iceland --cookies-from-browser chrome
tripshots clone https://www.instagram.com/reel/XXXX/ ~/Trips/Iceland --variants 3 --dry-run   # check first
```

1. The reel is cut into its shots at its exact cut frames (hard cuts, crossfades and white-flash cuts are recognised), so every cut stays on its soundtrack's beat.
2. The AI looks at each shot (wide landscape, aerial, close detail, walking POV…, plus how the camera moves and how busy it is) and reads its on-screen text, where it sits and what it's for (hook, place name, label, closing line).
3. The AI picks your best matching shot for every slot, with runners-up, and rewrites the text for your trip in the same format ("POV: you made it to Bali" becomes "POV: you made it to Moraine Lake"). It never invents facts your footage doesn't show.
4. The reel's colour grade is measured into a look and applied to your shots (or pick `--look`). Its sound is used, and an upload copy without the music (`.nomusic.mp4`, or `.noaudio.mp4` with sound design off) is written so you can post with the original sound from Instagram, starting at 0:00.
5. `NAME.clone.jpg` shows reference vs. your shot, slot by slot. Swap anything you don't like in the plan (`shot_id`) and `render`.

Options: `--variants N` (runner-up shots and alternative text), `--keep-text` (copy the text word for word), `--hype` (add freeze-frame and glitch), `--text-preset`, `-s style` (motion and text look). In the app: the **Clone** tab.


---
[Docs home](README.md)
