import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const appBinary = resolve(
  "src-tauri",
  "target",
  "release",
  "bundle",
  "macos",
  "SignalRank.app",
  "Contents",
  "MacOS",
  "signalrank-desktop"
);
const fixtureResume = resolve("fixtures", "smoke-resume.txt");

if (!existsSync(appBinary)) {
  console.error(`Missing packaged app binary: ${appBinary}`);
  process.exit(1);
}
if (!existsSync(fixtureResume)) {
  console.error(`Missing smoke resume fixture: ${fixtureResume}`);
  process.exit(1);
}

const appDataDir = mkdtempSync(resolve(tmpdir(), "signalrank-packaged-smoke-"));

const child = spawn(appBinary, {
  stdio: ["ignore", "pipe", "pipe"],
  env: {
    ...process.env,
    SIGNALRANK_APP_DATA_DIR: appDataDir,
  },
});

let output = "";
let webUrl = "";
let backendUrl = "";
let desktopSetupHealthy = false;

function collect(chunk) {
  const text = chunk.toString();
  output += text;
  const localMatch = text.match(/Local:\s+(http:\/\/127\.0\.0\.1:\d+)/);
  if (localMatch) webUrl = localMatch[1];
  const backendMatch = text.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);
  if (backendMatch) backendUrl = backendMatch[1];
}

child.stdout.on("data", collect);
child.stderr.on("data", collect);

async function waitForReady() {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    let backendHealthy = false;
    if (backendUrl) {
      try {
        const response = await fetch(`${backendUrl}/health`);
        backendHealthy = response.ok;
      } catch {
      }
    }

    if (webUrl) {
      try {
        const response = await fetch(`${webUrl}/desktop-setup`);
        if (response.ok) desktopSetupHealthy = true;
      } catch {
      }
    }

    if (backendHealthy && desktopSetupHealthy) return;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 500));
  }

  throw new Error(
    `Packaged app did not become ready. webUrl=${webUrl || "unknown"} backendUrl=${backendUrl || "unknown"}`
  );
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`${options.method ?? "GET"} ${url} failed ${response.status}: ${text}`);
  }
  return text ? JSON.parse(text) : null;
}

async function textFetch(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`${options.method ?? "GET"} ${url} failed ${response.status}: ${text}`);
  }
  return { response, text };
}

