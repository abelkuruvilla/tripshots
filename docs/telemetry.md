# Usage numbers and crash reports: the collector

Release builds of TripShots send anonymous usage counts, crash reports and bug reports, from people who said yes,
to a collector you run yourself. [privacy.md](privacy.md) is what users are told. This page covers setting the
collector up and reading its dashboard.

## The parts

| Part | Where | What it does |
|---|---|---|
| Engine | `tripshots/telemetry.py` | Consent, the random install id, the queue, scrubbing crashes, sending (standard library only) |
| CLI | `cli._run` | One `command` event per run (name, ok, rough time, option names), crashes |
| App server | `server.py` `/api/telemetry`, `/api/report` | The window's events and crashes; sends every 15 minutes |
| Desktop window | `desktop/src/lib/telemetry.js`, `views/Consent.svelte`, `views/Privacy.svelte` | Screens, editor tools, JavaScript errors; the question; Settings → Privacy |
| Desktop shell | `src-tauri/src/lib.rs` `note_crash` | Panics and engines that won't start, left in `~/.tripshots/telemetry/pending` for the engine to send |
| Collector | `telemetry/worker` | A Cloudflare Worker with a D1 database: takes events, checks them again, keeps them, shows the dashboard |

Download counts need none of this. GitHub counts every release file download, and the collector copies those counts
once a day. `latest.json` downloads are the app's update checks, so they count every copy in use, whatever its
owner answered.

Uninstalls can't be counted: macOS doesn't tell an app it was removed. The dashboard's **Gone quiet** (not seen for
30 days) stands in for them.

## Set it up (once, about 10 minutes)

You need a Cloudflare account; the free plan is enough. Run these from `telemetry/worker`, on Node 22:

```
npx wrangler login
npx wrangler d1 create tripshots                # copy the database_id it prints into wrangler.toml
npx wrangler d1 execute tripshots --remote --file schema.sql
npx wrangler secret put DASHBOARD_PASSWORD     # the dashboard's password
npx wrangler secret put GITHUB_TOKEN           # only if the repository is private (read-only, Contents)
npx wrangler deploy                            # prints https://tripshots-telemetry.<you>.workers.dev
```

Then tell the release builds where it is. On GitHub, go to **Settings → Secrets and variables → Actions →
Variables** and add `TELEMETRY_URL` with that address. The release workflow stamps it into the engine
(`tools/set_version.py --telemetry`). Builds without it send nothing.

To try it before a release, put `TRIPSHOTS_TELEMETRY_URL=https://…workers.dev` in `~/.tripshots/.env`. The app then
asks the question on its next start.

## The dashboard

Open `https://…workers.dev/dashboard`. Your browser asks for a user name and password: any user name, and the
`DASHBOARD_PASSWORD` you set. `/dashboard.json` has the same numbers as JSON.

- **Tiles:**
  - downloads (installer files);
  - installs seen;
  - active today, this week and in 30 days;
  - app opens;
  - **kept using it** (still active a week after their first day);
  - gone quiet;
  - crash-free sessions;
  - update checks.
- **Daily charts:** people using it, new installs, and installer downloads.
- **Tables:**
  - commands (runs, people, failures, typical time);
  - who started them (app, command line, agent);
  - screens, editor tools and features;
  - versions, systems, chips and countries;
  - downloads by kind and by release.
- **Crashes:**
  - errors are grouped by kind and by where they happened, across versions;
  - each group shows how many times it happened, to how many people, and from which version to which;
  - **Fixed** marks a group fixed. If it happens again in a newer version, it comes back as `back`. **Ignore** hides
    it.
- **Bug reports:** what people wrote, their e-mail address if they gave one, and diagnostics. **Done** files a report
  away.

## Limits and keeping

The collector checks every event against the same list as the engine (`telemetry/worker/src/validate.js`). Each
install can send at most 3,000 events, 60 crashes and 5 reports a day. Raw events are deleted after `KEEP_DAYS`
(395 by default). Installs, crash groups and reports stay.

## Tests

```
pytest tests/test_telemetry.py
cd telemetry/worker && node --test test/*.test.js   # node:sqlite stands in for D1
```

## Adding an event

1. Add it, with its properties, to `EVENTS` in both `tripshots/telemetry.py` and `telemetry/worker/src/validate.js`.
2. Add it to [privacy.md](privacy.md).

Property values can only be short plain words, numbers or yes/no. Paths and free text are dropped on both sides.
