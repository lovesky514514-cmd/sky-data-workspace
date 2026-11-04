use serde::Deserialize;
use serde_json::{json, Value};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::{
    fs::{self, OpenOptions},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

#[derive(Clone, Deserialize)]
struct Session {
    base_url: String,
    token: String,
    launch_id: Option<String>,
}

pub struct Runtime {
    pub child: Child,
    session: Session,
}

impl Runtime {
    pub fn launch(binary: &Path, data_dir: &Path) -> Result<Self, String> {
        fs::create_dir_all(data_dir.join("logs")).map_err(|e| e.to_string())?;
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(data_dir.join("logs/desktop-runtime.log"))
            .map_err(|e| e.to_string())?;
        let nonce = uuid::Uuid::new_v4().to_string();
        let mut command = Command::new(binary);
        command
            .args(["--data-dir"])
            .arg(data_dir)
            .args([
                "--launch-id",
                &nonce,
                "--parent-pid",
                &std::process::id().to_string(),
                "serve",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::from(log.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(log));
        #[cfg(windows)]
        command.creation_flags(0x08000000);
        let mut child = command
            .spawn()
            .map_err(|e| format!("无法启动本地运行时：{e}"))?;
        let deadline = Instant::now() + Duration::from_secs(40);
        while Instant::now() < deadline {
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                return Err(format!("运行时提前退出 ({status})，请查看日志。"));
            }
            let info = data_dir.join("runtime.json");
            if let Ok(content) = fs::read_to_string(info) {
                if let Ok(session) = serde_json::from_str::<Session>(&content) {
                    if session.launch_id.as_deref() == Some(&nonce) && valid_session(&session) {
                        let runtime = Self { child, session };
                        if runtime.request("GET", "/api/health", None).is_ok() {
                            return Ok(runtime);
                        }
                        return Err("运行时健康检查失败，请查看日志。".into());
                    }
                }
            }
            thread::sleep(Duration::from_millis(150));
        }
        terminate_tree(&mut child);
        Err("运行时启动超时，请查看日志。".into())
    }

    pub fn connection(&self) -> (String, String) {
        (self.session.base_url.clone(), self.session.token.clone())
    }

    pub fn request(&self, method: &str, path: &str, body: Option<Value>) -> Result<Value, String> {
        let (base, token) = self.connection();
        request(&base, &token, method, path, body)
    }

    pub fn stop(&mut self) {
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(2))
            .build();
        if let Ok(client) = client {
            let _ = client
                .post(format!("{}/api/shutdown", self.session.base_url))
                .bearer_auth(&self.session.token)
                .json(&json!({}))
                .send();
        }
        let deadline = Instant::now() + Duration::from_secs(15);
        while Instant::now() < deadline {
            if self.child.try_wait().ok().flatten().is_some() {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        terminate_tree(&mut self.child);
    }
}

impl Drop for Runtime {
    fn drop(&mut self) {
        self.stop();
    }
}

fn valid_session(session: &Session) -> bool {
    session
        .base_url
        .strip_prefix("http://127.0.0.1:")
        .and_then(|p| p.parse::<u16>().ok())
        .is_some()
        && session.token.len() == 64
        && session.token.chars().all(|c| c.is_ascii_hexdigit())
}

pub fn valid_route(method: &str, path: &str) -> bool {
    matches!(method, "GET" | "POST")
        && path.starts_with("/api/")
        && !path.contains("..")
        && !path.contains(['\\', '#', '\r', '\n'])
        && !path.starts_with("/api/shutdown")
        && path.len() <= 4096
}

pub fn request(
    base: &str,
    token: &str,
    method: &str,
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    if !valid_route(method, path) {
        return Err("不允许的运行时请求".into());
    }
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(600))
        .connect_timeout(Duration::from_secs(3))
        .build()
        .map_err(|e| e.to_string())?;
    let method = reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?;
    let mut builder = client
        .request(method, format!("{base}{path}"))
        .bearer_auth(token);
    if let Some(value) = body {
        builder = builder.json(&value);
    }
    let response = builder
        .send()
        .map_err(|e| format!("本地运行时连接失败：{e}"))?;
    let status = response.status();
    let value: Value = response
        .json()
        .map_err(|_| "运行时响应格式无效".to_string())?;
    if !status.is_success() {
        return Err(value
            .get("message")
            .or_else(|| value.get("error"))
            .and_then(Value::as_str)
            .unwrap_or("运行时请求失败")
            .to_string());
    }
    Ok(value)
}

pub fn locate_binary() -> Result<PathBuf, String> {
    let path = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("无法确定程序位置")?
        .join("sky-data-runtime.exe");
    if path.is_file() {
        return Ok(path);
    }
    #[cfg(debug_assertions)]
    {
        let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("binaries/sky-data-runtime-x86_64-pc-windows-msvc.exe");
        if dev.is_file() {
            return Ok(dev);
        }
    }
    Err("随附的 Python 运行时缺失，请重新安装软件。".into())
}

fn terminate_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill.exe");
        command
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .creation_flags(0x08000000)
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let _ = command.status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn routes_stay_local() {
        assert!(valid_route("GET", "/api/tasks?limit=100"));
        for path in [
            "https://example.com",
            "/api/../secret",
            "/api/shutdown",
            "/api/x#fragment",
        ] {
            assert!(!valid_route("POST", path));
        }
        assert!(!valid_route("DELETE", "/api/tasks"));
    }
}
