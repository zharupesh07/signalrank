"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { X, Terminal, RefreshCw, Trash2, Download, Upload, Activity, Server } from "lucide-react";
import { useDevMode } from "./dev-mode-provider";
import { useToast } from "./toast";
import { useTheme } from "./theme-provider";
import { ChipSelect } from "./chip-select";
import { api } from "@/lib/api";
import type { Profile } from "@/types";

type Tab = "profile" | "ranking" | "runs" | "debug";

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile & Search" },
  { key: "ranking", label: "Ranking & Scoring" },
  { key: "runs", label: "Run Controls" },
  { key: "debug", label: "Debug & System" },
];

const ROLE_OPTIONS = [
  "AI Platform Engineer",
  "ML Platform Engineer",
  "MLOps",
  "LLMOps",
  "GenAI",
  "Agentic Systems",
  "AI Infrastructure",
  "Forward Deployed Engineer",
  "Developer Productivity Engineer",
  "Machine Learning Engineer",
  "ML Engineer",
  "Data Scientist",
  "AI Engineer",
  "MLOps Engineer",
  "Data Engineer",
  "Platform Engineer",
  "Backend Engineer",
  "Software Engineer",
  "Research Engineer",
  "Applied Scientist",
  "NLP Engineer",
  "Computer Vision Engineer",
  "Deep Learning Engineer",
  "GenAI Engineer",
  "LLM Engineer",
  "Full Stack Engineer",
];

const LOCATION_OPTIONS = [
  "Bangalore",
  "Hyderabad",
  "Mumbai",
  "Pune",
  "Delhi NCR",
  "Chennai",
  "Remote",
  "India",
  "Gurgaon",
  "Noida",
];

const BLOCKLIST_OPTIONS = [
  "Intern",
  "Trainee",
  "Fresher",
  "Junior",
  "Associate",
  "Lead",
  "Manager",
  "Director",
  "VP",
  "Head",
  "Chief",
  "Principal",
  "Staff",
  "Consultant",
  "Freelance",
  "Part-time",
];

const DEFAULTS = {
  targetRoles: ["AI Platform Engineer", "ML Platform Engineer", "MLOps", "LLMOps", "GenAI", "Agentic Systems", "AI Infrastructure", "Forward Deployed Engineer", "Developer Productivity Engineer"],
  preferredLocations: ["Pune", "Bangalore", "Remote"],
  titleBlocklist: ["Intern", "Trainee", "Fresher", "Junior"],
  minYoe: "3",
  maxYoe: "12",
  targetLpa: "60",
  recencyHours: 168,
};

const sectionCls = "space-y-4";
const labelCls = "text-xs font-semibold text-muted-foreground uppercase tracking-wide";
const inputCls =
  "w-full bg-input border border-border px-3 py-1.5 text-xs text-foreground outline-none focus:border-primary transition-colors";
const btnCls =
  "flex items-center gap-2 px-3 py-2 text-xs border border-border text-muted-foreground hover:border-primary hover:text-primary transition-colors uppercase tracking-wider";
const btnPrimaryCls =
  "flex items-center gap-2 px-4 py-2.5 text-xs border border-primary/50 text-primary hover:bg-primary hover:text-background hover:border-primary transition-all duration-150 uppercase tracking-widest font-bold";

function formatHours(h: number): string {
  if (h < 24) return `${h}h`;
  if (h < 168) return `${Math.round(h / 24)}d`;
  if (h < 720) return `${Math.round(h / 168)}w`;
  return `${Math.round(h / 720)}mo`;
}

const HOUR_STOPS = [6, 12, 24, 48, 72, 168, 336, 720];

