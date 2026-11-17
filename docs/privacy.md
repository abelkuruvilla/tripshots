# Privacy

TripShots runs on your computer. Your footage is read where it is and never uploaded by TripShots itself; finished
reels are written to your disk. Some features do talk to outside services. This page lists every one, so you can
decide what to turn on.

| Feature | Sends | To | Turn it off |
|---|---|---|---|
| AI shot judging, colour notes, hooks, captions, labels | Small JPEG stills and contact sheets of your shots (not the video files), technical numbers (length, fps, brightness, shake), place names | Your chosen AI: Anthropic (Claude Code / API), MiniMax, OpenAI, Google, xAI, Mistral, OpenRouter (and the model it routes to), DeepSeek, or Ollama on your own computer (nothing leaves it) | `--backend none` / `TRIPSHOTS_BACKEND=none` |
| `tripshots ask` / the app's Ask tab | Your request, today's date, the names and aliases of people you've taught it, your trips (dates, GPS centre points, folder names), style names, the file names (not paths) of tracks in `TRIPSHOTS_MUSIC` | Your chosen backend | Don't use `ask`; use `find` + `make` |
| Gemini video watching (optional) | A 480p, 15 fps proxy of each clip with its sound, deleted from Google right after | Google Gemini API | Leave `GEMINI_API_KEY` unset, or `--watch off` |
| Place names (location titles, trips) | GPS coordinates rounded to about 10–100 m | OpenStreetMap Nominatim (town) and Overpass (the park or landmark the point is in or near) | `--no-location`, `trips --no-names`, or `TRIPSHOTS_OFFLINE=1` |
| Place search (`find --place`) | The place name you typed | OpenStreetMap Nominatim | Use `--near` or `--text`, or `TRIPSHOTS_OFFLINE=1` |
| Sound effects | Search words such as "whoosh" or "ocean waves" | Openverse | `--sfx off --ambience off`, or put your own sounds in `~/.tripshots/sfx/library/` |
| Reel links (music, learn, clone, look) | The link, with your browser's Instagram cookies (only instagram.com's, in a temporary file deleted afterwards) if you pass `--cookies-from-browser` | Instagram, via yt-dlp | Use local files |
| Installing (`./install.sh`) | Search words for a starter set of sound effects | Openverse | Run it as `TRIPSHOTS_OFFLINE=1 ./install.sh` |
| Sending to Edits | The package files, copied into Edits' sandbox on your Mac; tool calls to Edits' local automation server | The Edits app on your computer (it posts to Instagram only when you post) | Don't use `tripshots edits` |
| Usage counts and crash reports (asked once, off until you say yes) | A random install id, app/OS version, chip, names of screens, commands and editor tools used, scrubbed crash notes ([below](#usage-counts-and-crash-reports-asked-once)) | The TripShots collector (Cloudflare) | Answer no, Settings → Privacy, `tripshots telemetry off`, or `DO_NOT_TRACK=1` |
| Model downloads | Nothing about you | GitHub / Hugging Face (face models), PyPI, npm | Download once; then works offline |

Things that **never** leave your computer: your video files, full-resolution photos, face detection and
recognition (faces, face embeddings and names stay in `~/.tripshots/`), beat tracking, colour grading, rendering,
the route map (drawn from map data downloaded once at setup), and the MCP server (unless you serve it over HTTP yourself).

## Usage counts and crash reports (asked once)

Release builds can send anonymous counts of what gets used and a note when something crashes, if you say yes. That helps the most-used parts improve and the worst bugs get fixed first. Your footage and anything you type are never part of it. The collector belongs to the TripShots maintainer and runs on Cloudflare ([telemetry.md](telemetry.md)).

### You are asked once

The first time the app opens, it asks. Nothing is sent before you answer, and nothing is sent if you say no. To
change your answer, go to **Settings → Privacy**. On the command line:

```
tripshots telemetry            # your answer and what is waiting
tripshots telemetry on|off
tripshots telemetry log        # what was sent, what is waiting, recent errors
tripshots telemetry reset      # a new anonymous id
```

These always stop all sending, whatever your answer: `DO_NOT_TRACK=1`, or `TRIPSHOTS_TELEMETRY=off` in your
environment or in `~/.tripshots/.env`. Builds made from the source code send nothing unless you set a collector
yourself.

### What is sent

- **A random id**, made on your computer. It isn't linked to you, your Apple ID or your Instagram account. **New
  anonymous id** in Settings replaces it, so what was sent before can't be linked to what comes next.
- **The app version**, the operating system and its version (for example `darwin 15.1`), and the chip (`arm64`).
- **Named events**, each with a few plain words or numbers:
  - `app_open`: the app was opened.
  - `view`: a screen was opened, for example `make` or `reel`.
  - `command`: a command ran, for example `make` or `render`. It includes whether it worked, roughly how long it
    took (1 s, 3 s, 10 s and so on, up to 1 h), whether the app, the command line or an AI agent started it, and the
    names of the options used (for example `music`, never the song).
  - `edit`: an editor tool was used, for example `split` or `trim`.
  - `feature`: a feature such as the MCP server was used.
- **Crashes**: the kind of error (for example `KeyError`), where in TripShots it happened (for example
  `tripshots/planedit.py:apply`), and the error message with paths, file names, e-mail addresses, links and long ids
  removed.

The collector also keeps the country Cloudflare reports for the connection. It never stores your IP address.

### What is never sent

- Your photos, clips, music, sound or reels, or pictures of them.
- File or folder names, paths, places, GPS positions or people.
- Anything you type: hooks, titles, captions, notes or style names.
- Your AI keys, your Instagram login or cookies.

The collector checks every event against the same short list and drops anything else before it is stored.

### See exactly what was sent

**Settings → Privacy → See what's sent** shows every batch, exactly as it was sent, newest first. The same log is at
`~/.tripshots/telemetry/sent.jsonl`. Events wait in `~/.tripshots/telemetry/queue.jsonl` until they're sent. The app
sends every 15 minutes, and the command line about every six hours.

### Report a problem

**Settings → Privacy → Report a problem** sends a note you write. You can add an e-mail address if you'd like an
answer. **Attach diagnostics** adds the versions and the last few errors and jobs, with names and paths removed.
**Show what's sent** shows the whole report before anything goes. A report needs no yes to anonymous counts, because
you press Send yourself. If it can't be sent, you can open it as a public GitHub issue instead.

### How long it is kept

Events are deleted after 13 months. Crash groups and bug reports are kept until they're dealt with. Download numbers
come from GitHub's own count of release downloads, and need nothing from you.

## Faces

Face recognition is local and opt-in: faces are only looked for when you add a person, search with `--people`, or run `people discover` / `people who`.
Embeddings (numbers describing a face, not images) are stored in `~/.tripshots/people/people.json`, and the faces found
in each file in `~/.tripshots/library/faces/`. `tripshots people forget <name>` removes a person; deleting those
folders removes everything. If you use TripShots on photos of other people, you are responsible for having their
consent where the law requires it.

## Agents

An agent connected through MCP can do what the tools allow: read your footage folders, see contact sheets and
storyboards, and write reels. What the agent then sends to its own AI provider is up to that agent and its
settings. Over HTTP, protect the server with `TRIPSHOTS_MCP_TOKEN` and keep it on a private network (see
[Security](../SECURITY.md)).
