// The private dashboard: the numbers (numbers) and one server-drawn page (dashboard). No scripts, no outside files.
import { day } from "./validate.js";

const all = async (env, sql, ...args) => (await env.DB.prepare(sql).bind(...args).all()).results || [];
const one = async (env, sql, ...args) => (await env.DB.prepare(sql).bind(...args).first()) || {};
const ago = (n) => day(Date.now() / 1000 - n * 86400);

// what a release file is, from its name
export function assetKind(name) {
  const n = name.toLowerCase();
  if (n === "latest.json") return "update checks";
  if (n === "engine.json") return "engine checks";
  if (/\.(sig|minisig|sha256|asc)$/.test(n)) return null;
  if (/\.app\.tar\.gz$|\.nsis\.zip$|\.appimage\.tar\.gz$/.test(n)) return "app updates";
  if (n.includes("engine")) return "engine downloads";
  if (n.endsWith(".dmg")) return "macOS";
  if (/\.(msi|exe)$/.test(n)) return "Windows";
  if (/\.(appimage|deb|rpm)$/.test(n)) return "Linux";
  return "other";
}

export async function numbers(env, range) {
  const since = ago(range - 1);
  const today = ago(0);
  const [installs, active1, active7, active30, quiet, opens, sessions, crashSessions] = await Promise.all([
    one(env, "SELECT COUNT(*) n FROM installs"),
    one(env, "SELECT COUNT(*) n FROM installs WHERE last_day >= ?", today),
    one(env, "SELECT COUNT(*) n FROM installs WHERE last_day >= ?", ago(6)),
    one(env, "SELECT COUNT(*) n FROM installs WHERE last_day >= ?", ago(29)),
    one(env, "SELECT COUNT(*) n FROM installs WHERE last_day < ?", ago(30)),
    one(env, "SELECT COUNT(*) n FROM events WHERE name = 'app_open' AND day >= ?", since),
    one(env, "SELECT COUNT(DISTINCT session) n FROM events WHERE day >= ? AND session != ''", since),
    one(env, "SELECT COUNT(DISTINCT session) n FROM events WHERE day >= ? AND name = 'crash' AND json_extract(props, '$.handled') = 0", since),
  ]);
  const [daily, newDaily, quietMonthly, retained] = await Promise.all([
    all(env, "SELECT day, COUNT(DISTINCT install) n FROM events WHERE day >= ? GROUP BY day ORDER BY day", since),
    all(env, "SELECT first_day day, COUNT(*) n FROM installs WHERE first_day >= ? GROUP BY first_day ORDER BY first_day", since),
    all(env, "SELECT substr(last_day, 1, 7) month, COUNT(*) n FROM installs WHERE last_day < ? GROUP BY month ORDER BY month DESC LIMIT 12", ago(30)),
    one(env, `SELECT COUNT(*) total, SUM(CASE WHEN julianday(last_day) - julianday(first_day) >= 7 THEN 1 ELSE 0 END) kept
              FROM installs WHERE first_day BETWEEN ? AND ?`, ago(90), ago(8)),
  ]);
  const by = (col) => all(env, `SELECT ${col} k, COUNT(*) n FROM installs WHERE last_day >= ? GROUP BY k ORDER BY n DESC LIMIT 12`, ago(29));
  const [versions, oses, archs, countries] = await Promise.all([by("v"), by("os || ' ' || osv"), by("arch"), by("country")]);
  const prop = (name, key, extra = "") => all(env,
    `SELECT json_extract(props, '$.${key}') k, COUNT(*) n, COUNT(DISTINCT install) people${extra}
     FROM events WHERE name = ? AND day >= ? GROUP BY k ORDER BY n DESC LIMIT 25`, name, since);
  const [commands, views, edits, features, via] = await Promise.all([
    prop("command", "cmd", ", SUM(CASE WHEN json_extract(props, '$.ok') = 0 THEN 1 ELSE 0 END) failed, " +
         "CAST(AVG(json_extract(props, '$.secs')) AS INTEGER) secs"),
    prop("view", "view"), prop("edit", "op"), prop("feature", "name"), prop("command", "via"),
  ]);
  const crashes = await all(env,
    `SELECT c.*, (SELECT COUNT(DISTINCT install) FROM crash_hits h WHERE h.fingerprint = c.fingerprint AND h.day >= ?) people,
            (SELECT COUNT(*) FROM crash_hits h WHERE h.fingerprint = c.fingerprint AND h.day >= ?) hits
     FROM crashes c WHERE c.last_day >= ? ORDER BY c.status = 'ignored', c.handled, hits DESC LIMIT 40`, since, since, since);
  const reports = await all(env, "SELECT id, ts, v, message, email, diagnostics, country, status FROM reports ORDER BY status = 'done', ts DESC LIMIT 40");
  // downloads: the newest count of every file, and per day the growth of the totals
  const latest = await all(env,
    "SELECT d.tag, d.asset, d.count FROM downloads d WHERE d.day = (SELECT MAX(day) FROM downloads)");
  const perDay = await all(env, "SELECT day, asset, SUM(count) n FROM downloads WHERE day >= ? GROUP BY day, asset ORDER BY day", ago(range));
  const kinds = {};
  const tags = {};
  for (const r of latest) {
    const k = assetKind(r.asset);
    if (!k) continue;
    kinds[k] = (kinds[k] || 0) + r.count;
    if (["macOS", "Windows", "Linux"].includes(k)) tags[r.tag] = (tags[r.tag] || 0) + r.count;
  }
  const totals = new Map();
  for (const r of perDay) {
    if (!["macOS", "Windows", "Linux"].includes(assetKind(r.asset))) continue;
    totals.set(r.day, (totals.get(r.day) || 0) + r.n);
  }
  const days = [...totals.keys()].sort();
  const dlDaily = days.slice(1).map((d, i) => ({ day: d, n: Math.max(0, totals.get(d) - totals.get(days[i])) }));
  return {
    range, since, generated: new Date().toISOString(),
    totals: { installs: installs.n || 0, today: active1.n || 0, week: active7.n || 0, month: active30.n || 0,
              quiet: quiet.n || 0, opens: opens.n || 0, sessions: sessions.n || 0, crashSessions: crashSessions.n || 0,
              retained: retained.total ? Math.round((100 * (retained.kept || 0)) / retained.total) : null,
              retainedOf: retained.total || 0 },
    daily: fill(daily, since, range), newDaily: fill(newDaily, since, range), quietMonthly,
    versions, oses, archs, countries, commands, views, edits, features, via, crashes, reports,
    downloads: { kinds, tags, daily: dlDaily },
  };
}