export default function DevPanel() {
  const { isDevPanelOpen, closeDevPanel } = useDevMode();
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();
  const { theme, toggleTheme } = useTheme();

  const [tab, setTab] = useState<Tab>("profile");
  const [loading, setLoading] = useState(false);

  const [targetRoles, setTargetRoles] = useState<string[]>(DEFAULTS.targetRoles);
  const [preferredLocations, setPreferredLocations] = useState<string[]>(DEFAULTS.preferredLocations);
  const [customSearchQueries, setCustomSearchQueries] = useState<string[]>([]);
  const [minYoe, setMinYoe] = useState(DEFAULTS.minYoe);
  const [maxYoe, setMaxYoe] = useState(DEFAULTS.maxYoe);
  const [targetLpa, setTargetLpa] = useState(DEFAULTS.targetLpa);
  const [titleBlocklist, setTitleBlocklist] = useState<string[]>(DEFAULTS.titleBlocklist);
  const [recencyHours, setRecencyHours] = useState(DEFAULTS.recencyHours);

  const [apiUrl, setApiUrl] = useState(() =>
    typeof window !== "undefined" ? localStorage.getItem("signalrank-api-url") || "" : ""
  );
  const [pollingInterval, setPollingInterval] = useState(() =>
    typeof window !== "undefined" ? localStorage.getItem("signalrank-poll-interval") || "3000" : "3000"
  );
  const [debugLog, setDebugLog] = useState(() =>
    typeof window !== "undefined" ? localStorage.getItem("signalrank-debug-log") === "true" : false
  );
  const [healthStatus, setHealthStatus] = useState<string | null>(null);
  const [lastApiResponse, setLastApiResponse] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    if (!isDevPanelOpen || !token) return;
    setLoading(true);
    api.profile
      .get(token)
      .then((p: Profile) => {
        setTargetRoles(p.target_roles?.length ? p.target_roles : DEFAULTS.targetRoles);
        setPreferredLocations(p.preferred_locations?.length ? p.preferred_locations : DEFAULTS.preferredLocations);
        setCustomSearchQueries(p.custom_search_queries ?? []);
        setMinYoe(p.min_yoe != null ? String(p.min_yoe) : DEFAULTS.minYoe);
        setMaxYoe(p.max_yoe != null ? String(p.max_yoe) : DEFAULTS.maxYoe);
        setTargetLpa(p.target_lpa != null ? String(p.target_lpa) : DEFAULTS.targetLpa);
        const blocklist = (p.config_overrides?.title_blocklist as string[] | undefined);
        setTitleBlocklist(blocklist?.length ? blocklist : DEFAULTS.titleBlocklist);
        const savedHours = p.config_overrides?.recency_hours as number | undefined;
        setRecencyHours(savedHours ?? DEFAULTS.recencyHours);
      })
      .catch(() => toast("Failed to load profile", "error"))
      .finally(() => setLoading(false));
  }, [isDevPanelOpen, token]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeDevPanel();
    }
    if (isDevPanelOpen) {
      document.addEventListener("keydown", onKey);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [isDevPanelOpen, closeDevPanel]);

  const saveProfile = useCallback(async () => {
    if (!token) return;
    try {
      await api.profile.patch(token, {
        target_roles: targetRoles,
        preferred_locations: preferredLocations,
        custom_search_queries: customSearchQueries,
        min_yoe: minYoe !== "" ? Number(minYoe) : null,
        max_yoe: maxYoe !== "" ? Number(maxYoe) : null,
        target_lpa: targetLpa !== "" ? Number(targetLpa) : null,
        config_overrides: { title_blocklist: titleBlocklist, recency_hours: recencyHours },
      });
      toast("Profile saved", "success");
    } catch {
      toast("Save failed", "error");
    }
  }, [token, targetRoles, preferredLocations, customSearchQueries, minYoe, maxYoe, targetLpa, titleBlocklist, recencyHours, toast]);

  function resetToDefaults() {
    setTargetRoles(DEFAULTS.targetRoles);
    setPreferredLocations(DEFAULTS.preferredLocations);
    setCustomSearchQueries([]);
    setMinYoe(DEFAULTS.minYoe);
    setMaxYoe(DEFAULTS.maxYoe);
    setTargetLpa(DEFAULTS.targetLpa);
    setTitleBlocklist(DEFAULTS.titleBlocklist);
    setRecencyHours(DEFAULTS.recencyHours);
    toast("Reset to defaults", "info");
  }

  async function triggerRun() {
    setTriggering(true);
    try {
      await api.runs.trigger(token);
      toast("Run queued", "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", "error");
    } finally {
      setTriggering(false);
    }
  }

  function saveDebugSettings() {
    localStorage.setItem("signalrank-api-url", apiUrl);
    localStorage.setItem("signalrank-poll-interval", pollingInterval);
    localStorage.setItem("signalrank-debug-log", String(debugLog));
    toast("Debug settings saved", "success");
  }

  async function checkHealth() {
    setHealthStatus("checking...");
    try {
      const base = apiUrl || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${base}/health`);
      setHealthStatus(res.ok ? `OK (${res.status})` : `Error (${res.status})`);
    } catch (e) {
      setHealthStatus(`Unreachable: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }

  async function fetchLastResponse() {
    try {
      const data = await api.jobs.list(token, 1, 1);
      setLastApiResponse(JSON.stringify(data, null, 2));
    } catch (e) {
      setLastApiResponse(`Error: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }

  function exportSettings() {
    const data: Record<string, string | null> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith("signalrank-")) data[key] = localStorage.getItem(key);
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "signalrank-settings.json";
    a.click();
    URL.revokeObjectURL(url);
    toast("Settings exported", "success");
  }

  function importSettings() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        for (const [key, val] of Object.entries(data)) {
          if (typeof val === "string") localStorage.setItem(key, val);
        }
        toast("Settings imported — reload to apply", "success");
      } catch {
        toast("Invalid settings file", "error");
      }
    };
    input.click();
  }

  function clearLocalStorage() {
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith("signalrank-")) keys.push(key);
    }
    keys.forEach((k) => localStorage.removeItem(k));
    toast(`Cleared ${keys.length} keys`, "success");
  }

  if (!isDevPanelOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex">
      <div className="absolute inset-0 bg-background/80 backdrop-blur-sm" onClick={closeDevPanel} />

      <div className="relative m-auto w-full max-w-2xl max-h-[85vh] bg-card border border-border shadow-2xl flex flex-col overflow-hidden animate-in">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-card shrink-0">
          <div className="flex items-center gap-2">
            <Terminal size={13} className="text-primary" />
            <span className="text-sm font-bold text-primary tracking-widest uppercase text-glow-dim">
              Dev Console
            </span>
            <span className="text-[10px] text-muted-foreground border border-border px-1.5 py-0.5 ml-2">HIDDEN</span>
          </div>
          <button onClick={closeDevPanel} className="text-muted-foreground hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="flex border-b border-border shrink-0">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex-1 px-3 py-2.5 text-[11px] uppercase tracking-widest transition-colors ${
                tab === key
                  ? "text-primary border-b-2 border-primary bg-primary/5"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {loading ? (
            <div className="text-xs text-muted-foreground">Loading...</div>
          ) : (
            <>
              {tab === "profile" && (
                <div className={sectionCls}>
                  <ChipSelect
                    label="Target Roles"
                    options={ROLE_OPTIONS}
                    selected={targetRoles}
                    onChange={setTargetRoles}
                    customPlaceholder="Add custom role..."
                  />

                  <ChipSelect
                    label="Preferred Locations"
                    options={LOCATION_OPTIONS}
                    selected={preferredLocations}
                    onChange={setPreferredLocations}
                    customPlaceholder="Add custom location..."
                  />

                  <ChipSelect
                    label="Custom Search Queries"
                    options={[]}
                    selected={customSearchQueries}
                    onChange={setCustomSearchQueries}
                    customPlaceholder="Add search query..."
                  />

                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className={labelCls}>Min YOE</label>
                      <input type="number" value={minYoe} onChange={(e) => setMinYoe(e.target.value)} placeholder="0" className={inputCls} />
                    </div>
                    <div>
                      <label className={labelCls}>Max YOE</label>
                      <input type="number" value={maxYoe} onChange={(e) => setMaxYoe(e.target.value)} placeholder="20" className={inputCls} />
                    </div>
                    <div>
                      <label className={labelCls}>Target LPA</label>
                      <input type="number" value={targetLpa} onChange={(e) => setTargetLpa(e.target.value)} placeholder="60" className={inputCls} />
                    </div>
                  </div>

                  <ChipSelect
                    label="Title Blocklist"
                    options={BLOCKLIST_OPTIONS}
                    selected={titleBlocklist}
                    onChange={setTitleBlocklist}
                    customPlaceholder="Add blocked title..."
                  />

                  {/* Recency slider */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className={labelCls}>Job Recency</label>
                      <span className="text-xs text-primary tabular-nums font-bold">{formatHours(recencyHours)}</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={HOUR_STOPS.length - 1}
                      value={HOUR_STOPS.indexOf(recencyHours) !== -1 ? HOUR_STOPS.indexOf(recencyHours) : 4}
                      onChange={(e) => setRecencyHours(HOUR_STOPS[Number(e.target.value)])}
                      className="w-full accent-primary"
                    />
                    <div className="flex justify-between mt-1">
                      {HOUR_STOPS.map((h) => (
                        <span
                          key={h}
                          className={`text-[9px] tabular-nums cursor-pointer transition-colors ${
                            h === recencyHours ? "text-primary font-bold" : "text-muted-foreground"
                          }`}
                          onClick={() => setRecencyHours(h)}
                        >
                          {formatHours(h)}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-2 border-t border-border">
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-muted-foreground">
                        Theme: {theme === "dark" ? "Dark" : "Light"}
                      </span>
                      <button onClick={toggleTheme} className={btnCls}>
                        Toggle
                      </button>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={resetToDefaults} className={btnCls}>
                        Reset Defaults
                      </button>
                      <button onClick={saveProfile} className={btnPrimaryCls}>
                        Save Profile
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {tab === "ranking" && (
                <div className={sectionCls}>
                  <div className="border border-border bg-muted/30 px-4 py-3">
                    <p className="text-xs text-muted-foreground">
                      Ranking weights and scoring parameters are configured server-side. The values below are read-only references.
                    </p>
                  </div>

                  <div>
                    <div className={labelCls + " mb-2"}>Score Component Weights</div>
                    <div className="space-y-2">
                      {[
                        { label: "Semantic Match", weight: "30%" },
                        { label: "Skills Match", weight: "20%" },
                        { label: "Company Tier", weight: "20%" },
                        { label: "Seniority Fit", weight: "15%" },
                        { label: "Location", weight: "10%" },
                        { label: "Recency", weight: "5%" },
                      ].map(({ label, weight }) => (
                        <div key={label} className="flex items-center gap-3">
                          <span className="text-xs text-foreground w-28 shrink-0">{label}</span>
                          <div className="flex-1 h-1.5 bg-muted relative overflow-hidden">
                            <div className="h-full bg-primary/60" style={{ width: weight }} />
                          </div>
                          <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">{weight}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className={labelCls + " mb-2"}>Company Tier Scores</div>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { tier: "SS", score: 100, color: "var(--primary)" },
                        { tier: "S", score: 95, color: "var(--terminal-green-bright)" },
                        { tier: "A", score: 85, color: "var(--terminal-yellow)" },
                        { tier: "B", score: 65, color: "var(--chart-4)" },
                        { tier: "C", score: 45, color: "var(--muted-foreground)" },
                        { tier: "D", score: 15, color: "var(--destructive)" },
                        { tier: "Default", score: 40, color: "var(--muted-foreground)" },
                      ].map(({ tier, score, color }) => (
                        <div key={tier} className="flex items-center gap-2 border border-border px-2 py-1.5">
                          <span className="text-[11px] font-bold" style={{ color }}>{tier}</span>
                          <span className="text-xs text-muted-foreground tabular-nums">{score}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className={labelCls + " mb-2"}>Filters Active</div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      {[
                        { label: "Contract Penalty", value: "Enabled" },
                        { label: "Semantic Floor", value: "0.65" },
                        { label: "Dedup Strategy", value: "Fuzzy Seniority" },
                        { label: "QA Blocklist", value: "Active" },
                      ].map(({ label, value }) => (
                        <div key={label} className="border border-border px-3 py-2">
                          <span className="text-muted-foreground">{label}:</span>{" "}
                          <span className="text-primary">{value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {tab === "runs" && (
                <div className={sectionCls}>
                  <div>
                    <div className={labelCls + " mb-3"}>Trigger New Run</div>
                    <button onClick={triggerRun} disabled={triggering} className={btnPrimaryCls}>
                      <RefreshCw size={11} className={triggering ? "spin-slow" : ""} />
                      {triggering ? "Queuing..." : "Refresh Jobs"}
                    </button>
                  </div>

                  <div className="border-t border-border pt-4">
                    <div className={labelCls + " mb-3"}>Run History</div>
                    <RunHistoryMini token={token} />
                  </div>
                </div>
              )}

              {tab === "debug" && (
                <div className={sectionCls}>
                  <div>
                    <label className={labelCls}>API URL Override</label>
                    <input
                      type="text"
                      value={apiUrl}
                      onChange={(e) => setApiUrl(e.target.value)}
                      placeholder={process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
                      className={inputCls}
                    />
                    <p className="text-[10px] text-muted-foreground mt-1">Requires page reload to take effect</p>
                  </div>

                  <div>
                    <label className={labelCls}>Polling Interval (ms)</label>
                    <input
                      type="number"
                      value={pollingInterval}
                      onChange={(e) => setPollingInterval(e.target.value)}
                      className={inputCls}
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <label className={labelCls}>Debug Logging</label>
                    <button
                      onClick={() => setDebugLog((d) => !d)}
                      className={`text-xs px-2 py-1 border transition-colors ${
                        debugLog ? "border-primary text-primary bg-primary/10" : "border-border text-muted-foreground"
                      }`}
                    >
                      {debugLog ? "ON" : "OFF"}
                    </button>
                  </div>

                  <div className="flex gap-2">
                    <button onClick={saveDebugSettings} className={btnPrimaryCls}>
                      Save Debug Settings
                    </button>
                  </div>

                  <div className="border-t border-border pt-4 space-y-3">
                    <div className={labelCls}>System Tools</div>
                    <div className="flex items-center gap-2">
                      <button onClick={checkHealth} className={btnCls}>
                        <Activity size={11} /> Health Check
                      </button>
                      {healthStatus && (
                        <span className={`text-xs ${healthStatus.startsWith("OK") ? "text-primary" : "text-destructive"}`}>
                          {healthStatus}
                        </span>
                      )}
                    </div>
                    <button onClick={fetchLastResponse} className={btnCls}>
                      <Server size={11} /> Fetch Sample API Response
                    </button>
                    {lastApiResponse && (
                      <pre className="text-[10px] text-muted-foreground bg-muted/30 border border-border p-3 max-h-48 overflow-auto whitespace-pre-wrap">
                        {lastApiResponse}
                      </pre>
                    )}
                  </div>

                  <div className="border-t border-border pt-4 space-y-3">
                    <div className={labelCls}>LocalStorage</div>
                    <div className="flex flex-wrap gap-2">
                      <button onClick={exportSettings} className={btnCls}>
                        <Download size={11} /> Export
                      </button>
                      <button onClick={importSettings} className={btnCls}>
                        <Upload size={11} /> Import
                      </button>
                      <button
                        onClick={clearLocalStorage}
                        className="flex items-center gap-2 px-3 py-2 text-xs border border-destructive/40 text-destructive hover:bg-destructive hover:text-background transition-colors uppercase tracking-wider"
                      >
                        <Trash2 size={11} /> Clear All
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function RunHistoryMini({ token }: { token: string }) {
  const [runs, setRuns] = useState<{ run_id: string; status: string; job_count: number | null; started_at: string | null }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    api.runs.list(token).then(setRuns).catch(() => null).finally(() => setLoading(false));
  }, [token]);

  if (loading) return <div className="text-xs text-muted-foreground">Loading...</div>;
  if (runs.length === 0) return <div className="text-xs text-muted-foreground">No runs yet</div>;

  return (
    <div className="space-y-1">
      {runs.slice(0, 8).map((r) => {
        const statusColor =
          r.status === "done" || r.status === "success"
            ? "text-primary"
            : r.status === "failed"
            ? "text-destructive"
            : "text-terminal-yellow";
        return (
          <div key={r.run_id} className="flex items-center gap-3 text-xs border border-border px-3 py-2">
            <span className={`font-bold uppercase ${statusColor}`}>{r.status}</span>
            <span className="text-muted-foreground tabular-nums">{r.job_count ?? "—"} jobs</span>
            <span className="text-muted-foreground ml-auto tabular-nums">
              {r.started_at ? new Date(r.started_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
