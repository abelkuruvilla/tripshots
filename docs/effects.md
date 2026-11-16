# The effects library

TripShots has a library of transitions, text motions, text looks and shot effects. Each item records its
energy (calm, medium, intense), its mood and what it suits. `tripshots effects` lists the library
(`--json` for the full list, or `transitions`, `text` or `shot` for one part). In the desktop app, the Shot tab
shows each item drawn on your own shots.

| Part | Where it lives | What it is |
|---|---|---|
| Transitions | `motion.py` | 33 ways from one shot into the next: soft (dissolve, light-led `luma`, light leak, ripple), graphic (push, wipe, clock, blinds, card flip, paper shapes, reveals), punchy (zoom blur, shake, flash, RGB split, glitch, pixels, stretch) |
| Text motions | `hfx.py` | how a line comes in: rise, pull focus, film title, spread, typewriter, handwritten, decode, stamp, slam |
| Text looks | `typo.py` (`LOOKS`) | how the letters are drawn: neon, glow, outline (hollow), offset (a hard copy behind in the accent colour) |
| Shot effects | `vfx.py` | an effect on one whole shot: glow, dream, light leak, old film (`dust`), VHS, black and white, duotone, chromatic edges, beat flicker, mirror, handheld drift, tilt-shift |

## The effects director

`make` ends with the effects director (`fxlib.direct`). The AI is shown the reel:
- each shot's role, length, music level and what it shows;
- where the cuts fall, and which ones the style already gave a transition;
- the lines of text;
- the library.

It then picks a transition for each cut, a motion and look for each line of text, and an effect for a shot or
two, with a reason for each one. TripShots checks the answer:
- only items from the library are used;
- the number of transitions stays about where the style put it;
- at most three kinds of transition appear in one reel;
- at most two shots get an effect (style `effects.max_shot_effects`).

Lines of text you styled yourself are left alone. A style that orders its own transitions, and reels made from a
recipe, keep their transitions.

- `make --effects auto` (default): the AI chooses when one is set up; otherwise the style's own choices stand.
- `--effects rules`: rules choose instead of the AI, by the music's energy and what the next shot shows (warm
  light into a sunset, water into water, punch on a drop).
- `--effects off`: no director.
- Style key `effects`: `{use, transitions, text, shots, max_shot_effects}`.

What was decided is kept in the plan (`effects`: by, summary, changes, why). It is shown in the editor's Shot
tab, where **Choose effects with AI** runs the director again (plan edit `auto_effects`, MCP `edit_plan`).

## By hand

- Plan edits: `{"op": "transition", "segment": 3, "to": "push"}`, `{"op": "effect", "segment": 3, "id": "glow",
  "amount": 0.5}` (`id: null` removes it), and `{"op": "edit_text", "index": 1, "motion": "stamp", "style":
  {"look": "neon"}}`.
- MCP: `list_effects` returns the library.
- Desktop: the Shot tab has a transition picker and an effect picker, both filtered by energy, with an amount
  slider. The Text tab has **Motion** and **Look**.
