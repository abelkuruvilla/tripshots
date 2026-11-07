# Security

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use GitHub's private vulnerability reporting
(*Security → Report a vulnerability*) on this repository. Include what you found, how to reproduce it, and the
version (`pip show tripshots`). You'll get a reply within a week.

## What to keep in mind

TripShots works with private data: your photos and videos, GPS history, faces, API keys and browser cookies.

- **API keys** live in `~/.tripshots/.env`. Keep that file private (`chmod 600`); never commit it.
- **Instagram cookies** are read from your browser by yt-dlp only when you pass `--cookies-from-browser` or set
  `TRIPSHOTS_COOKIES_BROWSER`, and only to download the reels you name.
- **The MCP server over stdio** runs as you and can read your footage folders and write reels. Only connect agents
  you trust.
- **The MCP server over HTTP** (`tripshots mcp --http`) refuses to listen beyond localhost without
  `TRIPSHOTS_MCP_TOKEN`, compares the token in constant time, and has no TLS. Use a long random token, keep it on a
  private network (LAN, Tailscale/WireGuard) or behind an HTTPS reverse proxy, and never expose it to the internet.
- **Agent requests are untrusted input.** File paths and text from agents go to the CLI as arguments, never through a
  shell. Plan tools only accept `.plan.json` files; reels are written under the reels folder (which an agent can
  change with `set_folders`) and working files under `~/.tripshots/`.
- **Downloaded models are pinned.** Face models are checked against fixed SHA-256 hashes; route-map packages are
  pinned to exact versions.

See [docs/privacy.md](docs/privacy.md) for everything that is sent to outside services.
