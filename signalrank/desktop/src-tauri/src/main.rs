use std::process::Command;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use std::{env, path::PathBuf};

use tauri::{Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct DesktopChildren {
    backend: Mutex<Option<CommandChild>>,
    web: Mutex<Option<CommandChild>>,
}

impl DesktopChildren {
    fn kill_all(&self) {
        if let Ok(mut child) = self.backend.lock() {
            if let Some(child) = child.take() {
                kill_process_tree(child.pid());
                let _ = child.kill();
            }
        }
        if let Ok(mut child) = self.web.lock() {
            if let Some(child) = child.take() {
                kill_process_tree(child.pid());
                let _ = child.kill();
            }
        }
    }
}

impl Drop for DesktopChildren {
    fn drop(&mut self) {
        self.kill_all();
    }
}

fn stop_sidecars(app: &tauri::AppHandle) {
    if let Some(children) = app.try_state::<DesktopChildren>() {
        children.kill_all();
    }
}

#[cfg(unix)]
fn child_pids(pid: u32) -> Vec<u32> {
    let output = Command::new("pgrep")
        .args(["-P", &pid.to_string()])
        .output();
    match output {
        Ok(output) if output.status.success() => String::from_utf8_lossy(&output.stdout)
            .lines()
            .filter_map(|line| line.trim().parse::<u32>().ok())
            .collect(),
        _ => Vec::new(),
    }
}

#[cfg(unix)]
fn kill_process_tree(pid: u32) {
    for child_pid in child_pids(pid) {
        kill_process_tree(child_pid);
    }
    let _ = Command::new("kill")
        .args(["-TERM", &pid.to_string()])
        .status();
}

#[cfg(windows)]
fn kill_process_tree(pid: u32) {
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .status();
}

fn free_local_port() -> std::io::Result<u16> {
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_port(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if std::net::TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(150));
    }
    false
}

