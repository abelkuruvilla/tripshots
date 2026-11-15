mod engine;
mod integrate;

use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, State};

#[derive(Default)]
struct AppState {
    engine: Mutex<Option<engine::Running>>,
}

#[derive(Serialize)]
struct EngineState {
    status: String, // ready | missing | error
    info: Option<engine::EngineInfo>,
    error: Option<String>,
    installed_version: Option<String>,
    platform: String,
    app_version: String,
}

fn snapshot(app: &AppHandle, st: &AppState, error: Option<String>) -> EngineState {
    let guard = st.engine.lock().unwrap();
    let info = guard.as_ref().map(|r| r.info.clone());
    EngineState {
        status: if info.is_some() { "ready" } else if error.is_some() { "error" } else { "missing" }.into(),
        info,
        error,
        installed_version: engine::installed(app).map(|(_, v)| v),
        platform: engine::platform_key(),
        app_version: env!("CARGO_PKG_VERSION").into(),
    }
}

fn stop(st: &AppState) {
    if let Some(mut r) = st.engine.lock().unwrap().take() {
        let _ = r.child.kill();
        let _ = r.child.wait();
    }
}

/// Start the engine if it isn't running (or restart it after an install).
#[tauri::command]
async fn engine_start(app: AppHandle, state: State<'_, AppState>, restart: Option<bool>) -> Result<EngineState, String> {
    if restart.unwrap_or(false) {
        stop(&state);
    }
    if state.engine.lock().unwrap().is_some() {
        return Ok(snapshot(&app, &state, None));
    }
    let Some((exe, source)) = engine::locate(&app) else {
        return Ok(snapshot(&app, &state, None));
    };
    let app2 = app.clone();
    let started = tauri::async_runtime::spawn_blocking(move || engine::start(&app2, &exe, &source))
        .await
        .map_err(|e| e.to_string())?;
    match started {
        Ok(r) => {
            *state.engine.lock().unwrap() = Some(r);
            Ok(snapshot(&app, &state, None))
        }
        Err(e) => Ok(snapshot(&app, &state, Some(e))),
    }
}

#[tauri::command]
fn engine_state(app: AppHandle, state: State<'_, AppState>) -> EngineState {
    snapshot(&app, &state, None)
}

/// Download, verify and install the engine for this computer, then (re)start it.
#[tauri::command]
async fn engine_install(app: AppHandle, state: State<'_, AppState>) -> Result<EngineState, String> {
    engine::install(&app).await?;
    if state.engine.lock().unwrap().as_ref().map(|r| r.info.source.as_str()) != Some("dev") {
        stop(&state);
    }
    engine_start(app, state, Some(false)).await
}

#[derive(Serialize)]
struct UpdateInfo {
    available: bool,
    latest: String,
    current: Option<String>,
    notes: Option<String>,
}

#[tauri::command]
async fn engine_check_update(app: AppHandle) -> Result<UpdateInfo, String> {
    let m = engine::fetch_manifest().await?;
    let current = engine::installed(&app).map(|(_, v)| v);
    let available = current.as_deref().map(|c| engine::parse_version(&m.version) > engine::parse_version(c)).unwrap_or(true);
    Ok(UpdateInfo { available, latest: m.version, current, notes: m.notes })
}

fn engine_path(app: &AppHandle, state: &AppState) -> Result<std::path::PathBuf, String> {
    if let Some(r) = state.engine.lock().unwrap().as_ref() {
        return Ok(r.info.path.clone().into());
    }
    engine::locate(app).map(|(p, _)| p).ok_or_else(|| "install the engine first".to_string())
}

#[tauri::command]
fn install_cli(app: AppHandle, state: State<'_, AppState>) -> Result<integrate::CliResult, String> {
    integrate::install_cli(&engine_path(&app, &state)?)
}

#[tauri::command]
fn connect_claude(app: AppHandle, state: State<'_, AppState>) -> Result<integrate::ClaudeResult, String> {
    integrate::connect_claude(&engine_path(&app, &state)?)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            engine_start,
            engine_state,
            engine_install,
            engine_check_update,
            install_cli,
            connect_claude
        ])
        .build(tauri::generate_context!())
        .expect("error while building TripShots");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop(&handle.state::<AppState>());
        }
    });
}