async function waitForRun(runId, token) {
  const deadline = Date.now() + 90_000;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await jsonFetch(`${backendUrl}/api/runs/${runId}/status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (["success", "completed", "failed", "cancelled", "timed_out"].includes(latest.status)) break;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 1000));
  }
  if (!latest) throw new Error("Run status was never returned");
  if (!["success", "completed"].includes(latest.status)) {
    throw new Error(`Run ${runId} ended with ${latest.status}: ${latest.error ?? "no error"}`);
  }
  return latest;
}

async function verifyPageRoutes() {
  for (const route of ["/desktop-setup", "/dashboard", "/jobs", "/tracker", "/settings"]) {
    const { text } = await textFetch(`${webUrl}${route}`);
    if (!text.includes("SignalRank") && !text.includes("SIGNALRANK")) {
      throw new Error(`Page ${route} did not render SignalRank shell`);
    }
  }
}

async function verifyResumeUpload() {
  const session = await jsonFetch(`${backendUrl}/api/desktop/session`, {
    method: "POST",
  });
  const token = session.access_token;
  if (!token) throw new Error("Desktop session response did not include access_token");

  const resumeText = readFileSync(fixtureResume, "utf-8");
  const form = new FormData();
  form.set(
    "file",
    new Blob([resumeText], { type: "text/plain" }),
    "smoke-resume.txt"
  );

  const upload = await jsonFetch(`${backendUrl}/api/onboarding/resume`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!upload.extracted?.skills?.length) {
    throw new Error("Resume upload did not return extracted skills");
  }

  const deadline = Date.now() + 30_000;
  let parsed = null;
  while (Date.now() < deadline) {
    parsed = await jsonFetch(`${backendUrl}/api/onboarding/parsed`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!parsed.parsing) break;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 500));
  }
  if (!parsed || parsed.parsing) {
    throw new Error("Resume parsing did not complete during packaged smoke");
  }

  const roles = parsed.prefill?.target_roles ?? [];
  if (!roles.some((role) => String(role).toLowerCase().includes("platform"))) {
    throw new Error(`Parsed resume roles did not include a platform role: ${roles.join(", ")}`);
  }

  const status = await jsonFetch(`${backendUrl}/api/desktop/status`);
  if (!status.resume_uploaded) {
    throw new Error("Desktop status did not report resume_uploaded after upload");
  }

  await jsonFetch(`${backendUrl}/api/onboarding/refine`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question_id: "onboarding_complete", answer: "true" }),
  });

  return { roles, token };
}

async function verifyDesktopApis(token) {
  const providers = await jsonFetch(`${backendUrl}/api/desktop/providers`);
  if (!providers.providers?.some((provider) => provider.id === "openrouter")) {
    throw new Error("Provider list did not include OpenRouter");
  }

  const templates = await jsonFetch(`${backendUrl}/api/resume/templates`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!templates.templates?.length) {
    throw new Error("Resume templates endpoint returned no templates");
  }

  const preview = await jsonFetch(`${backendUrl}/api/resume/preview`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ template: templates.templates[0], debug: true }),
  });
  if (!preview.pdf_size || preview.pdf_size < 1000) {
    throw new Error(`Resume preview did not produce a PDF: ${preview.pdf_size}`);
  }

  const run = await jsonFetch(`${backendUrl}/api/runs/rank-existing`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ mode: "quick" }),
  });
  const completed = await waitForRun(run.run_id, token);

  const jobs = await jsonFetch(`${backendUrl}/api/jobs?limit=10`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!Array.isArray(jobs.jobs)) {
    throw new Error("Jobs endpoint did not return a jobs array");
  }

  const created = await jsonFetch(`${backendUrl}/api/applications`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      company: "Smoke Test Co",
      title: "Platform Engineer",
      status: "interested",
      notes: "packaged smoke",
      priority: "P2",
    }),
  });
  if (!created.id) throw new Error("Application create did not return an id");

  await jsonFetch(`${backendUrl}/api/applications/${created.id}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ status: "applied", notes: "updated packaged smoke" }),
  });

  const apps = await jsonFetch(`${backendUrl}/api/applications`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!apps.applications?.some((app) => app.id === created.id && app.status === "applied")) {
    throw new Error("Application update was not visible in tracker list");
  }

  const stats = await jsonFetch(`${backendUrl}/api/applications/stats`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (typeof stats.total !== "number") {
    throw new Error("Application stats did not return total");
  }

  await textFetch(`${backendUrl}/api/applications/${created.id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });

  return completed;
}

function cleanupProcessTree() {
  if (!child.pid) return;
  const ps = spawnSync("ps", ["-axo", "pid=,ppid=,command="], {
    encoding: "utf-8",
  });
  if (ps.status !== 0) return;
  const rows = ps.stdout
    .trim()
    .split("\n")
    .map((line) => {
      const match = line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/);
      return match
        ? { pid: Number(match[1]), ppid: Number(match[2]), command: match[3] }
        : null;
    })
    .filter(Boolean);
  const childrenByParent = new Map();
  for (const row of rows) {
    if (!childrenByParent.has(row.ppid)) childrenByParent.set(row.ppid, []);
    childrenByParent.get(row.ppid).push(row.pid);
  }
  const toKill = [];
  const visit = (pid) => {
    for (const childPid of childrenByParent.get(pid) ?? []) {
      visit(childPid);
      toKill.push(childPid);
    }
  };
  visit(child.pid);
  toKill.push(child.pid);
  for (const pid of toKill) {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
    }
  }
}

try {
  await waitForReady();
  await verifyPageRoutes();
  const { roles, token } = await verifyResumeUpload();
  const run = await verifyDesktopApis(token);
  console.log(`packaged-app-ready ${webUrl}/desktop-setup`);
  console.log(`resume-upload-ready roles=${roles.slice(0, 3).join(", ")}`);
  console.log(`scan-ready status=${run.status} scored=${run.scored_count ?? 0}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  console.error(output.slice(-4000));
  process.exitCode = 1;
} finally {
  cleanupProcessTree();
}
