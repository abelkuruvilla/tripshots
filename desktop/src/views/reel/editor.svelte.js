// The open reel and what's selected in it. Every change goes through the engine's plan edits (/api/edit), which
// keep the beat grid and an undo history; the view then reloads the plan. Nothing is rendered until Render.
import { app, api, toast } from "../../lib/store.svelte.js";

const EXPERT_KEY = "tripshots.expert";
const readExpert = () => {
  try {
    return localStorage.getItem(EXPERT_KEY) === "1";
  } catch {
    return false;
  }
};

export const ed = $state({
  reel: null,
  error: "",
  sel: null, // { kind: "text", index } | { kind: "clip", slot }
  expert: readExpert(),
  now: 0, // playhead, seconds
  busy: false,
  version: 0, // bumps after every change: previews ask for a new frame
  fonts: [],
  preview: false, // show the edited frame instead of the last render
  raw: false, // the preview shows the shot as filmed (Colour's compare)
  tab: "text", // the inspector's tab: shot, text, colour, sound, post
  split: false, // the viewer shows as filmed | your edit side by side, with a divider
  splitAt: 0.5, // where the divider is, 0 (left) to 1 (right)
  mask: null, // a colour layer's region shown on the picture (Colour > Layers)
  notes: [], // the user's notes on the reel, each pinned to a moment: [{ t, text }] (kept per reel, sent together)
  noting: false, // the note box is open
});

// notes stay on this computer until they are sent (one list per reel)
const notesKey = () => `tripshots.notes:${ed.reel?.plan || app.reel}`;
export function loadNotes() {
  try {
    ed.notes = JSON.parse(localStorage.getItem(notesKey()) || "[]");
  } catch {
    ed.notes = [];
  }
}
function saveNotes() {
  try {
    localStorage.setItem(notesKey(), JSON.stringify(ed.notes));
  } catch {}
}
export function addNote(t, text) {
  text = text.trim();
  if (!text) return;
  ed.notes = [...ed.notes, { t: Math.round(t * 100) / 100, text }].sort((a, b) => a.t - b.t);
  saveNotes();
}
export function removeNote(i) {
  ed.notes = ed.notes.filter((_, k) => k !== i);
  saveNotes();
}
export function clearNotes() {
  ed.notes = [];
  saveNotes();
}

export function setExpert(on) {
  ed.expert = on;
  try {
    localStorage.setItem(EXPERT_KEY, on ? "1" : "0");
  } catch {}
  if (!on && ed.sel?.kind === "clip") ed.sel = null;
  if (!on && (ed.tab === "shot" || ed.tab === "sound")) ed.tab = "text";
}

export async function load() {
  try {
    ed.reel = await api(`/api/reel?plan=${encodeURIComponent(app.reel)}`);
    ed.error = "";
    ed.version++;
    // a selection that no longer exists (the text was removed, the slot merged) goes away
    if (ed.sel?.kind === "text" && !ed.reel.texts.some((t) => t.index === ed.sel.index)) ed.sel = null;
    if (ed.sel?.kind === "clip" && ed.sel.slot > ed.reel.segments.length) ed.sel = null;
  } catch (e) {
    ed.error = String(e.message || e);
  }
}

// changes run one after another, in the order they were made (an undo never overtakes the edit before it)
let chain = Promise.resolve();
const queued = (fn) => (chain = chain.then(fn, fn));

// one change (several ops at once are one undo step)
export function edit(ops, quiet = false) {
  return queued(() => applyEdit(ops, quiet));
}
async function applyEdit(ops, quiet) {
  if (!ed.reel) return null;
  ed.busy = true;
  try {
    const res = await api("/api/edit", { plan: ed.reel.plan, edits: Array.isArray(ops) ? ops : [ops] });
    await load();
    const list = Array.isArray(ops) ? ops : [ops];
    const notes = (res.changes || []).filter((c) => c.startsWith("note:"));
    const gone = list.some((o) => ["delete", "delete_text"].includes(o.op) || o.reset);
    if (gone) toast(sentence(res.changes.join(" · ")), "info", { label: "Undo", run: () => undo() });
    else if (notes.length) toast(notes.join(" ").replace(/note: /g, ""), "info");
    else if (!quiet && res.changes?.length) toast(sentence(res.changes.join(" · ")), "info");
    return res;
  } catch (e) {
    toast(String(e.message || e), "error");
    return null;
  } finally {
    ed.busy = false;
  }
}

async function step(dir) {
  if (!ed.reel) return;
  try {
    await api(`/api/${dir}`, { plan: ed.reel.plan });
    await load();
  } catch (e) {
    toast(String(e.message || e), "error");
  }
}
export const undo = () => queued(() => step("undo"));
export const redo = () => queued(() => step("redo"));

export async function loadFonts() {
  if (!ed.fonts.length) ed.fonts = await api("/api/fonts").catch(() => []);
  return ed.fonts;
}

// a font as the browser can show it (for the font list and the size of things): loaded once from the engine
const loaded = new Map();
export function fontFamily(id) {
  if (!id || !app.engine) return "inherit";
  const fam = "ts-" + id.replace(/[^a-z0-9]/gi, "_");
  if (!loaded.has(id)) {
    loaded.set(id, true);
    const url = `${app.engine.url}/api/font?t=${app.engine.token}&name=${encodeURIComponent(id)}`;
    const f = new FontFace(fam, `url("${url}")`);
    f.load().then((ff) => document.fonts.add(ff)).catch(() => {});
  }
  return `"${fam}", var(--font)`;
}

const sentence = (t) => t.replace(/^./, (c) => c.toUpperCase());

// select a shot or a line of text, and show its tab
export function select(sel) {
  ed.sel = sel;
  if (sel?.kind === "clip" && ed.expert) ed.tab = "shot";
  if (sel?.kind === "text") {
    ed.tab = "text";
    ed.preview = true;
  }
}

export const SNAP = 1 / 30; // a frame
export const frames = (s) => Math.round(s / SNAP) * SNAP;

// the colour of a style as #rrggbb (the engine keeps [r, g, b])
export function hex(c, fallback = "#ffffff") {
  if (!Array.isArray(c)) return fallback;
  return "#" + c.slice(0, 3).map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, "0")).join("");
}
