# Troubleshooting

Start with `tripshots doctor`: it checks ffmpeg and its filters, the AI backend, yt-dlp, the cut-out model, Gemini,
sound effects, the route-map runtime, HEIC support, the encoder, footage folders, people and MCP.

| Problem | Fix |
|---|---|
| "Claude Code isn't logged in" / `Not logged in · Please run /login` | Run `claude auth login` (or `claude`, then `/login`), then `tripshots doctor`: the `claude` line should say "logged in". Logging in to the Claude desktop app doesn't log in Claude Code. If doctor says logged in but runs still fail (Claude Code keeps its login in the macOS keychain, which a few setups can't reach), run `claude setup-token` and put the token in `~/.tripshots/.env` as `CLAUDE_CODE_OAUTH_TOKEN=…` |
| `claude CLI failed` / no AI backend | Install Claude Code and run `claude` once to log in, or set another backend ([AI backends](ai-backends.md)). `-b none` works without AI |
| HDR iPhone clips look grey or flat | `tripshots doctor` → the **HDR** line. Without `zscale` (Homebrew's standard `ffmpeg` no longer has it) TripShots uses built-in tables with `lut3d` and gets the same colours; update TripShots if you see the old "lacks zscale" warning. `brew install ffmpeg-full` adds zscale, but isn't needed |
| HEIC photos skipped | `pip install pillow-heif` (macOS can also convert with `sips`) |
| "only N usable shots" | Thin or rejected footage: add footage, `--allow-similar`, `--min-score 4`, or a shorter `-d` |
| The AI rejected every shot | It uses the best of them anyway and says so; check the storyboard |
| Reel links fail to download | Instagram needs your login: `--cookies-from-browser chrome` (or `TRIPSHOTS_COOKIES_BROWSER`); update yt-dlp (re-run `./install.sh`) |
| `place search failed` / no location titles | No network, or OpenStreetMap is unreachable. Use `--location "Place, Region"`; `find` still matches folder names |
| `find --place` finds nothing | Be specific ("Yellowstone National Park"); check `notes` for what it resolved to; many cameras record no GPS (try `--text`) |
| `find --people me` finds too little | Add 3–5 more varied photos of yourself; small or turned-away faces aren't recognised |
| `watch failed … models/gemini-flash-latest is not found` | Fixed in newer TripShots: it asks Google which models your key can use, switches to an available Flash model on a "not found", and stops Gemini for the run (falling back to local analysis) when none works. To pick one yourself: `TRIPSHOTS_GEMINI_MODEL=gemini-2.5-flash` |
| `watch failed … 429 RESOURCE_EXHAUSTED` | Gemini's rate limit or quota. Newer TripShots paces its requests (`TRIPSHOTS_GEMINI_RPM`, 10 a minute by default), waits the time Gemini asks for when it hits the per-minute limit and then goes slower, and moves to another model when one model's daily quota is used up. When the daily quota is used up on every model, it stops Gemini for the run with one message; clips already watched are kept, and running again after the reset (midnight Pacific time) watches the rest. A paid key has much higher limits |
| Face models won't download | Put `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx` from OpenCV's model zoo in `~/.tripshots/models/` |
| Route map: "runtime not installed" | `./install.sh --maps` or `tripshots maps --setup` (needs Node.js 22+) |
| Sounds are "synthesized stand-ins" | `tripshots sounds --fetch` once (needs network), or add your own to `~/.tripshots/sfx/library/<role>/` |
| Rendering is slow | Check the log line `encoder: …`; on a Mac it should say VideoToolbox. `-j 4` renders more segments at once |
| 360° clips are skipped | On purpose: reframe them to flat video first (Insta360 Studio / GoPro Player) |
| MCP client can't start the server | Use the full path to `tripshots` in the client config (`which tripshots`) |
| MCP over HTTP returns 401 | Send `Authorization: Bearer $TRIPSHOTS_MCP_TOKEN` |
| An agent's job seems stuck | `job_status` shows its log; logs are in `~/.tripshots/jobs/`; `cancel_job` stops it |

Still stuck? Run the command with `-v` for debug output and open an issue with the log (remove personal paths).
