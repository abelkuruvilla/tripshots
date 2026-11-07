# Privacy

TripShots runs on your computer. Your footage is read where it is and never uploaded by TripShots itself; finished
reels are written to your disk. Some features do talk to outside services. This page lists every one, so you can
decide what to turn on.

| Feature | Sends | To | Turn it off |
|---|---|---|---|
| AI shot judging, colour notes, hooks, captions, labels | Small JPEG stills and contact sheets of your shots (not the video files), technical numbers (length, fps, brightness, shake), place names | Your chosen backend: Anthropic (Claude Code / API) or MiniMax | `--backend none` / `TRIPSHOTS_BACKEND=none` |
| `tripshots ask` / the app's Ask tab | Your request, today's date, the names and aliases of people you've taught it, your trips (dates, GPS centre points, folder names), style names, the file names (not paths) of tracks in `TRIPSHOTS_MUSIC` | Your chosen backend | Don't use `ask`; use `find` + `make` |
| Gemini video watching (optional) | A 480p, 15 fps proxy of each clip with its sound, deleted from Google right after | Google Gemini API | Leave `GEMINI_API_KEY` unset, or `--watch off` |
| Place names (location titles, trips) | GPS coordinates rounded to about 100 m–2 km | OpenStreetMap Nominatim | `--no-location`, `trips --no-names`, or `TRIPSHOTS_OFFLINE=1` |
| Place search (`find --place`) | The place name you typed | OpenStreetMap Nominatim | Use `--near` or `--text`, or `TRIPSHOTS_OFFLINE=1` |
| Sound effects | Search words such as "whoosh" or "ocean waves" | Openverse | `--sfx off --ambience off`, or put your own sounds in `~/.tripshots/sfx/library/` |
| Reel links (music, learn, clone, look) | The link, with your browser's Instagram cookies if you pass `--cookies-from-browser` | Instagram, via yt-dlp | Use local files |
| Installing (`./install.sh`) | Search words for a starter set of sound effects | Openverse | Run it as `TRIPSHOTS_OFFLINE=1 ./install.sh` |
| Model downloads | Nothing about you | GitHub / Hugging Face (face models), PyPI, npm | Download once; then works offline |

Things that **never** leave your computer: your video files, full-resolution photos, face detection and
recognition (faces, face embeddings and names stay in `~/.tripshots/`), beat tracking, colour grading, rendering,
the route map (drawn from map data downloaded once at setup), and the MCP server (unless you serve it over HTTP yourself).

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
