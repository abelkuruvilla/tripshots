// The collector against a real SQLite database (node:sqlite standing in for D1). Run: node --test test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";
import { cleanEvent, cleanProps, cleanReport } from "../src/validate.js";
import { assetKind, dashboard, numbers } from "../src/dashboard.js";

// a D1-shaped wrapper: prepare().bind().all()/first()/run(), batch()
function d1() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, a),
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    first: async () => db.prepare(sql).get(...args) ?? null,
    run: async () => db.prepare(sql).run(...args),
  });
  return { raw: db, prepare: (sql) => stmt(sql), batch: async (list) => { for (const s of list) await s.run(); } };
}

const ID = "a".repeat(32);
const now = Math.floor(Date.now() / 1000);
const ev = (name, props, extra = {}) => ({ name, props, ts: now, install: ID, session: "s1", v: "0.3.0", os: "darwin", osv: "15.1", arch: "arm64", ...extra });
const post = (path, body) => new Request(`https://c.example${path}`, { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });

test("only known events with plain values are kept", () => {
  assert.deepEqual(cleanProps("command", { cmd: "make", ok: true, secs: 60, path: "/Users/x", flags: ["music", "/a b"] }),
                   { cmd: "make", ok: true, secs: 60, flags: ["music"] });
  assert.deepEqual(cleanProps("view", { view: "/Users/me/Trips" }), {});
  assert.equal(cleanProps("keystrokes", { k: "a" }), null);
  assert.equal(cleanEvent({ ...ev("view", { view: "make" }), install: "me@example.com" }), null);
  const wrongClock = cleanEvent(ev("view", { view: "make" }, { ts: now + 10 * 86400 }));
  assert.ok(Math.abs(wrongClock.ts - now) < 5);
  assert.equal(cleanReport({ message: "  " }), null);
  assert.equal(cleanReport({ message: "x", email: "not an email" }).email, null);
});

test("events, crashes and reports land in the tables and on the dashboard", async () => {
  const env = { DB: d1(), DASHBOARD_PASSWORD: "pw" };
  const crash = { kind: "engine", type: "ValueError", message: "bad <path>", where: "cli:make", frames: ["tripshots/render.py:seg:10"], fingerprint: "0123456789abcdef" };
  let r = await worker.fetch(post("/v1/events", { events: [
    ev("app_open", { app: "0.3.0" }), ev("command", { cmd: "make", ok: false, secs: 600, via: "app" }),
    ev("edit", { op: "split" }), ev("crash", null, { crash }), ev("crash", null, { crash }), { name: "junk" },
  ] }), env);
  assert.equal(r.status, 202);
  assert.deepEqual(await r.json(), { ok: true, kept: 5, dropped: 1 });
  r = await worker.fetch(post("/v1/report", { message: "The timeline froze", install: ID, v: "0.3.0", diagnostics: { os: "darwin" } }), env);
  assert.equal(r.status, 202);

  const db = env.DB.raw;
  assert.equal(db.prepare("SELECT opens FROM installs").get().opens, 1);
  assert.equal(db.prepare("SELECT count FROM crashes").get().count, 2);
  assert.equal(db.prepare("SELECT COUNT(*) n FROM reports").get().n, 1);
  assert.equal(db.prepare("SELECT COUNT(*) n FROM events WHERE country != ''").get().n, 0);

  assert.equal((await worker.fetch(new Request("https://c.example/dashboard"), env)).status, 401);
  const auth = { Authorization: "Basic " + btoa("me:pw") };
  const page = await (await worker.fetch(new Request("https://c.example/dashboard", { headers: auth }), env)).text();
  assert.match(page, /TripShots usage/);
  assert.match(page, /ValueError/);
  assert.match(page, /The timeline froze/);
  const n = await numbers(env, 30);
  assert.equal(n.totals.installs, 1);
  assert.equal(n.commands[0].failed, 1);
  assert.equal(n.totals.crashSessions, 1);

  // the dashboard's Fixed button
  const form = new FormData();
  form.set("status", "fixed");
  r = await worker.fetch(new Request("https://c.example/dashboard/crash/0123456789abcdef", { method: "POST", body: form, headers: auth }), env);
  assert.equal(r.status, 303);
  assert.equal(db.prepare("SELECT status FROM crashes").get().status, "fixed");
});

test("one install can't flood the tables", async () => {
  const env = { DB: d1() };
  const many = Array.from({ length: 500 }, () => ev("view", { view: "make" }));
  for (let i = 0; i < 7; i++) await worker.fetch(post("/v1/events", { events: many }), env);
  assert.equal(env.DB.raw.prepare("SELECT COUNT(*) n FROM events").get().n, 3000);
  for (let i = 0; i < 7; i++) await worker.fetch(post("/v1/report", { message: "again", install: ID }), env);
  assert.equal(env.DB.raw.prepare("SELECT COUNT(*) n FROM reports").get().n, 5);
});

test("release files are sorted into kinds, and the page renders with nothing in it", async () => {
  assert.equal(assetKind("TripShots_0.3.0_aarch64.dmg"), "macOS");
  assert.equal(assetKind("TripShots.app.tar.gz"), "app updates");
  assert.equal(assetKind("TripShots.app.tar.gz.sig"), null);
  assert.equal(assetKind("latest.json"), "update checks");
  assert.equal(assetKind("tripshots-engine-0.3.0-darwin-arm64.tar.gz"), "engine downloads");
  assert.equal(assetKind("TripShots_0.3.0_x64-setup.exe"), "Windows");
  const html = dashboard(await numbers({ DB: d1() }, 7));
  assert.match(html, /No crashes in this period/);
});
