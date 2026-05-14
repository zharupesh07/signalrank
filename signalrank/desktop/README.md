# SignalRank Desktop

Tauri shell for the single-user local SignalRank app.

This is intentionally Tauri-first instead of Electron to keep the app lighter on
memory. Packaged builds bundle the Python backend and a Node runtime as Tauri
sidecars so users do not need Python, Node, Rust, or Cargo installed.

## Development

```bash
cd signalrank/desktop
npm install
npm run dev
```

The dev command starts:

- FastAPI on `127.0.0.1:8000` with `SIGNALRANK_MODE=desktop`
- Next.js on `127.0.0.1:3000` with desktop UI routing
- Tauri WebView pointed at the Next.js dev server

Desktop data is written to `signalrank/.desktop-data` in development.
Packaged builds write to the OS app data directory and launch backend/web on
random free localhost ports.

## Packaging

```bash
cd signalrank/desktop
npm run build
npm run smoke:packaged
```

The build flow:

1. Packages the backend with PyInstaller and strips symbols where supported.
2. Builds the Next.js app in standalone desktop mode.
3. Stages sidecars under `src-tauri/binaries/` with Tauri target-triple names.
4. Vendors and strips macOS Node dylibs under `src-tauri/node-libs/` for
   packaged web sidecar portability.
5. Runs `tauri build`.

macOS packaging requires Rust/Cargo and Xcode. Windows packaging should be run on
Windows so PyInstaller, Node, and Tauri stage Windows-native sidecars.

Rust/Cargo are not bundled into the final app because they are build-time
toolchains. The shipped app contains the compiled Tauri binary plus the staged
backend/web sidecars; end users should not install Rust, Cargo, Python, or Node.

## macOS Build Machine Setup

Install Rust/Cargo:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustc --version
cargo --version
```

Install Xcode:

1. Install Xcode from the Mac App Store or Apple Developer downloads.
2. Open Xcode once and accept the license/install additional components.
3. Point developer tools at the full Xcode app:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -version
```

The already-installed Command Line Tools are useful, but Tauri/macOS packaging
still expects the full Xcode app for the native app toolchain.

## Windows Build Machine Setup

Build Windows artifacts on Windows:

1. Install Rust with `rustup`.
2. Install Microsoft C++ Build Tools / Visual Studio Build Tools.
3. Ensure Microsoft Edge WebView2 Runtime is present.
4. Run:

```powershell
cd signalrank\desktop
npm install
npm run build
```

The Windows build should produce a Windows-native Tauri app plus Windows-native
PyInstaller backend and Node sidecars. A macOS build will not produce a usable
Windows executable for this app because the sidecars are platform-native.

## Implemented

- `SIGNALRANK_MODE=desktop` uses SQLite by default under the desktop data dir.
- Desktop endpoints expose setup status, provider listing/preferences, local
  session creation, and provider key validation.
- A single local admin user/profile is created automatically.
- OpenRouter, OpenAI, and Anthropic keys are saved to the OS keychain when
  available, with a restricted local fallback file.
- The setup screen is a three-step local wizard: provider key, resume upload,
  and first scan.
- Queue and resume workers run inside the local API process; archival is disabled
  by default.
- The frontend skips signup/login friction in desktop mode and starts at local
  setup/resume onboarding.
- Packaged Tauri builds spawn backend and web sidecars, wait for them to become
  reachable on random localhost ports, and close them when the app exits.
- `npm run smoke:packaged` launches the built macOS app with an isolated temp
  desktop data dir, verifies backend health plus the desktop setup page on the
  random web port, uploads `fixtures/smoke-resume.txt`, and checks parsed
  onboarding roles.

## Still Pending

- Add signing, notarization, and installer metadata.
- Reduce package size further by replacing bundled Node with a smaller runtime
  or a static frontend shell.
- Add CI jobs for macOS and Windows artifacts.
- Run a clean-machine smoke test for OpenRouter setup, scan, ranked jobs, and
  tailored resume generation.