function fill(rows, since, range) {
  const m = new Map(rows.map((r) => [r.day, r.n]));
  const out = [];
  const start = new Date(since + "T00:00:00Z").getTime() / 1000;
  for (let i = 0; i < range; i++) {
    const d = day(start + i * 86400);
    out.push({ day: d, n: m.get(d) || 0 });
  }
  return out;
}

// ------------------------------------------------------------------ the page
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (n) => (n == null ? "–" : Number(n).toLocaleString("en-US"));

// one series of daily bars; each bar names its day and value on hover
function bars(series, label) {
  const w = 720, h = 160, pad = 24;
  const max = Math.max(1, ...series.map((s) => s.n));
  const bw = (w - pad) / series.length;
  const gap = Math.min(2, bw * 0.2);
  const rects = series.map((s, i) => {
    const bh = s.n ? Math.max(2, ((h - pad * 1.5) * s.n) / max) : 0;   // the tallest bar meets the top line
    const x = pad + i * bw + gap / 2;
    return `<g><rect class="hit" x="${x - gap / 2}" y="0" width="${bw}" height="${h - pad}"><title>${esc(s.day)}: ${fmt(s.n)}</title></rect>` +
      (bh ? `<path class="bar" d="${roundTop(x, h - pad - bh, bw - gap, bh)}"><title>${esc(s.day)}: ${fmt(s.n)}</title></path>` : "") + "</g>";
  }).join("");
  const first = series[0]?.day || "", last = series.at(-1)?.day || "";
  return `<figure><figcaption>${esc(label)}</figcaption><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}">
    <line class="grid" x1="${pad}" x2="${w}" y1="${pad / 2}" y2="${pad / 2}"/>
    <text class="axis" x="0" y="${pad / 2 + 4}">${fmt(max)}</text>
    <line class="base" x1="${pad}" x2="${w}" y1="${h - pad}" y2="${h - pad}"/>${rects}
    <text class="axis" x="${pad}" y="${h - 6}">${esc(first.slice(5))}</text>
    <text class="axis" x="${w}" y="${h - 6}" text-anchor="end">${esc(last.slice(5))}</text></svg></figure>`;
}

