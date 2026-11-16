// The TripShots collector: a Cloudflare Worker with a D1 database.
//   POST /v1/events   batches of anonymous events and crashes (only from apps whose user said yes)
//   POST /v1/report   a bug report the user wrote and chose to send
//   GET  /dashboard   the private dashboard (HTTP basic auth: any user name, DASHBOARD_PASSWORD)
//   GET  /dashboard.json   the same numbers as JSON
// Once a day (cron) it records GitHub release download counts and deletes events older than KEEP_DAYS.
// IP addresses are never stored; only the country Cloudflare reports for the request.
import { cleanEvent, cleanReport, day, LIMITS } from "./validate.js";
import { dashboard, numbers } from "./dashboard.js";

const MAX_BODY = 256 * 1024;

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      if (req.method === "POST" && url.pathname === "/v1/events") return await events(req, env);
      if (req.method === "POST" && url.pathname === "/v1/report") return await report(req, env);
      if (url.pathname === "/dashboard" || url.pathname === "/dashboard.json" || url.pathname.startsWith("/dashboard/")) {
        if (!authed(req, env)) {
          return new Response("TripShots dashboard", { status: 401, headers: { "WWW-Authenticate": 'Basic realm="TripShots"' } });
        }
        if (req.method === "POST") return await mark(req, env, url);
        const range = Math.min(365, Math.max(7, parseInt(url.searchParams.get("days") || "30", 10) || 30));
        const n = await numbers(env, range);
        if (url.pathname === "/dashboard.json") return json(n);
        return new Response(dashboard(n), {
          headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex",
                     "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'" },
        });
      }
      if (url.pathname === "/") return new Response("TripShots collector\n", { headers: { "Content-Type": "text/plain" } });
      return json({ error: "not found" }, 404);
    } catch (e) {
      return json({ error: "server error" }, 500);
    }
  },

  async scheduled(_event, env) {
    await snapshotDownloads(env).catch(() => {});
    const keep = parseInt(env.KEEP_DAYS || "395", 10);
    const cut = day(Date.now() / 1000 - keep * 86400);
    await env.DB.batch([
      env.DB.prepare("DELETE FROM events WHERE day < ?").bind(cut),
      env.DB.prepare("DELETE FROM crash_hits WHERE day < ?").bind(cut),
      env.DB.prepare("DELETE FROM limits WHERE day < ?").bind(day(Date.now() / 1000 - 3 * 86400)),
    ]);
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}

