#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod runtime;

use runtime::Runtime;
use serde::Serialize;
use serde_json::{json, Value};
use std::{fs, path::PathBuf, sync::Mutex};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Emitter, Manager, State};

#[derive(Default)]
struct DesktopState {
    runtime: Option<Runtime>,
    error: Option<String>,
}
#[derive(Clone, Serialize)]
struct Bootstrap {
    state: String,
    error: Option<String>,
    version: &'static str,
}

#[tauri::command]
fn hide_to_tray(app: tauri::AppHandle) -> Result<(), String> {
    app.get_webview_window("main")
        .ok_or("主窗口不存在")?
        .hide()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn desktop_bootstrap(state: State<'_, Mutex<DesktopState>>) -> Bootstrap {
    let guard = state.lock().unwrap();
    Bootstrap {
        state: if guard.runtime.is_some() {
            "ready"
        } else if guard.error.is_some() {
            "error"
        } else {
            "starting"
        }
        .into(),
        error: guard.error.clone(),
        version: env!("CARGO_PKG_VERSION"),
    }
}

#[tauri::command]
async fn api_request(
    state: State<'_, Mutex<DesktopState>>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    let (base, token) = state
        .lock()
        .map_err(|_| "运行时状态不可用")?
        .runtime
        .as_ref()
        .ok_or("运行时尚未就绪")?
        .connection();
    tauri::async_runtime::spawn_blocking(move || {
        runtime::request(&base, &token, &method, &path, body)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn save_export(
    app: tauri::AppHandle,
    state: State<'_, Mutex<DesktopState>>,
    task_id: String,
    format: String,
) -> Result<String, String> {
    let (base, token) = state
        .lock()
        .map_err(|_| "状态不可用")?
        .runtime
        .as_ref()
        .ok_or("运行时尚未就绪")?
        .connection();
    let folder = app
        .path()
        .download_dir()
        .map_err(|e| e.to_string())?
        .join("SKY Data Workspace");
    tauri::async_runtime::spawn_blocking(move || {
        if !matches!(format.as_str(), "xlsx" | "csv" | "json" | "sqlite") {
            return Err("导出格式无效".into());
        }
        let meta = runtime::request(
            &base,
            &token,
            "POST",
            if format == "sqlite" {
                "/api/backup"
            } else {
                "/api/tasks/export"
            },
            Some(if format == "sqlite" {
                json!({})
            } else {
                json!({"task_id":task_id,"format":format})
            }),
        )?;
        let id = meta["export_id"].as_str().ok_or("导出标识缺失")?;
        let name = meta["filename"].as_str().ok_or("文件名缺失")?;
        if name.contains(['/', '\\', ':']) || name.contains("..") || !name.starts_with("SKY_") {
            return Err("导出文件名无效".into());
        }
        let bytes = reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(std::time::Duration::from_secs(600))
            .build()
            .map_err(|e| e.to_string())?
            .get(format!("{base}/api/exports/{id}"))
            .bearer_auth(token)
            .send()
            .map_err(|e| e.to_string())?
            .error_for_status()
            .map_err(|e| e.to_string())?
            .bytes()
            .map_err(|e| e.to_string())?;
        if bytes.len() > 128 * 1024 * 1024 {
            return Err("导出文件超过大小限制".into());
        }
        fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
        let output = folder.join(name);
        use std::io::Write;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&output)
            .map_err(|e| e.to_string())?;
        file.write_all(&bytes).map_err(|e| e.to_string())?;
        Ok(output.to_string_lossy().into_owned())
    })
    .await
    .map_err(|e| e.to_string())?
}

fn headless_check(args: &[String]) -> Result<(), String> {
    let value = |flag: &str| -> Result<PathBuf, String> {
        args.iter()
            .position(|v| v == flag)
            .and_then(|i| args.get(i + 1))
            .map(PathBuf::from)
            .ok_or(format!("缺少 {flag}"))
    };
    let output = value("--report")?;
    let data = value("--data-dir")?;
    let binary = value("--runtime").or_else(|_| runtime::locate_binary())?;
    let mut runtime = Runtime::launch(&binary, &data)?;
    let health = runtime.request("GET", "/api/health", None)?;
    let ai = runtime.request("GET", "/api/ai/status", None)?;
    let kb = runtime.request(
        "POST",
        "/api/knowledge/search",
        Some(json!({"query":"PDF OCR"})),
    )?;
    let task = runtime.request("POST", "/api/tasks", Some(json!({
        "name":"本机构建链路检查","urls":["https://www.python.org/downloads/"],"fields":[],"interval_seconds":null
    })))?;
    let tasks = runtime.request("GET", "/api/tasks", None)?;
    let id = task["task_id"].as_str().ok_or("任务未持久化")?;
    runtime.request(
        "POST",
        "/api/tasks/action",
        Some(json!({"task_id":id,"action":"delete"})),
    )?;
    runtime.stop();
    let stopped = runtime
        .child
        .try_wait()
        .map_err(|e| e.to_string())?
        .is_some();
    let persisted = tasks["tasks"]
        .as_array()
        .map(|v| v.iter().any(|t| t["task_id"] == id))
        .unwrap_or(false);
    let knowledge_matched = kb["results"]
        .as_array()
        .map(|v| !v.is_empty())
        .unwrap_or(false);
    let passed = health["runtime"] == "running" && stopped && persisted && knowledge_matched;
    let report = json!({"desktop_window_created":false,"health":health,"ai":ai,"knowledge":kb,
        "task_persistence":persisted,"runtime_stopped":stopped,"passed":passed});
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    fs::write(output, serde_json::to_vec_pretty(&report).unwrap()).map_err(|e| e.to_string())?;
    if passed {
        Ok(())
    } else {
        Err("后台链路检查失败".into())
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--headless-check") {
        if headless_check(&args).is_err() {
            std::process::exit(1);
        }
        return;
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .manage(Mutex::new(DesktopState::default()))
        .invoke_handler(tauri::generate_handler![
            desktop_bootstrap,
            api_request,
            save_export,
            hide_to_tray,
            quit_app
        ])
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "显示工作台", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出程序", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("SKY 数据采集工作台")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let result = runtime::locate_binary().and_then(|binary| {
                    let data = handle.path().app_data_dir().map_err(|e| e.to_string())?;
                    Runtime::launch(&binary, &data)
                });
                let state = handle.state::<Mutex<DesktopState>>();
                let mut guard = state.lock().unwrap();
                match result {
                    Ok(owner) => guard.runtime = Some(owner),
                    Err(error) => guard.error = Some(error),
                };
                let _ = handle.emit("runtime-ready", ());
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("无法初始化 SKY Data Workspace")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(mut owner) = app
                    .state::<Mutex<DesktopState>>()
                    .lock()
                    .unwrap()
                    .runtime
                    .take()
                {
                    owner.stop();
                }
            }
        });
}
