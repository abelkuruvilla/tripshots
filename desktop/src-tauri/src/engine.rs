//! The TripShots engine: the Python program that does the work (`tripshots serve` answers the UI over HTTP on
//! 127.0.0.1). This finds it, starts it, downloads and verifies it from a release manifest, and stops it on exit.
//!
//! Where it comes from, in order: `TRIPSHOTS_ENGINE` (a path, for development), the copy installed by this app
//! (`<app data>/engine/<version>/tripshots/`), then a `tripshots` on PATH (a pip install).

use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

use base64::Engine as _;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager};

/// Where the app looks for the engine's release manifest (overridable at build time).
pub const MANIFEST_URL: &str = match option_env!("TRIPSHOTS_ENGINE_MANIFEST") {
    Some(u) => u,
    None => "https://github.com/abelkuruvilla/tripshots/releases/latest/download/engine.json",
};

pub struct Running {
    pub child: Child,
    pub info: EngineInfo,
}

#[derive(Clone, Serialize, Default)]
pub struct EngineInfo {
    pub url: String,
    pub token: String,
    pub version: String,
    pub path: String,
    pub source: String, // "dev" | "installed" | "path"
}

#[derive(Deserialize, Clone)]
pub struct Manifest {
    pub version: String,
    #[serde(default)]
    pub min_app: Option<String>,
    #[serde(default)]
    pub notes: Option<String>,
    pub platforms: std::collections::HashMap<String, Asset>,
}

#[derive(Deserialize, Clone)]
pub struct Asset {
    pub url: String,
    pub sha256: String,
    pub signature: String,
    #[serde(default)]
    pub size: Option<u64>,
}

#[derive(Clone, Serialize)]
struct Progress {
    stage: String,
    done: u64,
    total: u64,
}

pub fn exe_name() -> &'static str {
    if cfg!(windows) { "tripshots.exe" } else { "tripshots" }
}

/// This computer as the manifest names platforms: darwin-aarch64, darwin-x86_64, linux-x86_64, windows-x86_64.
pub fn platform_key() -> String {
    let os = match std::env::consts::OS {
        "macos" => "darwin",
        other => other,
    };
    format!("{}-{}", os, std::env::consts::ARCH)
}

fn engine_root(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app.path().app_data_dir().map_err(|e| e.to_string())?.join("engine"))
}

pub fn installed(app: &AppHandle) -> Option<(PathBuf, String)> {
    let root = engine_root(app).ok()?;
    let ver = std::fs::read_to_string(root.join("current")).ok()?.trim().to_string();
    let exe = root.join(&ver).join("tripshots").join(exe_name());
    exe.is_file().then_some((exe, ver))
}

/// Folders a GUI app doesn't get on PATH (macOS starts apps with a bare PATH), where pip and Homebrew put
/// `tripshots` and `ffmpeg`.
fn extra_dirs() -> Vec<PathBuf> {
    let mut v = vec![];
    if let Some(h) = dirs::home_dir() {
        v.push(h.join(".local").join("bin"));
    }
    if !cfg!(windows) {
        v.push("/opt/homebrew/bin".into());
        v.push("/usr/local/bin".into());
    }
    v
}

fn search_path() -> String {
    let sep = if cfg!(windows) { ";" } else { ":" };
    let mut parts: Vec<String> = std::env::var("PATH").unwrap_or_default().split(sep).map(String::from).collect();
    for d in extra_dirs() {
        let s = d.to_string_lossy().to_string();
        if !parts.contains(&s) {
            parts.push(s);
        }
    }
    parts.join(sep)
}

fn on_path() -> Option<PathBuf> {
    let sep = if cfg!(windows) { ';' } else { ':' };
    search_path().split(sep).map(|d| Path::new(d).join(exe_name())).find(|p| p.is_file())
}

/// The engine to run, and where it came from.
pub fn locate(app: &AppHandle) -> Option<(PathBuf, String)> {
    if let Ok(p) = std::env::var("TRIPSHOTS_ENGINE") {
        let p = PathBuf::from(p);
        if p.is_file() {
            return Some((p, "dev".into()));
        }
    }
    if let Some((p, _)) = installed(app) {
        return Some((p, "installed".into()));
    }
    on_path().map(|p| (p, "path".into()))
}

fn token() -> String {
    let mut b = [0u8; 24];
    getrandom::getrandom(&mut b).expect("random token");
    hex::encode(b)
}

