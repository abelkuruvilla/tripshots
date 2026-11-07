# Getting started

## Requirements

| | |
|---|---|
| Python | 3.10 or newer (tested on 3.11–3.13) |
| ffmpeg | 6 or newer, with `zscale` for HDR footage (`tripshots doctor` checks) |
| An AI backend | optional but recommended: [Claude Code](https://docs.claude.com/en/docs/claude-code) logged in with a Claude subscription, a MiniMax key, or an Anthropic API key ([AI backends](ai-backends.md)) |
| Node.js 22+ | only for animated route maps |
| OS | macOS is the main target (Apple Silicon and Intel). Linux works (CI runs on Ubuntu). Windows is untested. |

## Install

**macOS (recommended):**

```bash
git clone <this repository> tripshots
cd tripshots
./install.sh                 # Homebrew ffmpeg + yt-dlp + Python 3.12, TripShots in ~/.tripshots/venv
./install.sh --maps          # optional: route maps (Node.js + HyperFrames, ~100 MB)
./install.sh --sound         # optional: earshot's offline sound bank
```

`install.sh` puts TripShots in its own virtual environment and links `tripshots` into `~/.local/bin`. Re-run it to update.

**Linux / any platform with pip:**

```bash
sudo apt install ffmpeg      # or your platform's ffmpeg 6+
git clone <this repository> tripshots && cd tripshots
python -m venv ~/.tripshots/venv && . ~/.tripshots/venv/bin/activate
pip install ".[heic,cutout,watch,export]"
```

The extras are optional: `heic` (iPhone HEIC photos), `cutout` (pop-out frames, ~170 MB model on first use), `watch` (Gemini video watching), `export` (OpenTimelineIO export). `dev` adds the test tools.

Then check everything:

```bash
tripshots doctor
```

## Your first reel

```bash
tripshots make ~/Pictures/Banff -m ~/Music/song.mp3 --dry-run   # plan only: fast
```

Open the `.storyboard.jpg` it prints. Every shot is shown in order with its timing and colour. If it looks right:

```bash
tripshots render reels/Banff-beat-montage-<time>.plan.json
```

You get the `.mp4` (1080×1920, 30 fps), a cover, a caption and the files described in [Making reels](making-reels.md#what-you-get-per-reel). Or do all of it in one go without `--dry-run`, or in the app: run `tripshots`.

## Search instead of folders

Tell TripShots where your footage lives once, then ask for footage by place, dates or people:

```bash
tripshots footage ~/Pictures/Trips /Volumes/SSD/Footage
tripshots trips                                              # what trips it sees
tripshots find --place "Yellowstone National Park" --sheet  # -> sel:1a2b3c4d
tripshots make sel:1a2b3c4d -m song.mp3
```

For "the pictures I'm in", teach it your face once: `tripshots people add me selfie1.jpg selfie2.jpg selfie3.jpg`. See [Finding footage](finding-footage.md).

## Let an AI do it

```bash
tripshots ask "a reel about my days in Yellowstone"          # uses your AI backend to understand the request
claude mcp add tripshots -- tripshots mcp                    # or give Claude Code (or any MCP agent) the tools
```

Then ask your agent: *"Make a reel of all the pictures I'm in from last summer."* See [AI agents](agents.md).
