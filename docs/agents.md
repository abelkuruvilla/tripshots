# AI agents

TripShots is built to be driven by an AI agent as well as by hand. Ask in plain words:

> "Create a reel highlighting all the pictures I'm in"
> "Make a reel about my days in Yellowstone"
> "15 seconds of Lisbon with mom, something calm"

and the agent finds the footage, plans the reel, looks at the storyboard, fixes weak shots and renders it. There are
three ways to connect one.

## 1. MCP server (any MCP agent)

`tripshots mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server. It works with Claude Code,
Claude Desktop, OpenClaw, Cursor and anything else that speaks MCP.

**Claude Code**

```bash
claude mcp add tripshots -- tripshots mcp
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on a Mac):

```json
{
  "mcpServers": {
    "tripshots": { "command": "/Users/you/.local/bin/tripshots", "args": ["mcp"] }
  }
}
```

Use the full path to `tripshots` (`which tripshots`), because desktop apps don't see your shell's `PATH`.

**Remote agents over HTTP** (an agent running on another machine, e.g. a home server):

```bash
export TRIPSHOTS_MCP_TOKEN="$(openssl rand -hex 32)"
tripshots mcp --http 0.0.0.0:8765
```

Connect the agent to `http://<host>:8765/mcp` with the header `Authorization: Bearer <token>`. Every request
without the token gets `401`. TripShots refuses to listen beyond `localhost` without a token. There is no TLS: keep
it on your LAN or a private network such as Tailscale, or put it behind a reverse proxy with HTTPS. The agent can
read your footage folders and write reels, so treat the token like a password.

### What the agent gets

The full list with parameters is in [MCP tools](mcp-tools.md). In short:

| Step | Tools |
|---|---|
| Setup | `status`, `set_footage_folders`, `set_folders` |
| Find footage | `list_trips`, `find_footage`, `view_selection`, `analyze_footage`, `search_media` ([analysis](analysis.md)) |
| People | `people_list`, `people_add`, `people_discover`, `people_name` |
| Plan | `list_music`, `list_styles_and_looks`, `make_reel` (dry run by default) |
| Review and fix | `show_plan`, `shot_candidates`, `edit_plan` |
| Finish | `render_reel`, `export_edit`, `edits_package`, `edits_status`, `edits_push` ([Edits](edits.md)) |
| Jobs | `job_status`, `cancel_job` |

- **Images in results.** `find_footage`, `make_reel`, `shot_candidates`, `edit_plan` and `people_discover` return
  their contact sheets and storyboards as images, so the agent can see what it chose.
- **Long steps are jobs.** Analysing footage, finding faces and rendering can take minutes. Those tools start a
  background process, wait a while (about 50 s; `render_reel` 20 s), and otherwise return a job id for `job_status`. Jobs keep running
  if the agent disconnects; their logs are in `~/.tripshots/jobs/`.
- **Safe edits.** `edit_plan` changes a plan without breaking its beat grid: swap the shot in a slot, move or
  exchange slots, set the hook, location or closing text, change a transition, speed or framing.
- **Server instructions** tell the agent the workflow (status → find → check → plan → review → fix → render) and
  the house rules (hooks of 7 words or fewer, make the creative calls, check the storyboard). You can read them in
  [MCP tools](mcp-tools.md#server-instructions).
- The `reel_from_request` prompt wraps a request in the same workflow, for clients that show MCP prompts.

## 2. Agent skill (agents with a shell)

[`skills/tripshots/SKILL.md`](../skills/tripshots/SKILL.md) is a portable agent skill: how to turn a request into
a search, which checks to do, how to plan, fix and render. It covers both the MCP tools and the CLI, so an agent with
only a shell can use it (every command prints JSON). Copy the folder into your agent's skills folder:

- Claude Code: `~/.claude/skills/tripshots/` (all projects) or `.claude/skills/tripshots/` in a project
- Claude (claude.ai): upload the folder as a skill
- OpenClaw and other `SKILL.md` readers: their skills folder

Working inside this repository with Claude Code, the `make-reel` skill in `.claude/skills/` and `CLAUDE.md` are
loaded automatically.

### Companion skills

`tripshots skills` lists agent skills that work well next to TripShots, says which are installed and how to install
them (`tripshots skills --install NAME` runs `npx skills add`):

| Skill | What it adds for an agent | Licence |
|---|---|---|
| [HyperFrames](https://github.com/heygen-com/hyperframes) | HTML-to-video and ~450 registry blocks (titles, captions, transitions, maps). TripShots already renders its maps and motion text with it; the skill lets an agent build custom title or end cards | Apache-2.0 |
| [Remotion](https://www.remotion.dev/docs/ai/skills) | React-based video, for an agent building its own intro or animations | free for individuals and small teams; companies need a licence |
| [one-take](https://github.com/KaranO-Dev/one-take-skill) | promo videos on HyperFrames with a strict QA pass (TripShots' `qa` follows it) | MIT |
| [Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar) | short films drawn in code in 43 styles, with a director's guide (TripShots' `DIRECTOR.md` follows its pattern) | MIT |

TripShots never needs any of them to run.

## 3. `tripshots ask` (no agent)

```bash
tripshots ask "a reel about my days in Yellowstone"            # finds the footage, plans the reel
tripshots ask "all the pictures I'm in" -m song.mp3 --render   # and renders it
tripshots ask "last summer's beach days" --find-only           # just the search + contact sheet
```

`ask` uses your configured [AI backend](ai-backends.md) for one thing: turning the sentence into a search (place,
dates, people, photo/video) and edit settings (style, length, hook, music from `TRIPSHOTS_MUSIC`). It sends the
request, today's date, your known people's names and aliases, your trips (dates, GPS centres, folder names), the style
names and the file names (not paths) of your music. When the request can't be resolved (for example it mentions someone TripShots doesn't know
yet) it asks one question back instead of guessing. The app's **Ask** tab does the same.

## Tips for good results

- Name places specifically: "Yellowstone National Park", not "Yellowstone" (which is also a river and a county).
- Teach it your face with 3–5 different photos before asking for "pictures I'm in".
- Under about 8 files makes a thin reel; agents are told to widen the search and say so.
- Without music the reel is silent at 100 BPM. Set `TRIPSHOTS_MUSIC` to a folder of tracks so agents can choose one.