function roundTop(x, y, w, h) {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function table(rows, cols, empty = "Nothing yet") {
  if (!rows.length) return `<p class="muted">${empty}</p>`;
  return `<table><thead><tr>${cols.map(([, t, num]) => `<th${num ? ' class="num"' : ""}>${esc(t)}</th>`).join("")}</tr></thead><tbody>` +
    rows.map((r) => `<tr>${cols.map(([k, , num, f]) => `<td${num ? ' class="num"' : ""}>${f ? f(r[k], r) : esc(num ? fmt(r[k]) : r[k] ?? "–")}</td>`).join("")}</tr>`).join("") +
    "</tbody></table>";
}

function share(rows) {
  const total = rows.reduce((a, r) => a + r.n, 0) || 1;
  return rows.map((r) => ({ ...r, pct: Math.round((100 * r.n) / total) }));
}

const tile = (label, value, note = "") =>
  `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}</div>${note ? `<div class="note">${esc(note)}</div>` : ""}</div>`;

export function dashboard(n) {
  const t = n.totals;
  const crashFree = t.sessions ? `${(100 - (100 * t.crashSessions) / t.sessions).toFixed(1)}%` : "–";
  const dl = n.downloads.kinds;
  const installsDl = (dl.macOS || 0) + (dl.Windows || 0) + (dl.Linux || 0);
  const ranges = [7, 30, 90, 365].map((r) => `<a href="?days=${r}"${r === n.range ? ' aria-current="page"' : ""}>${r} days</a>`).join("");
  const status = (s) => `<span class="st ${esc(s)}">${esc(s)}</span>`;
  const crashRows = n.crashes.map((c) => ({ ...c, frames: JSON.parse(c.frames || "[]") }));
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TripShots usage</title><style>
:root{--bg:#f4f3f0;--surface:#fcfcfb;--text:#0b0b0b;--text2:#52514d;--muted:#898781;--line:#e1e0d9;--bar:#2a78d6;--crit:#d03b3b;--good:#006300;color-scheme:light dark}
@media (prefers-color-scheme: dark){:root{--bg:#111110;--surface:#1a1a19;--text:#f0efec;--text2:#b5b3ad;--muted:#898781;--line:#2c2c2a;--bar:#3987e5;--crit:#e05555;--good:#0ca30c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1120px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0}h2{font-size:16px;margin:0 0 12px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;margin-bottom:20px}
nav a{color:var(--text2);text-decoration:none;padding:4px 10px;border-radius:8px}nav a[aria-current]{background:var(--surface);color:var(--text);box-shadow:inset 0 0 0 1px var(--line)}
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:16px;overflow-x:auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}.tile .label{color:var(--text2);font-size:13px}
.tile .value{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}.tile .note{color:var(--muted);font-size:12px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}.grid2 section{margin:0}
figure{margin:0 0 8px}figcaption{color:var(--text2);font-size:13px;margin-bottom:4px}svg{width:100%;height:auto;display:block}
.bar{fill:var(--bar)}.hit{fill:transparent}.hit:hover+.bar,.bar:hover{opacity:.8}.grid,.base{stroke:var(--line);stroke-width:1}.base{stroke:var(--muted)}
.axis{fill:var(--muted);font-size:11px}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-weight:500;border-bottom:1px solid var(--line);padding:6px 8px}
td{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:top}.num{text-align:right;font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}code,.mono{font:12px ui-monospace,Menlo,monospace}details summary{cursor:pointer}
.st{font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line)}.st.open,.st.back,.st.new{color:var(--crit)}.st.fixed,.st.done{color:var(--good)}
form{display:inline}button{font:inherit;font-size:12px;background:transparent;color:var(--text2);border:1px solid var(--line);border-radius:6px;padding:2px 8px;cursor:pointer}
.msg{white-space:pre-wrap;max-width:520px}</style></head><body><main>
<header><div><h1>TripShots usage</h1><div class="muted">Last ${n.range} days · from people who said yes · ${esc(n.generated.slice(0, 16).replace("T", " "))} UTC</div></div><nav>${ranges}</nav></header>

<div class="tiles">
${tile("Downloads", fmt(installsDl), "installer files from GitHub, everyone")}
${tile("Installs seen", fmt(t.installs), "opted in, ever")}
${tile("Active this week", fmt(t.week), `${fmt(t.today)} today · ${fmt(t.month)} in 30 days`)}
${tile("App opens", fmt(t.opens), `in ${n.range} days`)}
${tile("Kept using it", t.retained == null ? "–" : `${t.retained}%`, `still active a week after the first day (${fmt(t.retainedOf)} installs)`)}
${tile("Gone quiet", fmt(t.quiet), "not seen for 30 days: likely removed")}
${tile("Crash-free sessions", crashFree, `${fmt(t.crashSessions)} of ${fmt(t.sessions)} sessions had a crash`)}
${tile("Update checks", fmt(dl["update checks"]), "every copy, opted in or not")}
</div>

<section>${bars(n.daily, "People using TripShots each day")}${bars(n.newDaily, "New installs each day")}
${n.downloads.daily.length ? bars(n.downloads.daily, "Installer downloads each day") : '<p class="muted">Download counts start with the first daily snapshot.</p>'}</section>

<div class="grid2">
<section><h2>Commands</h2>${table(n.commands, [["k", "Command"], ["n", "Runs", 1], ["people", "People", 1], ["failed", "Failed", 1], ["secs", "Typical secs", 1]])}</section>
<section><h2>Where they come from</h2>${table(n.via, [["k", "Started by"], ["n", "Runs", 1], ["people", "People", 1]])}
<h2 style="margin-top:16px">Screens</h2>${table(n.views, [["k", "Screen"], ["n", "Opened", 1], ["people", "People", 1]])}</section>
<section><h2>Editor tools</h2>${table(n.edits, [["k", "Tool"], ["n", "Used", 1], ["people", "People", 1]])}</section>
<section><h2>Features</h2>${table(n.features, [["k", "Feature"], ["n", "Used", 1], ["people", "People", 1]])}</section>
<section><h2>Versions <span class="muted">(active in 30 days)</span></h2>${table(share(n.versions), [["k", "Version"], ["n", "Installs", 1], ["pct", "%", 1]])}</section>
<section><h2>Systems</h2>${table(share(n.oses), [["k", "OS"], ["n", "Installs", 1], ["pct", "%", 1]])}
<h2 style="margin-top:16px">Chips</h2>${table(share(n.archs), [["k", "Chip"], ["n", "Installs", 1], ["pct", "%", 1]])}</section>
<section><h2>Countries</h2>${table(share(n.countries), [["k", "Country"], ["n", "Installs", 1], ["pct", "%", 1]])}</section>
<section><h2>Downloads by kind <span class="muted">(all time)</span></h2>${table(Object.entries(n.downloads.kinds).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ k, n: v })), [["k", "Kind"], ["n", "Downloads", 1]])}
<h2 style="margin-top:16px">Installers by release</h2>${table(Object.entries(n.downloads.tags).sort((a, b) => b[0].localeCompare(a[0], "en", { numeric: true })).map(([k, v]) => ({ k, n: v })), [["k", "Release"], ["n", "Downloads", 1]])}</section>
<section><h2>Gone quiet, by month last seen</h2>${table(n.quietMonthly, [["month", "Last seen"], ["n", "Installs", 1]])}
<p class="muted">macOS tells no app it was removed, so "gone quiet" is the honest stand-in for uninstalls.</p></section>
</div>

