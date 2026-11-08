# Music and sound design

## Music

**Use the sound from any reel.** Pass a reel link instead of a file:

```bash
tripshots make ~/Trips/Banff -m "https://www.instagram.com/reel/XXXX/" --cookies-from-browser auto
tripshots music "https://www.instagram.com/reel/XXXX/" --cookies-from-browser auto   # just download + show BPM
```

It downloads the reel's soundtrack with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and cuts your footage to it from 0:00, the same place Instagram starts that sound. It also writes an upload copy without the music: `NAME.nomusic.mp4` (it keeps the sound effects), or `NAME.noaudio.mp4` when sound design is off. For a local music file, add `--upload-copy` to get one. Upload that copy, tap the sound name on the original reel → *Use audio* (or search it in the audio picker), and the cuts land on the beat. Your post then uses Instagram's licensed copy of the track rather than a re-upload. Most reels need you logged in, so pass the browser you use for Instagram with `--cookies-from-browser auto|safari|firefox`. To make that the default, set `TRIPSHOTS_COOKIES_BROWSER=chrome` in `~/.tripshots/.env`. Downloads are cached in `~/.tripshots/music/`.


* Cuts follow the actual beats of the track (librosa beat tracking, refined to about 5 ms). TripShots picks the most energetic window of the song so the hook lands at once.
* **Copyright tip:** Instagram can mute or block reels that use commercial songs from your own files. The usual workflow is:
  1. Find the trending sound in Instagram (the ↗ arrow in the audio picker marks trending audio) and download or record a similar-tempo track, or use the same song if you own it.
  2. Make the reel with that track so the cuts match its tempo.
  3. In Instagram, mute the original audio and add the trending sound from the app. The cuts stay on beat when the tempo matches.
* No `--music` gives a silent reel cut to a 100 BPM grid.

## Sound effects and ambience

Every reel gets a sound layer under the music, placed on the exact frames of the edit:

| on screen | sound | lands |
|---|---|---|
| whip / zoom / spin transition, speed ramp | a whoosh | its loudest moment on the cut (the motion's peak), or where the ramp slams into slow motion; a `rush` ramp's on the cut it speeds into |
| the freeze-frame on the drop | a riser, then one impact | the riser ends 120 ms before the hit; the hit on the frame |
| flash cut / glitch cut / colour split | camera shutter / short glitch | on the cut |
| hook words popping in on the beat | soft pops, climbing in pitch | each word's first frame |
| location title, map card | a short swish | as it slides in |
| map pins, tracker moves, split-screen panels, pop-out photos | pops / ticks | as each appears |
| plain hard cuts | nothing (the music carries them) | |
| each place | a quiet ambience bed: waves, wind, birds, waterfall, city | cut with the picture |

* **Real recordings first.** Sounds come from your own folder (`~/.tripshots/sfx/library/<whoosh|impact|riser|pop|...>/`), then [Openverse](https://openverse.org) (real CC0 / public-domain recordings, fetched once and cached), then [earshot](https://github.com/Leonxlnx/earshot)'s sound bank (built in code, offline, `./install.sh --sound`), and only then a tiny built-in fallback (the log tells you).
* **Measured, not guessed.** Every take is analysed (where its attack and loudest point are, clipping, length) and aligned by its role: attack on the frame for hits and pops, peak on the cut for whooshes, end before the hit for risers. Takes rotate so nothing machine-guns, with small level variation, and runs of pops climb in pitch.
* **Restraint.** About 6 designed sounds in any 10 seconds; the impact and riser win, word-pop runs count as one gesture. The rules follow earshot's `real-sound` skill and the Real SFX skill (sounds only where something on screen causes them).
* **Mix and master.** Effects sit under the music, the mix is mastered to about -14 LUFS with a -2 dB peak ceiling (Instagram's level).
* **Files:** `NAME.sound.jpg` (music and effects waveforms over the beat grid and cuts, every cue marked), `NAME.sound.json` (every cue, its take, source and licence), `NAME.sfx.wav` (effects + ambience stem), `NAME.credits.txt` (only if you allow credited CC BY sounds).
* **The clip's own sound.** When a clip recorded clean ambience (real surf, a real street), that segment uses it instead of a library bed (`--clip-sound auto|on|off`). It's rejected when it's near silent, clipped, mostly wind rumble (over 60% of the energy below 150 Hz), full of knocks, or when Gemini heard speech or music in it. `NAME.sound.json` → `native` says why each clip was or wasn't used; the sound sheet marks its own sound in amber.
* **Posting with Instagram's sound:** the upload copy is now `NAME.nomusic.mp4` with the effects kept. Add the song in Instagram and set "original audio" to about 40-60%.

```bash
tripshots sounds --fetch                       # once: a starter set of CC0 effects + ambiences from Openverse
tripshots make ~/Trips/Iceland -m song.mp3     # sound design is on by default
tripshots make ... --sfx off --ambience on     # just the ambience; --sfx-level -3 for quieter effects
tripshots make ... --sfx-licenses cc0,pdm,by   # also credited CC BY sounds (credits file written)
tripshots listen reels/NAME.mp4                # optional: earshot listens to the finished reel (./install.sh --sound-ears)
```

In a style: `sound: {sfx: on, ambience: on, native: auto, level_db: 0, licenses: "cc0,pdm"}`. In the app: the Make tab's sound menus, and **Music → Get real sound effects**.


---
[Docs home](README.md)
