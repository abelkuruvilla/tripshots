# The desktop app

TripShots for macOS, Windows and Linux: your reels in a gallery, a player with the caption and the sound to add,
a timeline where you swap any shot, new reels from folders and a reel link, Ask, learning styles, and settings.
The app itself is small (a system web view, no bundled browser); the engine that analyses footage and renders
reels is downloaded once on first launch and updates on its own.

## Install

Download the installer for your computer from the latest release:

| | File |
|---|---|
| Mac (Apple Silicon) | `TripShots_<version>_aarch64.dmg` |
| Windows | `TripShots_<version>_x64-setup.exe` or `.msi` |
| Linux | `.deb`, `.rpm` or `.AppImage` |

Intel Macs aren't supported: libraries the engine needs (numba, onnxruntime) no longer ship for them.

On first launch, **Download the engine** fetches it (about 200 MB; it is checked against TripShots' signature before
it's used). On a Mac, install ffmpeg once with `brew install ffmpeg`; the Windows and Linux engines include it.

## What's where

- **Reels**: every reel in your reels folder and `~/.tripshots/reels`, newest first, grouped by folder.
- **A reel**: play it, copy or edit the caption, see the sound to add in Instagram (and open the reel it comes
  from), the words on screen, and the timeline. Click a shot to jump to it; **Swap** shows the best shots of the
  same footage and replaces that slot without moving the cuts. **Re-render** makes the new version.
- **New reel**: footage folders or files, a sound (a reel link, so its cut and sound are used, or an audio file),
  a style, the shape (automatic, upright, wide), up to four versions to compare, an optional opening line, and
  **Plan only** for a storyboard in about a minute.
- **Ask**: say what you want ("a reel about my days in Yellowstone"); TripShots finds the footage and makes it.
- **Styles**: learn a style from reel links (each becomes a recipe), or add examples to one.
- **Activity**: everything being made, rendered or learned, with its log. Jobs started from the command line or by
  an AI agent show up here too, and reels they make appear in the gallery.
- **Settings > AI**: which AI makes the creative calls (Automatic, Claude, MiniMax, Claude API, None) and, for
  each one, the steps to set it up with links and a **Test** button: Claude Code is installed and logged in from a
  Terminal window the app opens (`claude auth login`, your Pro/Max plan, no key), MiniMax and the Claude API take a
  key from their sites, and Gemini (optional, a free key from Google AI Studio) watches clips. The gallery says so
  when no AI is set up.
- **Settings**: footage, reels and music folders; the browser to borrow your Instagram login from;
  **Command line** (puts `tripshots` on your PATH) and **Claude** (adds TripShots to Claude Desktop's MCP servers
  and gives the `claude mcp add` line for Claude Code); app and engine updates.

## The command line and agents

The app's engine is the full `tripshots` program. After Settings > Command line > Install, every command in
[Commands](cli.md) works in a terminal, and `tripshots mcp` serves the [MCP tools](mcp-tools.md). The app, the
command line and agents share `~/.tripshots` (library, styles, memory of earlier reels).

## For developers

Building, the engine API, releases and signing: [desktop/README.md](../desktop/README.md).