/// Start `<engine> serve` and wait for the line that says where it listens.
pub fn start(app: &AppHandle, exe: &Path, source: &str) -> Result<Running, String> {
    let tok = token();
    let log_dir = app.path().app_log_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&log_dir).ok();
    let log = std::fs::File::create(log_dir.join("engine.log")).map_err(|e| e.to_string())?;
    let mut cmd = Command::new(exe);
    cmd.args(["serve", "--watch-stdin"])
        .env("TRIPSHOTS_API_TOKEN", &tok)
        .env("PATH", search_path())
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::piped()) // held open: the engine quits when the app does, even after a crash
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = cmd.spawn().map_err(|e| format!("could not start {}: {e}", exe.display()))?;
    let stdout = child.stdout.take().ok_or("no stdout")?;
    let (tx, rx) = mpsc::channel::<String>();
    std::thread::spawn(move || {
        let mut r = BufReader::new(stdout);
        let mut first = String::new();
        let _ = r.read_line(&mut first);
        let _ = tx.send(first);
        let mut sink = [0u8; 4096]; // keep draining so the engine never blocks on a full pipe
        while matches!(r.read(&mut sink), Ok(n) if n > 0) {}
    });
    // a first start can take a while (the OS checks a new executable once)
    let line = match rx.recv_timeout(Duration::from_secs(90)) {
        Ok(l) if !l.trim().is_empty() => l,
        _ => {
            let _ = child.kill();
            return Err(format!(
                "the engine didn't start (see {}). An older tripshots on PATH may not have `serve` yet.",
                log_dir.join("engine.log").display()
            ));
        }
    };
    let v: serde_json::Value = serde_json::from_str(line.trim()).map_err(|_| format!("unexpected engine output: {line}"))?;
    let info = EngineInfo {
        url: v["url"].as_str().unwrap_or_default().to_string(),
        version: v["version"].as_str().unwrap_or_default().to_string(),
        token: tok,
        path: exe.to_string_lossy().to_string(),
        source: source.to_string(),
    };
    Ok(Running { child, info })
}

pub fn parse_version(v: &str) -> (u64, u64, u64) {
    let mut it = v.trim_start_matches('v').split(|c: char| c == '.' || c == '-').map(|x| x.parse::<u64>().unwrap_or(0));
    (it.next().unwrap_or(0), it.next().unwrap_or(0), it.next().unwrap_or(0))
}

pub async fn fetch_manifest() -> Result<Manifest, String> {
    let r = reqwest::Client::new()
        .get(MANIFEST_URL)
        .header("User-Agent", "tripshots-desktop")
        .send()
        .await
        .map_err(|e| format!("no connection to the release server: {e}"))?;
    if !r.status().is_success() {
        return Err(format!("no engine release found ({} from {MANIFEST_URL})", r.status()));
    }
    r.json::<Manifest>().await.map_err(|e| format!("bad engine manifest: {e}"))
}

/// The updater key in tauri.conf.json (base64 of a minisign public key) signs engine archives too.
fn verify_signature(app: &AppHandle, data_path: &Path, sig_b64: &str) -> Result<(), String> {
    let pubkey_b64 = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .ok_or("no signing key in this build")?
        .to_string();
    let data = std::fs::read(data_path).map_err(|e| e.to_string())?;
    verify(&pubkey_b64, sig_b64, &data)
}

/// Check `data` against a signature from `tauri signer sign` (both key and signature are base64 of minisign text).
pub fn verify(pubkey_b64: &str, sig_b64: &str, data: &[u8]) -> Result<(), String> {
    let dec = |s: &str| -> Result<String, String> {
        let b = base64::engine::general_purpose::STANDARD.decode(s.trim()).map_err(|e| e.to_string())?;
        String::from_utf8(b).map_err(|e| e.to_string())
    };
    let pk = minisign_verify::PublicKey::decode(&dec(pubkey_b64)?).map_err(|e| format!("bad key: {e}"))?;
    let sig = minisign_verify::Signature::decode(&dec(sig_b64)?).map_err(|e| format!("bad signature: {e}"))?;
    pk.verify(data, &sig, false).map_err(|_| "the engine download is not signed by TripShots: not installed".to_string())
}

