//! The engine outside the app: `tripshots` on the command line, and as an MCP server for Claude.

use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::{json, Value};

#[derive(Serialize)]
pub struct CliResult {
    pub path: String,
    pub on_path: bool,
    pub note: String,
}

/// Put `tripshots` on the command line: a link in /usr/local/bin (macOS asks for an administrator password when
/// needed) or ~/.local/bin (Linux), or the engine folder on the user's PATH (Windows).
pub fn install_cli(engine: &Path) -> Result<CliResult, String> {
    #[cfg(unix)]
    {
        let target = PathBuf::from("/usr/local/bin/tripshots");
        let link = |dst: &Path| -> std::io::Result<()> {
            if dst.symlink_metadata().is_ok() {
                std::fs::remove_file(dst)?;
            }
            if let Some(d) = dst.parent() {
                std::fs::create_dir_all(d)?;
            }
            std::os::unix::fs::symlink(engine, dst)
        };
        if link(&target).is_ok() {
            return Ok(CliResult { path: target.display().to_string(), on_path: true, note: String::new() });
        }
        if cfg!(target_os = "macos") {
            let q = |s: &Path| s.display().to_string().replace('\'', "'\\''");
            let script = format!(
                "do shell script \"mkdir -p /usr/local/bin && ln -sf '{}' '{}'\" with administrator privileges",
                q(engine),
                q(&target)
            );
            let ok = std::process::Command::new("osascript").args(["-e", &script]).status().is_ok_and(|s| s.success());
            if ok {
                return Ok(CliResult { path: target.display().to_string(), on_path: true, note: String::new() });
            }
        }
        let home = dirs::home_dir().ok_or("no home folder")?;
        let local = home.join(".local").join("bin").join("tripshots");
        link(&local).map_err(|e| format!("could not link {}: {e}", local.display()))?;
        let dir = local.parent().unwrap().display().to_string();
        let on = std::env::var("PATH").unwrap_or_default().split(':').any(|p| p == dir);
        Ok(CliResult {
            path: local.display().to_string(),
            on_path: on,
            note: if on { String::new() } else { format!("add {dir} to your PATH") },
        })
    }
    #[cfg(windows)]
    {
        use winreg::enums::*;
        let dir = engine.parent().ok_or("no engine folder")?.display().to_string();
        let env = winreg::RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey_with_flags("Environment", KEY_READ | KEY_WRITE)
            .map_err(|e| e.to_string())?;
        let cur: String = env.get_value("Path").unwrap_or_default();
        let parts: Vec<&str> = cur.split(';').filter(|p| !p.is_empty() && !p.to_lowercase().contains("tripshots")).collect();
        let new = parts.into_iter().chain(std::iter::once(dir.as_str())).collect::<Vec<_>>().join(";");
        env.set_value("Path", &new).map_err(|e| e.to_string())?;
        Ok(CliResult { path: dir, on_path: true, note: "open a new terminal to use it".into() })
    }
}

#[derive(Serialize)]
pub struct ClaudeResult {
    pub desktop_config: String,
    pub claude_code_command: String,
}

/// Add TripShots to Claude Desktop's MCP servers (keeps everything else in the file, with a backup), and give the
/// one-line command for Claude Code.
pub fn connect_claude(engine: &Path) -> Result<ClaudeResult, String> {
    let cfg = dirs::config_dir().ok_or("no config folder")?.join("Claude").join("claude_desktop_config.json");
    let mut v: Value = if cfg.exists() {
        let text = std::fs::read_to_string(&cfg).map_err(|e| e.to_string())?;
        let parsed = serde_json::from_str(&text)
            .map_err(|_| format!("{} isn't valid JSON: not changed", cfg.display()))?;
        std::fs::write(cfg.with_extension("json.bak"), text).map_err(|e| e.to_string())?;
        parsed
    } else {
        json!({})
    };
    if !v.is_object() {
        return Err(format!("{} isn't a JSON object: not changed", cfg.display()));
    }
    let servers = v.as_object_mut().unwrap().entry("mcpServers").or_insert_with(|| json!({}));
    servers
        .as_object_mut()
        .ok_or("mcpServers isn't an object: not changed")?
        .insert("tripshots".into(), json!({"command": engine.display().to_string(), "args": ["mcp"]}));
    if let Some(d) = cfg.parent() {
        std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
    }
    std::fs::write(&cfg, serde_json::to_string_pretty(&v).unwrap()).map_err(|e| e.to_string())?;
    Ok(ClaudeResult {
        desktop_config: cfg.display().to_string(),
        claude_code_command: format!("claude mcp add tripshots -- \"{}\" mcp", engine.display()),
    })
}
