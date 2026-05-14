import { spawnSync } from "node:child_process";
import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..", "..");
const backendDir = resolve(root, "backend");

function commandPath(command) {
  const result = spawnSync("command", ["-v", command], {
    shell: true,
    encoding: "utf-8",
  });
  return result.status === 0 ? result.stdout.trim() : "";
}

const pyinstallerArgs = [
  "run",
  "pyinstaller",
  "--name",
  "signalrank-backend",
  "--onefile",
  "--strip",
  "--collect-submodules",
  "api",
  "--collect-submodules",
  "batch",
  "--collect-submodules",
  "domain",
  "--collect-submodules",
  "llm",
  "--collect-data",
  "tls_client",
  "--hidden-import",
  "aiosqlite",
  "--hidden-import",
  "keyring.backends.macOS",
  "--add-data",
  `config${delimiter}config`,
  "--add-data",
  `templates${delimiter}templates`,
  "--add-data",
  `data/fonts${delimiter}data/fonts`,
  "--add-data",
  `ranking/v4/weights.yaml${delimiter}ranking/v4`,
];

const typstPath = commandPath(process.platform === "win32" ? "typst.exe" : "typst");
if (typstPath) {
  pyinstallerArgs.push("--add-binary", `${typstPath}${delimiter}.`);
} else {
  console.warn("typst not found on PATH; resume PDF preview will require system typst");
}

pyinstallerArgs.push("api/desktop_main.py");

const result = spawnSync(
  "uv",
  pyinstallerArgs,
  {
    cwd: backendDir,
    stdio: "inherit",
    env: {
      ...process.env,
      SIGNALRANK_MODE: "desktop",
    },
  }
);

process.exit(result.status ?? 1);
