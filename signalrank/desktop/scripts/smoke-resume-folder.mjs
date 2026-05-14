import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(scriptDir, "..");
const appBinary = resolve(
  desktopDir,
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

function findResumesDir() {
  if (process.env.SIGNALRANK_RESUME_DIR) {
    return resolve(process.env.SIGNALRANK_RESUME_DIR);
  }
  let cursor = desktopDir;
  for (let i = 0; i < 10; i += 1) {
    const direct = resolve(cursor, "resumes");
    if (existsSync(direct)) return direct;
    if (basename(cursor) === ".worktrees") {
      const root = resolve(cursor, "..", "resumes");
      if (existsSync(root)) return root;
    }
    const parent = resolve(cursor, "..");
    if (parent === cursor) break;
    cursor = parent;
  }
  throw new Error("Could not find resumes directory; set SIGNALRANK_RESUME_DIR");
}

if (!existsSync(appBinary)) {
  console.error(`Missing packaged app binary: ${appBinary}`);
  process.exit(1);
}

const resumesDir = findResumesDir();
const pdfs = readdirSync(resumesDir)
  .filter((name) => name.toLowerCase().endsWith(".pdf"))
  .sort()
  .map((name) => resolve(resumesDir, name));

if (pdfs.length === 0) {
  console.error(`No PDFs found in ${resumesDir}`);
  process.exit(1);
}

const appDataDir = mkdtempSync(resolve(tmpdir(), "signalrank-resume-folder-smoke-"));
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
    let webHealthy = false;
    if (backendUrl) {
      try {
        backendHealthy = (await fetch(`${backendUrl}/health`)).ok;
      } catch {
      }
    }
    if (webUrl) {
      try {
        webHealthy = (await fetch(`${webUrl}/desktop-setup`)).ok;
      } catch {
      }
    }
    if (backendHealthy && webHealthy) return;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 500));
  }
  throw new Error(`Packaged app did not become ready. webUrl=${webUrl || "unknown"} backendUrl=${backendUrl || "unknown"}`);
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`${options.method ?? "GET"} ${url} failed ${response.status}: ${text}`);
  }
  return text ? JSON.parse(text) : null;
}

