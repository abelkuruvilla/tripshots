# Troubleshooting

Start with `tripshots doctor`: it checks ffmpeg and its filters, the AI backend, yt-dlp, the cut-out model, Gemini,
sound effects, the route-map runtime, HEIC support, the encoder, footage folders, people and MCP.

| Problem | Fix |
|---|---|
| "Claude Code isn't logged in" / `Not logged in · Please run /login` | Run `claude auth login` (or `claude`, then `/login`), then `tripshots doctor`: the `claude` line should say "logged in". Logging in to the Claude desktop app doesn't log in Claude Code. If doctor says logged in but runs still fail (Claude Code keeps its login in the macOS keychain, which a few setups can't reach), run `claude setup-token` and put the token in `~/.tripshots/.env` as `CLAUDE_CODE_OAUTH_TOKEN=…` |
| `claude CLI failed` / no AI backend | Install Claude Code and run `claude` once to log in, or set another backend ([AI backends](ai-backends.md)). `-b none` works without AI |
| HDR iPhone clips look grey | Your ffmpeg lacks `zscale`: install ffmpeg from Homebrew (`brew install ffmpeg`) |
| HEIC photos skipped | `pip install pillow-heif` (macOS can also convert with `sips`) |
| "only N usable shots" | Thin or rejected footage: add footage, `--allow-similar`, `--min-score 4`, or a shorter `-d` |
| The AI rejected every shot | It uses the best of them anyway and says so; check the storyboard |
| Reel links fail to download | Instagram needs your login: `--cookies-from-browser chrome` (or `TRIPSHOTS_COOKIES_BROWSER`); update yt-dlp (re-run `./install.sh`) |
| `place search failed` / no location titles | No network, or OpenStreetMap is unreachable. Use `--location "Place, Region"`; `find` still matches folder names |
| `find --place` finds nothing | Be specific ("Yellowstone National Park"); check `notes` for what it resolved to; many cameras record no GPS (try `--text`) |
| `find --people me` finds too little | Add 3–5 more varied photos of yourself; small or turned-away faces aren't recognised |
| Face models won't download | Put `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx` from OpenCV's model zoo in `~/.tripshots/models/` |
| Route map: "runtime not installed" | `./install.sh --maps` or `tripshots maps --setup` (needs Node.js 22+) |
| Sounds are "synthesized stand-ins" | `tripshots sounds --fetch` once (needs network), or add your own to `~/.tripshots/sfx/library/<role>/` |
| Rendering is slow | Check the log line `encoder: …`; on a Mac it should say VideoToolbox. `-j 4` renders more segments at once |
| 360° clips are skipped | On purpose: reframe them to flat video first (Insta360 Studio / GoPro Player) |
| MCP client can't start the server | Use the full path to `tripshots` in the client config (`which tripshots`) |
| MCP over HTTP returns 401 | Send `Authorization: Bearer $TRIPSHOTS_MCP_TOKEN` |
| An agent's job seems stuck | `job_status` shows its log; logs are in `~/.tripshots/jobs/`; `cancel_job` stops it |

Still stuck? Run the command with `-v` for debug output and open an issue with the log (remove personal paths).