fn loading_html() -> String {
    r#"<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {
      color-scheme: dark;
      background: #050606;
      color: #e5e7eb;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at center, rgba(38, 211, 97, 0.12), transparent 34rem),
        linear-gradient(180deg, #050606 0%, #0b0d0d 100%);
    }
    main {
      display: grid;
      justify-items: center;
      gap: 22px;
      text-align: center;
    }
    .mark {
      display: flex;
      align-items: center;
      gap: 14px;
      color: #30e873;
      font-size: 28px;
      font-weight: 800;
      letter-spacing: 0.18em;
    }
    .prompt {
      color: #30e873;
      font-size: 31px;
      letter-spacing: 0;
    }
    .spinner {
      width: 46px;
      height: 46px;
      border: 2px solid rgba(229, 231, 235, 0.18);
      border-top-color: #30e873;
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
    }
    .status {
      color: #a1a1aa;
      font-size: 15px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <main>
    <div class="mark"><span class="prompt">&gt;_</span><span>SIGNALRANK</span></div>
    <div class="spinner" aria-label="Loading"></div>
    <div class="status">Starting local services</div>
  </main>
</body>
</html>"#
        .to_string()
}

fn show_loading(window: &tauri::WebviewWindow) -> tauri::Result<()> {
    let html = loading_html();
    window.eval(&format!(
        "document.open();document.write({html:?});document.close();"
    ))
}

fn show_startup_error(window: &tauri::WebviewWindow, message: &str) {
    let escaped = format!("{message:?}");
    let _ = window.eval(&format!(
        "document.querySelector('.spinner')?.remove();\
         const status = document.querySelector('.status');\
         if (status) {{ status.textContent = 'Startup failed: ' + {escaped}; status.style.color = '#f87171'; }}"
    ));
}

fn setup_packaged_sidecars(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    if cfg!(debug_assertions) {
        return Ok(());
    }

    let handle = app.handle().clone();
    let data_dir = env::var("SIGNALRANK_APP_DATA_DIR")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or(handle.path().app_data_dir()?);
    std::fs::create_dir_all(&data_dir)?;

    let backend_port = free_local_port()?;
    let web_port = free_local_port()?;
    let backend_url = format!("http://127.0.0.1:{backend_port}");
    let frontend_url = format!("http://127.0.0.1:{web_port}/desktop-setup");
    let nextauth_url = format!("http://127.0.0.1:{web_port}");
    let server_js = handle
        .path()
        .resource_dir()?
        .join("frontend/.next/standalone/server.js");

    app.manage(DesktopChildren {
        backend: Mutex::new(None),
        web: Mutex::new(None),
    });

    if let Some(window) = handle.get_webview_window("main") {
        show_loading(&window)?;
    }

    tauri::async_runtime::spawn(async move {
        let result = start_packaged_sidecars(
            handle.clone(),
            data_dir,
            backend_port,
            web_port,
            backend_url,
            frontend_url,
            nextauth_url,
            server_js,
        )
        .await;

        if let Err(error) = result {
            eprintln!("[desktop] startup failed: {error}");
            let _ = handle.emit("signalrank-sidecar-exit", "startup");
            if let Some(window) = handle.get_webview_window("main") {
                show_startup_error(&window, &error.to_string());
            }
        }
    });

    Ok(())
}

async fn start_packaged_sidecars(
    handle: tauri::AppHandle,
    data_dir: PathBuf,
    backend_port: u16,
    web_port: u16,
    backend_url: String,
    frontend_url: String,
    nextauth_url: String,
    server_js: PathBuf,
) -> Result<(), Box<dyn std::error::Error>> {
    let (mut backend_rx, backend_child) = handle
        .shell()
        .sidecar("signalrank-backend")?
        .env("SIGNALRANK_MODE", "desktop")
        .env(
            "SIGNALRANK_APP_DATA_DIR",
            data_dir.to_string_lossy().to_string(),
        )
        .env("PORT", backend_port.to_string())
        .spawn()?;
    if let Some(children) = handle.try_state::<DesktopChildren>() {
        if let Ok(mut child) = children.backend.lock() {
            *child = Some(backend_child);
        }
    }
    let backend_handle = handle.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = backend_rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    println!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(status) => {
                    eprintln!("[backend] terminated: {status:?}");
                    let _ = backend_handle.emit("signalrank-sidecar-exit", "backend");
                    break;
                }
                _ => {}
            }
        }
    });

    if !wait_for_port(backend_port, Duration::from_secs(75)) {
        return Err("SignalRank backend did not become ready".into());
    }

    let (mut web_rx, web_child) = handle
        .shell()
        .sidecar("signalrank-web")?
        .args([server_js.to_string_lossy().to_string()])
        .env("HOSTNAME", "127.0.0.1")
        .env("PORT", web_port.to_string())
        .env("BACKEND_URL", backend_url)
        .env("NEXTAUTH_URL", nextauth_url.clone())
        .env("AUTH_URL", nextauth_url)
        .env("AUTH_SECRET", "signalrank-desktop-local-secret")
        .env("NEXTAUTH_SECRET", "signalrank-desktop-local-secret")
        .env("SIGNALRANK_MODE", "desktop")
        .env("NEXT_PUBLIC_SIGNALRANK_MODE", "desktop")
        .spawn()?;
    if let Some(children) = handle.try_state::<DesktopChildren>() {
        if let Ok(mut child) = children.web.lock() {
            *child = Some(web_child);
        }
    }
    let web_handle = handle.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = web_rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    println!("[web] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[web] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(status) => {
                    eprintln!("[web] terminated: {status:?}");
                    let _ = web_handle.emit("signalrank-sidecar-exit", "web");
                    break;
                }
                _ => {}
            }
        }
    });

    if !wait_for_port(web_port, Duration::from_secs(45)) {
        return Err("SignalRank web server did not become ready".into());
    }

    if let Some(window) = handle.get_webview_window("main") {
        window.eval(&format!("window.location.replace({frontend_url:?})"))?;
    }

    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(setup_packaged_sidecars)
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                stop_sidecars(&window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build SignalRank desktop");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            stop_sidecars(app_handle);
        }
    });
}
