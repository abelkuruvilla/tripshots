# AI backends

TripShots asks an AI to judge shots (light, composition, hook potential, where the subject is), pick a colour look, and write the hook, labels and caption. Everything else (shot detection, beat tracking, rendering, face recognition) runs locally without one.

Pick one:

* **Claude subscription (default).** Install [Claude Code](https://docs.claude.com/en/docs/claude-code) and run `claude` once to log in. TripShots runs it headless, so shot judging uses your Pro/Max plan and needs no API key.
* **MiniMax.** Put `MINIMAX_API_KEY=...` in `~/.tripshots/.env` and use `--backend minimax`. It uses MiniMax's Anthropic-compatible endpoint with `MiniMax-M3`, which accepts images. The M2.x models are text-only and can't judge footage.
* **Claude API key.** Set `ANTHROPIC_API_KEY` and use `--backend api`.
* **None.** `--backend none` uses only technical measures (sharpness, exposure, shake). It's quick and free, but has no taste.

Check everything with `tripshots doctor`.

TripShots checks that Claude Code is logged in before it starts (`claude auth status`, no request sent) and stops with instructions if it isn't, instead of failing on every contact sheet. If the login expires mid-run, it stops asking at the first refusal. `tripshots doctor` shows the login status.

Set the default with `TRIPSHOTS_BACKEND` in `~/.tripshots/.env` (or the app's Settings tab), or per run with `-b/--backend`. What is sent to each backend is listed in [Privacy](privacy.md).

## Optional: Gemini watches your clips

The default AI looks at stills. With a free [Gemini API key](https://aistudio.google.com/apikey) (`GEMINI_API_KEY` in `~/.tripshots/.env`, or the app's Settings tab), Gemini also *watches* each clip once, as a 480p proxy that is deleted from Google right after:

* the **best instant** of each clip (the wave breaking, the drone clearing the ridge), which the cut is then built around;
* **shake, tilt, bad exposure**, and whether the clip's own sound is ambience, speech or music (used for the clip-sound bed);
* **in-camera whip pans** you shot on purpose.

Results are cached per file, so a clip is only watched once. `--watch auto` (default: on when a key is set), `--watch gemini` (required), `--watch off`. Model: `TRIPSHOTS_GEMINI_MODEL` (default `gemini-flash-latest`, falls back to `gemini-2.5-flash` when busy). Your Claude / MiniMax backend still makes the creative calls; Gemini's score is blended in at 40%.


---
[Docs home](README.md)