<section style="margin-top:16px"><h2>Crashes</h2>${table(crashRows, [
    ["type", "Error", 0, (v, r) => `<strong>${esc(v)}</strong> <span class="muted">${esc(r.kind)}${r.handled ? " · shown to the user" : ""}</span><div class="msg">${esc(r.message)}</div>` +
      `<details><summary class="muted">${esc(r.place)} · where</summary><div class="mono">${r.frames.map(esc).join("<br>")}</div></details>`],
    ["hits", "Times", 1], ["people", "People", 1],
    ["last_v", "Versions", 0, (v, r) => `${esc(r.first_v)}${r.first_v !== v ? ` → ${esc(v)}` : ""}<div class="muted">${esc(r.last_day)}</div>`],
    ["status", "", 0, (v, r) => `${status(v)} <form method="post" action="/dashboard/crash/${esc(r.fingerprint)}"><input type="hidden" name="status" value="${v === "fixed" ? "open" : "fixed"}"><button>${v === "fixed" ? "Reopen" : "Fixed"}</button></form>` +
      (v !== "ignored" ? ` <form method="post" action="/dashboard/crash/${esc(r.fingerprint)}"><input type="hidden" name="status" value="ignored"><button>Ignore</button></form>` : "")],
  ], "No crashes in this period")}</section>

<section><h2>Bug reports</h2>${table(n.reports, [
    ["ts", "When", 0, (v, r) => `${esc(new Date(v * 1000).toISOString().slice(0, 16).replace("T", " "))}<div class="muted">${esc(r.v)} ${esc(r.country)}</div>`],
    ["message", "What they said", 0, (v, r) => `<div class="msg">${esc(v)}</div>${r.email ? `<div><a href="mailto:${esc(r.email)}">${esc(r.email)}</a></div>` : ""}` +
      (r.diagnostics ? `<details><summary class="muted">Diagnostics</summary><pre class="mono">${esc(JSON.stringify(JSON.parse(r.diagnostics), null, 1))}</pre></details>` : "")],
    ["status", "", 0, (v, r) => `${status(v)} <form method="post" action="/dashboard/report/${r.id}"><input type="hidden" name="status" value="${v === "done" ? "new" : "done"}"><button>${v === "done" ? "Reopen" : "Done"}</button></form>`],
  ], "No reports yet")}</section>
</main></body></html>`;
}
