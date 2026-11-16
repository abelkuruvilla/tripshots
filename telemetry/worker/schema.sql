-- TripShots collector (Cloudflare D1). Apply with: npx wrangler d1 execute tripshots --remote --file schema.sql
-- No IP addresses are stored: only the country Cloudflare reports.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, day TEXT NOT NULL, ts INTEGER NOT NULL, install TEXT NOT NULL, session TEXT,
  name TEXT NOT NULL, props TEXT, v TEXT, os TEXT, osv TEXT, arch TEXT, country TEXT
);
CREATE INDEX IF NOT EXISTS events_day ON events(day, name);
CREATE INDEX IF NOT EXISTS events_install ON events(install, day);

CREATE TABLE IF NOT EXISTS installs (
  install TEXT PRIMARY KEY, first_day TEXT NOT NULL, last_day TEXT NOT NULL, v TEXT, os TEXT, osv TEXT, arch TEXT,
  country TEXT, opens INTEGER NOT NULL DEFAULT 0, events INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS installs_last ON installs(last_day);

CREATE TABLE IF NOT EXISTS crashes (
  fingerprint TEXT PRIMARY KEY, kind TEXT, type TEXT, message TEXT, place TEXT, frames TEXT, handled INTEGER,
  first_day TEXT, last_day TEXT, first_v TEXT, last_v TEXT, count INTEGER NOT NULL DEFAULT 0, status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS crash_hits (fingerprint TEXT NOT NULL, day TEXT NOT NULL, install TEXT NOT NULL, v TEXT);
CREATE INDEX IF NOT EXISTS crash_hits_fp ON crash_hits(fingerprint, day);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, install TEXT, v TEXT, message TEXT NOT NULL, email TEXT,
  diagnostics TEXT, country TEXT, status TEXT DEFAULT 'new'
);

-- GitHub release asset download counts, one row per asset per day (the daily cron)
CREATE TABLE IF NOT EXISTS downloads (day TEXT NOT NULL, tag TEXT NOT NULL, asset TEXT NOT NULL, count INTEGER NOT NULL,
  PRIMARY KEY (day, tag, asset));

-- per install per day, so one broken or hostile client can't flood the tables
CREATE TABLE IF NOT EXISTS limits (install TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (install, day, kind));
