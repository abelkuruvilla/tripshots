// The window's side of telemetry. Everything goes through the engine (/api/telemetry), which keeps it only when the
// user said yes and sends it on (tripshots/telemetry.py checks every event again). Names only: which screen, which
// editor tool; never what is in a reel.
import { api } from "./store.svelte.js";

let queue = [];
let timer = null;

export function track(name, props = {}) {
  queue.push({ name, props });
  if (queue.length > 40) return flush();
  clearTimeout(timer);
  timer = setTimeout(flush, 3000);
}

export async function flush() {
  clearTimeout(timer);
  if (!queue.length) return;
  const events = queue.splice(0, 50);
  await api("/api/telemetry", { events }).catch(() => {});
}

// "at fn (http://127.0.0.1:1420/assets/index-abc.js:10:5)" -> "fn (assets/index-abc.js:10:5)"
function frames(stack) {
  return String(stack || "").split("\n").slice(1, 13).map((l) => l.trim().replace(/^at\s+/, "")
    .replace(/(?:https?|tauri|asset):\/\/[^/\s)]+\//g, ""));
}

const seen = new Set();
function report(err, where) {
  const e = err instanceof Error ? err : new Error(String(err?.message || err));
  const key = `${e.name}:${e.message}`;
  if (seen.has(key)) return;   // one report per kind of error per run
  seen.add(key);
  api("/api/telemetry", { crash: { type: e.name, message: e.message, where, frames: frames(e.stack) } }).catch(() => {});
}

export function watchErrors() {
  window.addEventListener("error", (ev) => report(ev.error || ev.message, "window"));
  window.addEventListener("unhandledrejection", (ev) => {
    const r = ev.reason;
    // the engine's own answers ("no such reel", a 400) are messages for the user, not crashes
    if (r && r.fromEngine) return;
    report(r, "promise");
  });
}