async function waitForRun(runId, token) {
  const deadline = Date.now() + 120_000;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await jsonFetch(`${backendUrl}/api/runs/${runId}/status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (["success", "completed", "failed", "cancelled", "timed_out"].includes(latest.status)) break;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 1000));
  }
  if (!latest) throw new Error(`Run ${runId} status was never returned`);
  if (!["success", "completed"].includes(latest.status)) {
    throw new Error(`Run ${runId} ended with ${latest.status}: ${latest.error ?? "no error"}`);
  }
  return latest;
}

async function waitForParsed(token) {
  const deadline = Date.now() + 120_000;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await jsonFetch(`${backendUrl}/api/onboarding/parsed`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!latest.parsing) return latest;
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 1000));
  }
  throw new Error("Resume parsing did not complete");
}

async function seedJobs(token) {
  const jobs = [
    {
      title: "AI Platform Engineer",
      company: "SignalRank Fixture",
      location: "Remote, IN",
      job_url: "https://fixtures.signalrank.local/jobs/ai-platform-engineer",
      date_posted: "2026-05-14",
      description: "Build production AI platforms with Python, Kubernetes, Terraform, CI/CD, observability, LLM applications, retrieval systems, and MLOps workflows.",
    },
    {
      title: "Machine Learning Engineer",
      company: "SignalRank Fixture",
      location: "Bengaluru, IN",
      job_url: "https://fixtures.signalrank.local/jobs/machine-learning-engineer",
      date_posted: "2026-05-14",
      description: "Own model training, feature engineering, Python services, ML evaluation, deployment, experiment tracking, and model monitoring for applied machine learning products.",
    },
    {
      title: "SAP SD Consultant",
      company: "SignalRank Fixture",
      location: "Pune, IN",
      job_url: "https://fixtures.signalrank.local/jobs/sap-sd-consultant",
      date_posted: "2026-05-14",
      description: "Configure SAP SD, OTC processes, pricing, billing, S/4HANA integrations, stakeholder workshops, testing, rollout support, and functional documentation.",
    },
    {
      title: "Network Automation Engineer",
      company: "SignalRank Fixture",
      location: "Mumbai, IN",
      job_url: "https://fixtures.signalrank.local/jobs/network-automation-engineer",
      date_posted: "2026-05-14",
      description: "Automate network infrastructure using Python, Ansible, cloud networking, routing, firewalls, monitoring, scripting, and infrastructure reliability practices.",
    },
    {
      title: "Emerging Technologies Engineer",
      company: "SignalRank Fixture",
      location: "Gurugram, IN",
      job_url: "https://fixtures.signalrank.local/jobs/emerging-technologies-engineer",
      date_posted: "2026-05-14",
      description: "Prototype blockchain, IoT, cloud, generative AI, R&D platforms, innovation labs, enterprise pilots, and emerging technology solutions for business teams.",
    },
  ];

  for (const job of jobs) {
    await jsonFetch(`${backendUrl}/api/jobs/ingest/confirm`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(job),
    });
  }
}

async function uploadResume(pdfPath, token) {
  const form = new FormData();
  form.set(
    "file",
    new Blob([readFileSync(pdfPath)], { type: "application/pdf" }),
    basename(pdfPath)
  );
  const upload = await jsonFetch(`${backendUrl}/api/onboarding/resume`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!upload.extracted?.skills?.length) {
    throw new Error(`${basename(pdfPath)} upload returned no extracted skills`);
  }
  return upload;
}

async function verifyPreview(token) {
  const templates = await jsonFetch(`${backendUrl}/api/resume/templates`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const template = templates.templates?.[0];
  if (!template) throw new Error("Resume templates endpoint returned no templates");
  const preview = await jsonFetch(`${backendUrl}/api/resume/preview`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ template, debug: true }),
  });
  if (!preview.pdf_size || preview.pdf_size < 1000) {
    throw new Error(`Resume preview did not produce a usable PDF: ${preview.pdf_size}`);
  }
  const pageCount = preview.validation?.page_count;
  if (pageCount !== 1) {
    throw new Error(`Resume preview should be one page, got ${pageCount}`);
  }
  return preview;
}

const expectedEditors = {
  "Example_Candidate_Resume_V2_2.pdf": {
    position: "Senior AI Platform Engineer",
    location: "Pune",
    linkedin: "example-candidate",
    github: "examplecandidate",
    firstCompany: "Fractal Analytics",
  },
  "rohan_high_quality_resume.pdf": {
    position: "QA Automation Engineer",
    location: "Bangalore, India",
    linkedin: "rohan-raut-286406239",
    firstCompany: "Kaplan India Pvt. Ltd.",
  },
  "rohan_optimized_resume.pdf": {
    position: "QA Automation Engineer",
    location: "Bangalore, India",
    linkedin: "rohan-raut-286406239",
    firstCompany: "Kaplan India Pvt. Ltd.",
  },
};

async function verifyResumeEditor(name, token) {
  const expected = expectedEditors[name];
  if (!expected) return;
  const profile = await jsonFetch(`${backendUrl}/api/profile`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const editor = profile.resume_editor ?? {};
  for (const [field, value] of Object.entries(expected)) {
    if (field === "firstCompany") continue;
    if (!String(editor[field] ?? "").includes(value)) {
      throw new Error(`${name} resume_editor.${field} expected ${value}, got ${editor[field] ?? ""}`);
    }
  }
  const firstCompany = editor.experiences?.[0]?.company ?? "";
  if (expected.firstCompany && firstCompany !== expected.firstCompany) {
    throw new Error(`${name} first company expected ${expected.firstCompany}, got ${firstCompany}`);
  }
}

async function completeOnboarding(token) {
  await jsonFetch(`${backendUrl}/api/onboarding/refine`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question_id: "onboarding_complete", answer: "true" }),
  });
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
      return match ? { pid: Number(match[1]), ppid: Number(match[2]) } : null;
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
  const status = await jsonFetch(`${backendUrl}/api/desktop/status`);
  if (!status.provider_configured) {
    throw new Error("No desktop LLM provider is configured. Add a provider key before running this smoke.");
  }
  const session = await jsonFetch(`${backendUrl}/api/desktop/session`, { method: "POST" });
  const token = session.access_token;
  if (!token) throw new Error("Desktop session response did not include access_token");

  await seedJobs(token);

  const results = [];
  const failures = [];
  for (const pdfPath of pdfs) {
    const name = basename(pdfPath);
    try {
      const upload = await uploadResume(pdfPath, token);
      const parsed = await waitForParsed(token);
      await verifyResumeEditor(name, token);
      await completeOnboarding(token);
      const preview = await verifyPreview(token);
      const run = await jsonFetch(`${backendUrl}/api/runs/rank-existing`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ mode: "quick" }),
      });
      const completed = await waitForRun(run.run_id, token);
      const jobs = await jsonFetch(`${backendUrl}/api/jobs?limit=5`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!Array.isArray(jobs.jobs) || jobs.jobs.length === 0) {
        throw new Error(`${name} produced no ranked jobs`);
      }
      const roles = parsed.prefill?.target_roles ?? [];
      const topJob = jobs.jobs[0];
      results.push({
        name,
        skills: upload.extracted.skills.length,
        roles: roles.slice(0, 2).join("|") || "n/a",
        previewBytes: preview.pdf_size,
        scored: completed.scored_count ?? completed.job_count ?? 0,
        top: `${topJob.title ?? "Untitled"} @ ${topJob.company ?? "Unknown"}`,
      });
      console.log(`resume-ok ${name} skills=${upload.extracted.skills.length} scored=${completed.scored_count ?? completed.job_count ?? 0} top=${topJob.title ?? "Untitled"}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failures.push({ name, message });
      console.log(`resume-fail ${name} ${message}`);
    }
  }

  console.log(`resume-folder-smoke-ready ok=${results.length} failed=${failures.length} dir=${resumesDir}`);
  if (failures.length) {
    throw new Error(`Resume smoke failures: ${failures.map((failure) => `${failure.name}: ${failure.message}`).join("; ")}`);
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  console.error(output.slice(-5000));
  process.exitCode = 1;
} finally {
  cleanupProcessTree();
}
