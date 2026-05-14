import { execFileSync } from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  realpathSync,
  rmSync,
} from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..", "..");
const backendDir = resolve(root, "backend");
const desktopDir = resolve(root, "desktop");
const binariesDir = resolve(desktopDir, "src-tauri", "binaries");
const nodeLibsDir = resolve(desktopDir, "src-tauri", "node-libs");
const isWindows = process.platform === "win32";
const exe = isWindows ? ".exe" : "";

function fallbackTargetTriple() {
  const arch = process.arch === "arm64" ? "aarch64" : "x86_64";
  if (process.platform === "darwin") return `${arch}-apple-darwin`;
  if (process.platform === "win32") return `${arch}-pc-windows-msvc`;
  if (process.platform === "linux") return `${arch}-unknown-linux-gnu`;
  throw new Error(`Unsupported platform for Tauri sidecar staging: ${process.platform}`);
}

function targetTriple() {
  try {
    return execFileSync("rustc", ["--print", "host-tuple"], {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return fallbackTargetTriple();
  }
}

function stageBinary(source, baseName, target) {
  if (!existsSync(source)) {
    throw new Error(`Missing sidecar source: ${source}`);
  }
  const destination = resolve(binariesDir, `${baseName}-${target}${exe}`);
  copyFileSync(source, destination);
  if (!isWindows) chmodSync(destination, 0o755);
  console.log(`staged ${baseName}: ${destination}`);
  return destination;
}

function commandOutput(command, args) {
  return execFileSync(command, args, {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function isSystemDylib(path) {
  return (
    path.startsWith("/usr/lib/") ||
    path.startsWith("/System/Library/Frameworks/")
  );
}

function dylibDeps(binary) {
  const output = commandOutput("otool", ["-L", binary]);
  return output
    .split("\n")
    .slice(1)
    .map((line) => line.trim().split(" ")[0])
    .filter(Boolean)
    .filter((dep) => dep !== binary)
    .filter((dep) => !isSystemDylib(dep));
}

function brewPrefix() {
  try {
    return commandOutput("brew", ["--prefix"]).trim();
  } catch {
    return null;
  }
}

function resolveDylib(dep, loaderPath, homebrewPrefix) {
  if (dep.startsWith("/")) return existsSync(dep) ? dep : null;
  if (!dep.startsWith("@rpath/") && !dep.startsWith("@loader_path/")) return null;

  const name = basename(dep);
  const candidates = [
    resolve(loaderPath, name),
    homebrewPrefix ? resolve(homebrewPrefix, "lib", name) : null,
    homebrewPrefix ? resolve(homebrewPrefix, "opt", "node", "lib", name) : null,
    resolve(dirname(realpathSync(process.execPath)), "..", "lib", name),
  ].filter(Boolean);

  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

function installNameTool(args) {
  try {
    execFileSync("install_name_tool", args, { stdio: "pipe" });
  } catch (error) {
    const message = error.stderr?.toString() || error.message;
    throw new Error(`install_name_tool ${args.join(" ")} failed: ${message}`);
  }
}

function stripBinary(binary) {
  try {
    execFileSync("strip", ["-x", binary], { stdio: "pipe" });
  } catch (error) {
    const message = error.stderr?.toString() || error.message;
    console.warn(`strip skipped for ${binary}: ${message.trim()}`);
  }
}

function adHocSign(binary) {
  try {
    execFileSync("codesign", ["--force", "--sign", "-", binary], {
      stdio: "pipe",
    });
  } catch (error) {
    const message = error.stderr?.toString() || error.message;
    throw new Error(`codesign ${binary} failed: ${message}`);
  }
}

function stageMacNodeDylibs(nodeSidecar) {
  const homebrewPrefix = brewPrefix();
  const staged = new Map();
  const queue = [{ binary: nodeSidecar, loaderPath: dirname(realpathSync(process.execPath)) }];

  rmSync(nodeLibsDir, { force: true, recursive: true });
  mkdirSync(nodeLibsDir, { recursive: true });

  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    for (const dep of dylibDeps(current.binary)) {
      const source = resolveDylib(dep, current.loaderPath, homebrewPrefix);
      if (!source) {
        throw new Error(`Could not resolve macOS dylib dependency: ${dep}`);
      }

      const name = basename(source);
      const destination = resolve(nodeLibsDir, name);
      if (!staged.has(name)) {
        copyFileSync(source, destination);
        chmodSync(destination, 0o755);
        staged.set(name, destination);
        queue.push({ binary: destination, loaderPath: dirname(source) });
      }
    }
  }

  for (const [name, binary] of staged) {
    installNameTool(["-id", `@rpath/${name}`, binary]);
    for (const dep of dylibDeps(binary)) {
      installNameTool(["-change", dep, `@loader_path/${basename(dep)}`, binary]);
    }
    stripBinary(binary);
    adHocSign(binary);
  }

  for (const dep of dylibDeps(nodeSidecar)) {
    installNameTool([
      "-change",
      dep,
      `@executable_path/../Resources/node-libs/${basename(dep)}`,
      nodeSidecar,
    ]);
  }

  stripBinary(nodeSidecar);
  adHocSign(nodeSidecar);
  console.log(`staged macOS Node dylibs: ${nodeLibsDir}`);
}

mkdirSync(binariesDir, { recursive: true });
const target = targetTriple();

stageBinary(
  resolve(backendDir, "dist", `signalrank-backend${exe}`),
  "signalrank-backend",
  target
);
const nodeSidecar = stageBinary(process.execPath, "signalrank-web", target);

if (process.platform === "darwin") {
  stageMacNodeDylibs(nodeSidecar);
}
