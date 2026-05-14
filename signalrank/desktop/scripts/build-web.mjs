import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..", "..");
const frontendDir = resolve(root, "frontend");

const result = spawnSync("npm", ["run", "build"], {
  cwd: frontendDir,
  stdio: "inherit",
  env: {
    ...process.env,
    SIGNALRANK_MODE: "desktop",
    NEXT_PUBLIC_SIGNALRANK_MODE: "desktop",
  },
});

if (result.status) process.exit(result.status);

const standaloneDir = resolve(frontendDir, ".next", "standalone");
mkdirSync(standaloneDir, { recursive: true });

const staticSource = resolve(frontendDir, ".next", "static");
const staticTarget = resolve(standaloneDir, ".next", "static");
if (existsSync(staticSource)) {
  rmSync(staticTarget, { recursive: true, force: true });
  cpSync(staticSource, staticTarget, { recursive: true });
}

const publicSource = resolve(frontendDir, "public");
const publicTarget = resolve(standaloneDir, "public");
if (existsSync(publicSource)) {
  rmSync(publicTarget, { recursive: true, force: true });
  cpSync(publicSource, publicTarget, { recursive: true });
}
