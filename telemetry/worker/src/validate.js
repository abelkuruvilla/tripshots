// What the collector accepts. The same rules as the app (tripshots/telemetry.py): named events with a short list of
// properties each, values that are plain words, numbers or yes/no, and nothing else. Anything else is dropped here,
// before it reaches the database, whatever a client sends.

export const EVENTS = {
  app_open: ["app"],
  command: ["cmd", "ok", "secs", "via", "flags", "error"],
  view: ["view"],
  edit: ["op", "n"],
  feature: ["name", "kind"],
  consent: ["on"],
};
export const LIMITS = { events: 3000, crash: 60, report: 5 };   // per install per day
const WORD = /^[A-Za-z0-9_.:+\-]{0,48}$/;
const ID = /^[0-9a-f]{32}$/;
const SHORT = /^[A-Za-z0-9_.:+\-]{0,16}$/;
const DAY_MS = 86400000;

export function day(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function word(v, re = WORD) {
  return typeof v === "string" && re.test(v) ? v : null;
}

export function cleanProps(name, props) {
  const allowed = EVENTS[name];
  if (!allowed) return null;
  const out = {};
  for (const k of allowed) {
    const v = props?.[k];
    if (v === undefined || v === null) continue;
    if (typeof v === "boolean" || (typeof v === "number" && Number.isFinite(v) && Math.abs(v) < 1e9)) out[k] = v;
    else if (typeof v === "string" && WORD.test(v)) out[k] = v;
    else if (Array.isArray(v)) {
      const w = v.filter((x) => typeof x === "string" && WORD.test(x)).slice(0, 30);
      if (w.length) out[k] = w;
    }
  }
  return out;
}

function text(v, n) {
  return typeof v === "string" ? v.replace(/[\u0000-\u0008\u000b-\u001f]/g, "").slice(0, n) : "";
}

// a crash as the app sends it, cut to size; the app already removed paths and names
export function cleanCrash(c) {
  if (!c || typeof c !== "object") return null;
  const fp = word(c.fingerprint, /^[0-9a-f]{8,40}$/);
  if (!fp) return null;
  return {
    fingerprint: fp,
    kind: ["engine", "ui", "shell"].includes(c.kind) ? c.kind : "engine",
    type: text(c.type, 60).replace(/[^\w.]/g, "") || "Error",
    message: text(c.message, 300),
    place: text(c.where, 80),
    frames: (Array.isArray(c.frames) ? c.frames : []).slice(0, 12).map((f) => text(String(f), 120)),
    handled: !!c.handled,
  };
}

// one event from a batch, with the sender's coarse context; null = drop it
export function cleanEvent(e, now = Date.now()) {
  if (!e || typeof e !== "object") return null;
  const install = word(e.install, ID);
  if (!install) return null;
  let ts = Number.isFinite(e.ts) ? Math.floor(e.ts) : Math.floor(now / 1000);
  if (ts * 1000 > now + DAY_MS || ts * 1000 < now - 30 * DAY_MS) ts = Math.floor(now / 1000);   // a wrong clock
  const ctx = {
    install, ts, day: day(ts),
    session: word(e.session, /^[0-9a-f]{0,32}$/) || "",
    v: word(e.v, SHORT) || "", os: word(e.os, SHORT) || "", osv: word(e.osv, SHORT) || "", arch: word(e.arch, SHORT) || "",
  };
  if (e.name === "crash") {
    const crash = cleanCrash(e.crash);
    return crash ? { ...ctx, name: "crash", crash } : null;
  }
  const props = cleanProps(e.name, e.props);
  return props ? { ...ctx, name: e.name, props } : null;
}

export function cleanReport(b) {
  if (!b || typeof b !== "object") return null;
  const message = text(b.message, 4000).trim();
  if (!message) return null;
  const email = typeof b.email === "string" && /^[^\s@]{1,64}@[^\s@]{1,64}\.[^\s@]{2,24}$/.test(b.email) ? b.email : null;
  let diagnostics = null;
  if (b.diagnostics && typeof b.diagnostics === "object") {
    diagnostics = JSON.stringify(b.diagnostics).slice(0, 8000);
  }
  return { message, email, diagnostics, install: word(b.install, ID), v: word(b.v, SHORT) || "" };
}