pub fn unpack(archive: &Path, dest: &Path) -> Result<(), String> {
    std::fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    let f = std::fs::File::open(archive).map_err(|e| e.to_string())?;
    let name = archive.to_string_lossy().to_lowercase();
    if name.ends_with(".zip") {
        let mut z = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
        z.extract(dest).map_err(|e| e.to_string())?;
    } else {
        let mut t = tar::Archive::new(flate2::read::GzDecoder::new(f));
        t.set_preserve_permissions(true);
        t.unpack(dest).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Download this platform's engine from the manifest, check its checksum and signature, unpack it next to the
/// current one and switch over only when all of that worked. Older versions are removed afterwards.
pub async fn install(app: &AppHandle) -> Result<String, String> {
    let emit = |stage: &str, done: u64, total: u64| {
        let _ = app.emit("engine-progress", Progress { stage: stage.into(), done, total });
    };
    emit("checking", 0, 0);
    let m = fetch_manifest().await?;
    let key = platform_key();
    let asset = m.platforms.get(&key).cloned().ok_or(format!("no engine for this computer ({key}) in {}", m.version))?;
    if let Some(min) = &m.min_app {
        if parse_version(env!("CARGO_PKG_VERSION")) < parse_version(min) {
            return Err(format!("engine {} needs TripShots {} or newer: update the app first", m.version, min));
        }
    }
    let root = engine_root(app)?;
    std::fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    let ext = if asset.url.to_lowercase().ends_with(".zip") { "zip" } else { "tar.gz" };
    let part = root.join(format!("download-{}.{ext}", m.version));
    let resp = reqwest::Client::new()
        .get(&asset.url)
        .header("User-Agent", "tripshots-desktop")
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;
    let total = resp.content_length().or(asset.size).unwrap_or(0);
    let mut file = std::fs::File::create(&part).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    let mut done = 0u64;
    let mut stream = resp.bytes_stream();
    let mut last = 0u64;
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| e.to_string())?;
        std::io::Write::write_all(&mut file, &chunk).map_err(|e| e.to_string())?;
        hasher.update(&chunk);
        done += chunk.len() as u64;
        if done - last > 2_000_000 {
            emit("downloading", done, total);
            last = done;
        }
    }
    drop(file);
    emit("verifying", done, total);
    if hex::encode(hasher.finalize()) != asset.sha256.to_lowercase() {
        let _ = std::fs::remove_file(&part);
        return Err("the download is damaged (checksum mismatch): try again".into());
    }
    verify_signature(app, &part, &asset.signature).inspect_err(|_| {
        let _ = std::fs::remove_file(&part);
    })?;
    emit("unpacking", done, total);
    let dest = root.join(&m.version);
    let _ = std::fs::remove_dir_all(&dest);
    let (p2, d2) = (part.clone(), dest.clone());
    tauri::async_runtime::spawn_blocking(move || unpack(&p2, &d2)).await.map_err(|e| e.to_string())??;
    let _ = std::fs::remove_file(&part);
    if !dest.join("tripshots").join(exe_name()).is_file() {
        return Err("the engine archive doesn't contain tripshots/".to_string() + exe_name());
    }
    let previous = std::fs::read_to_string(root.join("current")).ok();
    std::fs::write(root.join("current"), &m.version).map_err(|e| e.to_string())?;
    // keep the version just replaced (a way back), remove anything older
    if let Ok(rd) = std::fs::read_dir(&root) {
        for e in rd.flatten() {
            let n = e.file_name().to_string_lossy().to_string();
            let keep = n == m.version || Some(n.as_str()) == previous.as_deref().map(str::trim) || n == "current";
            if e.path().is_dir() && !keep {
                let _ = std::fs::remove_dir_all(e.path());
            }
        }
    }
    emit("done", done, total);
    Ok(m.version)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn versions_compare_as_numbers() {
        assert!(parse_version("0.10.0") > parse_version("0.9.9"));
        assert_eq!(parse_version("v1.2.3"), (1, 2, 3));
        assert_eq!(parse_version("1.2"), (1, 2, 0));
    }

    #[test]
    fn platform_names_match_the_manifest() {
        let k = platform_key();
        assert!(["darwin-aarch64", "darwin-x86_64", "linux-x86_64", "windows-x86_64", "linux-aarch64"].contains(&k.as_str()), "{k}");
    }

    /// TRIPSHOTS_TEST_SIGNED=<file> (with <file>.sig next to it, from `tauri signer sign`) checks a real signature
    /// against the key in tauri.conf.json, and that one changed byte fails.
    #[test]
    fn signatures_from_the_release_key_verify() {
        let Ok(file) = std::env::var("TRIPSHOTS_TEST_SIGNED") else { return };
        let conf: serde_json::Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let key = conf["plugins"]["updater"]["pubkey"].as_str().unwrap();
        let sig = std::fs::read_to_string(format!("{file}.sig")).unwrap();
        let mut data = std::fs::read(&file).unwrap();
        assert!(verify(key, &sig, &data).is_ok());
        data[0] ^= 1;
        assert!(verify(key, &sig, &data).is_err());
    }

    #[test]
    fn archives_unpack_with_their_permissions() {
        let dir = std::env::temp_dir().join(format!("ts-unpack-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let tgz = dir.join("e.tar.gz");
        {
            let f = std::fs::File::create(&tgz).unwrap();
            let mut t = tar::Builder::new(flate2::write::GzEncoder::new(f, flate2::Compression::fast()));
            let body = b"#!/bin/sh\necho hi\n";
            let mut h = tar::Header::new_gnu();
            h.set_size(body.len() as u64);
            h.set_mode(0o755);
            h.set_cksum();
            t.append_data(&mut h, "tripshots/tripshots", &body[..]).unwrap();
            t.into_inner().unwrap().finish().unwrap();
        }
        unpack(&tgz, &dir.join("out")).unwrap();
        let exe = dir.join("out/tripshots/tripshots");
        assert!(exe.is_file());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(exe.metadata().unwrap().permissions().mode() & 0o111, 0o111);
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