async function body(req) {
  const n = parseInt(req.headers.get("Content-Length") || "0", 10);
  if (n > MAX_BODY) return null;
  const text = await req.text();
  if (text.length > MAX_BODY) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function country(req) {
  const c = req.cf?.country || req.headers.get("CF-IPCountry") || "";
  return /^[A-Z]{2}$/.test(c) ? c : "";
}

// how many more of this kind this install may send today
async function allowance(env, install, d, kind, want) {
  const row = await env.DB.prepare(
    "INSERT INTO limits (install, day, kind, n) VALUES (?, ?, ?, ?) ON CONFLICT (install, day, kind) DO UPDATE SET n = n + excluded.n RETURNING n",
  ).bind(install, d, kind, want).first();
  const used = (row?.n ?? want) - want;
  return Math.max(0, Math.min(want, LIMITS[kind] - used));
}

async function events(req, env) {
  const b = await body(req);
  if (!b || !Array.isArray(b.events)) return json({ error: "bad batch" }, 400);
  const cc = country(req);
  const clean = b.events.slice(0, 500).map((e) => cleanEvent(e)).filter(Boolean);
  // group by install and kind so each gets its own daily allowance
  const groups = new Map();
  for (const e of clean) {
    const k = `${e.install}|${e.day}|${e.name === "crash" ? "crash" : "events"}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(e);
  }
  const stmts = [];
  let kept = 0;
  for (const [k, list] of groups) {
    const [install, d, kind] = k.split("|");
    const ok = list.slice(0, await allowance(env, install, d, kind, list.length));
    for (const e of ok) {
      kept++;
      stmts.push(installStmt(env, e, cc));
      if (e.name === "crash") {
        const c = e.crash;
        stmts.push(env.DB.prepare(
          `INSERT INTO crashes (fingerprint, kind, type, message, place, frames, handled, first_day, last_day, first_v, last_v, count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
           ON CONFLICT (fingerprint) DO UPDATE SET count = count + 1, last_day = max(last_day, excluded.last_day),
             last_v = excluded.last_v, message = excluded.message, frames = excluded.frames,
             status = CASE WHEN status = 'fixed' AND excluded.last_v != first_v THEN 'back' ELSE status END`,
        ).bind(c.fingerprint, c.kind, c.type, c.message, c.place, JSON.stringify(c.frames), c.handled ? 1 : 0,
               e.day, e.day, e.v, e.v));
        stmts.push(env.DB.prepare("INSERT INTO crash_hits (fingerprint, day, install, v) VALUES (?, ?, ?, ?)")
          .bind(c.fingerprint, e.day, e.install, e.v));
        stmts.push(eventStmt(env, { ...e, props: { kind: c.kind, handled: c.handled, fingerprint: c.fingerprint } }, cc));
      } else {
        stmts.push(eventStmt(env, e, cc));
      }
    }
  }
  for (let i = 0; i < stmts.length; i += 90) await env.DB.batch(stmts.slice(i, i + 90));
  return json({ ok: true, kept, dropped: b.events.length - kept }, 202);
}

function eventStmt(env, e, cc) {
  return env.DB.prepare(
    "INSERT INTO events (day, ts, install, session, name, props, v, os, osv, arch, country) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
  ).bind(e.day, e.ts, e.install, e.session, e.name, JSON.stringify(e.props || {}), e.v, e.os, e.osv, e.arch, cc);
}

function installStmt(env, e, cc) {
  const open = e.name === "app_open" ? 1 : 0;
  return env.DB.prepare(
    `INSERT INTO installs (install, first_day, last_day, v, os, osv, arch, country, opens, events) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
     ON CONFLICT (install) DO UPDATE SET first_day = min(first_day, excluded.first_day), last_day = max(last_day, excluded.last_day),
       v = CASE WHEN excluded.last_day >= last_day THEN excluded.v ELSE v END, os = excluded.os, osv = excluded.osv,
       arch = excluded.arch, country = CASE WHEN excluded.country != '' THEN excluded.country ELSE country END,
       opens = opens + excluded.opens, events = events + 1`,
  ).bind(e.install, e.day, e.day, e.v, e.os, e.osv, e.arch, cc, open);
}

async function report(req, env) {
  const r = cleanReport(await body(req));
  if (!r) return json({ error: "write what went wrong" }, 400);
  const d = day(Date.now() / 1000);
  if (r.install && !(await allowance(env, r.install, d, "report", 1))) return json({ error: "too many reports today" }, 429);
  await env.DB.prepare(
    "INSERT INTO reports (ts, install, v, message, email, diagnostics, country) VALUES (?, ?, ?, ?, ?, ?, ?)",
  ).bind(Math.floor(Date.now() / 1000), r.install, r.v, r.message, r.email, r.diagnostics, country(req)).run();
  return json({ ok: true }, 202);
}

function authed(req, env) {
  const pw = env.DASHBOARD_PASSWORD;
  const h = req.headers.get("Authorization") || "";
  if (!pw || !h.startsWith("Basic ")) return false;
  let got = "";
  try {
    got = atob(h.slice(6)).split(":").slice(1).join(":");
  } catch {
    return false;
  }
  if (got.length !== pw.length) return false;
  let diff = 0;
  for (let i = 0; i < pw.length; i++) diff |= got.charCodeAt(i) ^ pw.charCodeAt(i);
  return diff === 0;
}

// the dashboard's buttons: a crash group fixed / ignored, a report done
async function mark(req, env, url) {
  const form = await req.formData();
  const status = String(form.get("status") || "");
  let m = url.pathname.match(/^\/dashboard\/crash\/([0-9a-f]{8,40})$/);
  if (m && ["open", "fixed", "ignored"].includes(status)) {
    await env.DB.prepare("UPDATE crashes SET status = ? WHERE fingerprint = ?").bind(status, m[1]).run();
  }
  m = url.pathname.match(/^\/dashboard\/report\/(\d+)$/);
  if (m && ["new", "done"].includes(status)) {
    await env.DB.prepare("UPDATE reports SET status = ? WHERE id = ?").bind(status, parseInt(m[1], 10)).run();
  }
  return Response.redirect(new URL("/dashboard", url).toString(), 303);
}

// GitHub counts every download of every release file; that needs no consent from anyone
async function snapshotDownloads(env) {
  if (!env.GITHUB_REPO) return;
  const headers = { "User-Agent": "tripshots-telemetry", Accept: "application/vnd.github+json" };
  if (env.GITHUB_TOKEN) headers.Authorization = `Bearer ${env.GITHUB_TOKEN}`;
  const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/releases?per_page=100`, { headers });
  if (!res.ok) return;
  const d = day(Date.now() / 1000);
  const stmts = [];
  for (const rel of await res.json()) {
    for (const a of rel.assets || []) {
      stmts.push(env.DB.prepare(
        "INSERT INTO downloads (day, tag, asset, count) VALUES (?, ?, ?, ?) ON CONFLICT (day, tag, asset) DO UPDATE SET count = excluded.count",
      ).bind(d, rel.tag_name, a.name, a.download_count));
    }
  }
  for (let i = 0; i < stmts.length; i += 90) await env.DB.batch(stmts.slice(i, i + 90));
}
