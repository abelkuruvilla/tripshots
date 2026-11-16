# Where the craft comes from

TripShots' story and editing rules are its own code, but many of them write down what experienced editors already
do. In November 2026 we read the editing, storytelling and effects skills in
[awesome-claude-video-skills](https://github.com/zhuyansen/awesome-claude-video-skills), using only entries the
catalogue grades **SAFE** (Agent Skills Hub's grade of each repository's README and install steps; it is not a code
audit). We read the method notes as reference material only: nothing was installed or run, and no code was
copied. Some of these repositories have licences that don't allow commercial use, so only the ideas were taken.

## What we took, and from where

| Idea | In TripShots | Read in |
|---|---|---|
| Every cut changes size, direction, light, colour or subject; avoid near-identical neighbours | [Shot grammar](storytelling.md#shot-grammar) | qingyunAGI/qingyun-cine-skill (beat-sync editing) |
| Open each chapter wide; neighbouring shots differ in size | [Shot grammar](storytelling.md#shot-grammar) | TheMarco/claude-music-video |
| Never the same camera move three shots running ("three pushes read as a slideshow") | [Shot grammar](storytelling.md#shot-grammar) | alchaincyf/huashu-art-motion (video grammars) |
| Each place is a scene: orient, then develop, then a detail; end a clip once its action reads | [Shot grammar](storytelling.md#shot-grammar), [director's notes](../tripshots/DIRECTOR.md) | denyakortunov/family-travel-editor |
| Two to four black frames before a major hit | `motion.blackout` | qingyunAGI/qingyun-cine-skill |
| Start near the climax, keep the setup short, turn at about two thirds, short close (起承转合) | [director's notes](../tripshots/DIRECTOR.md) | jtydhr88/screenwriting-skills |
| Pay off what you set up; don't stack two rises | [director's notes](../tripshots/DIRECTOR.md) | jtydhr88/screenwriting-skills |
| Vary the cut spacing: a metronome reads as boredom | [director's notes](../tripshots/DIRECTOR.md) | iart-ai/tiktok-video-skills |
| A print dropping in and opening into the scene (card-to-full-frame) | transition `polaroid` | Dryxio/effects-skill, RajaskaJanuardani/motion-craft, feitangyuan/onetake (ideas) |
| A reflection fold at the horizon | transition `mirror` | superyhee/hypr-video-skills (mirror effect) |
| Letters resolving out of random glyphs | text motion `decode` | hughminhphan/motion-kit, Phucanh-MRT/mrtkeyword (decode-word) |
| A stamp slamming onto the frame | text motion `stamp` | Phucanh-MRT/mrtkeyword (stamp-hit), Vibha-Ramprakash/claude-video-effects |

## Already in TripShots

Many rules in these skills were already part of the engine: the hook in the first second and no fade up from black,
shots getting shorter into the drop, the best shot on the biggest hit, a breath before it, the ending matching the
opening so the reel loops, a few kinds of transition rather than a catalogue, one shot per moment, beat-locked text,
safe zones, and checking frames after every render.

## Read and not used

- **Talking-head effects** (face-tracked widgets, comment boxes, tier lists): TripShots reels have no presenter.
- **Generated footage and avatars:** TripShots edits your own photos and clips.
- **Fixed explainer timings** (shots of 5-9 s): they suit narrated films, not music-driven reels.
