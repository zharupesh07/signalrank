import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..", "..");
const backendDir = resolve(root, "backend");
const frontendDir = resolve(root, "frontend");
const appDataDir = resolve(root, ".desktop-data");

mkdirSync(appDataDir, { recursive: true });

const sharedEnv = {
  ...process.env,
  SIGNALRANK_MODE: "desktop",
  SIGNALRANK_APP_DATA_DIR: appDataDir,
  NEXTAUTH_URL: "http://localhost:3000",
  AUTH_URL: "http://localhost:3000",
  BACKEND_URL: "http://localhost:8000",
  NEXT_PUBLIC_SIGNALRANK_MODE: "desktop",
  NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS: "60000",
};

const children = [];

function start(name, command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    env: sharedEnv,
    stdio: ["ignore", "inherit", "inherit"],
  });
  child.on("exit", (code) => {
    if (code && !shuttingDown) {
      console.error(`${name} exited with code ${code}`);
      process.exit(code);
    }
  });
  children.push(child);
}

let shuttingDown = false;
function shutdown() {
  shuttingDown = true;
  for (const child of children) child.kill("SIGTERM");
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
process.on("exit", shutdown);

start("backend", "uv", ["run", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"], backendDir);
start("frontend", "npm", ["run", "dev"], frontendDir);
