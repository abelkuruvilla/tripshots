// App state and the engine client. The engine (`tripshots serve`) runs on 127.0.0.1 with a random token the
// Rust side chose; every call carries it. Media (<video>, <img>) use ?t= because they can't set headers.
import { invoke } from "@tauri-apps/api/core";

export const app = $state({
  engine: null, // { url, token, version, path, source }
  engineState: null, // what the Rust side reports: status, error, installed_version, platform, app_version
  status: null, // /api/status
  view: "reels",
  reel: null, // plan path of the open reel
  reels: [],
  jobs: [],
  toasts: [],
});

export async function startEngine(restart = false) {
  const st = await invoke("engine_start", { restart });
  app.engineState = st;
  app.engine = st.info || null;
  if (app.engine) await refreshStatus();
  return st;
}

export async function api(path, body) {
  if (!app.engine) throw new Error("the engine isn't running");
  const res = await fetch(app.engine.url + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${app.engine.token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

export function media(path, bust) {
  if (!path || !app.engine) return "";
  const v = bust ? `&v=${bust}` : "";
  return `${app.engine.url}/api/file?t=${app.engine.token}&path=${encodeURIComponent(path)}${v}`;
}

export async function refreshStatus() {
  app.status = await api("/api/status");
}

export async function refreshReels() {
  app.reels = await api("/api/reels");
}

export function toast(text, kind = "info", action = null) {
  const id = Math.random().toString(36).slice(2);
  app.toasts.push({ id, text, kind, action });
  setTimeout(() => (app.toasts = app.toasts.filter((t) => t.id !== id)), action ? 9000 : 5000);
}

export function openReel(plan) {
  app.reel = plan;
  app.view = "reel";
}

export async function startJob(kind, fields, label) {
  const st = await api("/api/jobs", { kind, ...fields });
  toast(`${label || kind}: started`, "info");
  await pollJobs();
  return st;
}

// ---------------------------------------------------------------- job watching
const finished = new Set();
let timer = null;

export async function pollJobs() {
  if (!app.engine) return;
  let list;
  try {
    list = await api("/api/jobs?n=20");
  } catch {
    return;
  }
  const before = new Map(app.jobs.map((j) => [j.id, j.state]));
  app.jobs = list;
  for (const j of list) {
    if (before.get(j.id) === "running" && j.state !== "running" && !finished.has(j.id)) {
      finished.add(j.id);
      onFinished(j.id);
    }
  }
}

async function onFinished(id) {
  const st = await api(`/api/jobs/${id}`).catch(() => null);
  if (!st) return;
  if (st.state === "failed") {
    toast(`${st.label || st.kind} failed: ${st.error || "see Jobs"}`, "error");
    return;
  }
  const res = st.result || {};
  const plan = res.plan || (res.variants && res.variants[0] && res.variants[0].plan);
  if (["make", "render", "ask"].includes(st.kind)) {
    await refreshReels().catch(() => {});
    toast(`${st.label || st.kind}: done`, "ok", plan ? { label: "Open", run: () => openReel(plan) } : null);
  } else {
    toast(`${st.label || st.kind}: done`, "ok");
  }
  if (st.kind === "learn") refreshStatus().catch(() => {});
}

export function watchJobs() {
  if (timer) return;
  const tick = async () => {
    await pollJobs();
    const busy = app.jobs.some((j) => j.state === "running");
    timer = setTimeout(tick, busy ? 1500 : 6000);
  };
  tick();
}

// ---------------------------------------------------------------- little helpers
export function seconds(s) {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${(+s).toFixed(1)} s`;
}

export function ago(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 90) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
