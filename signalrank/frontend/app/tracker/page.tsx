"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Application, ApplicationStatus, TrackerStats, Run } from "@/types";
import { useToast } from "@/components/toast";
import {
  Trash2,
  Mail,
  ExternalLink,
  Plus,
  ChevronDown,
  ChevronRight,
  StickyNote,
  Linkedin,
  Download,
  Calendar,
  DollarSign,
} from "lucide-react";

const STATUSES: ApplicationStatus[] = [
  "interested",
  "applied",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
  "archived",
];

const PRIORITIES = ["P1", "P2", "P3"] as const;

const STATUS_STYLE: Record<ApplicationStatus, { dot: string; label: string; border: string; bar: string }> = {
  interested:   { dot: "bg-[#71717a]",  label: "text-[#a1a1aa]", border: "border-[#3f3f46]",      bar: "#71717a" },
  applied:      { dot: "bg-[#22c55e]",  label: "text-[#22c55e]", border: "border-[#22c55e]/40",   bar: "#22c55e" },
  phone_screen: { dot: "bg-[#a3e635]",  label: "text-[#a3e635]", border: "border-[#a3e635]/40",   bar: "#a3e635" },
  interview:    { dot: "bg-[#22c55e]",  label: "text-[#22c55e]", border: "border-[#22c55e]/60",   bar: "#22c55e" },
  offer:        { dot: "bg-[#facc15]",  label: "text-[#facc15]", border: "border-[#facc15]/40",   bar: "#facc15" },
  rejected:     { dot: "bg-[#ef4444]",  label: "text-[#ef4444]", border: "border-[#ef4444]/30",   bar: "#ef4444" },
  archived:     { dot: "bg-[#52525b]",  label: "text-[#52525b]", border: "border-[#3f3f46]",      bar: "#52525b" },
};

const PRIORITY_STYLE: Record<string, { bg: string; text: string }> = {
  P1: { bg: "bg-[#ef4444]/15", text: "text-[#ef4444]" },
  P2: { bg: "bg-[#facc15]/15", text: "text-[#facc15]" },
  P3: { bg: "bg-[#71717a]/15", text: "text-[#71717a]" },
};

function scoreColor(score: number) {
  const pct = score * 100;
  if (pct >= 80) return "#22c55e";
  if (pct >= 65) return "#a3e635";
  if (pct >= 50) return "#facc15";
  return "#f97316";
}

function gmailComposeUrl(to: string, subject: string, body: string) {
  return `https://mail.google.com/mail/?view=cm&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function emailTemplate(app: Application, recruiterName: string) {
  return {
    subject: `Re: ${app.title} at ${app.company}`,
    body: `Hi ${recruiterName},

I came across the ${app.title} role at ${app.company} and wanted to reach out directly. I have experience in the relevant domain and believe I'd be a strong fit.

I've applied via the portal and would love to connect. Happy to share more about my background.

Best regards`,
  };
}

function MiniBarChart({ data, maxVal }: { data: { label: string; count: number; color: string }[]; maxVal: number }) {
  return (
    <div className="space-y-1">
      {data.map(({ label, count, color }) => (
        <div key={label} className="flex items-center gap-2">
          <span className="text-[11px] text-[#71717a] w-20 shrink-0 truncate">{label}</span>
          <div className="flex-1 h-1.5 bg-[#1a1a1e] relative overflow-hidden">
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${maxVal > 0 ? (count / maxVal) * 100 : 0}%`, background: color }}
            />
          </div>
          <span className="text-[11px] text-[#71717a] tabular-nums w-5 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

export default function TrackerPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [applications, setApplications] = useState<Application[]>([]);
  const [stats, setStats] = useState<TrackerStats | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [expandedNotes, setExpandedNotes] = useState<string | null>(null);
  const [expandedRecruiter, setExpandedRecruiter] = useState<string | null>(null);
  const [recruiterForm, setRecruiterForm] = useState({ name: "", email: "", linkedin_url: "" });
  const [showImport, setShowImport] = useState(false);
  const [importMinScore, setImportMinScore] = useState(0.7);
  const [importLimit, setImportLimit] = useState(20);
  const [runs, setRuns] = useState<{ run_id: string; status: string; job_count: number | null }[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [importing, setImporting] = useState(false);
  const [priorityFilter, setPriorityFilter] = useState<"all" | "p1" | "p1p2">("all");

  const loadData = useCallback(async () => {
    if (!token) return;
    const [apps, s] = await Promise.all([
      api.applications.list(token),
      api.applications.stats(token),
    ]);
    setApplications(apps);
    setStats(s);
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!token || !showImport) return;
    api.runs.list(token).then(setRuns);
  }, [token, showImport]);

  async function updateStatus(id: string, status: ApplicationStatus) {
    const app = applications.find((a) => a.id === id);
    await api.applications.update(token, id, { status });
    setApplications((apps) =>
      apps.map((a) => (a.id === id ? { ...a, status, applied_at: status === "applied" && !a.applied_at ? new Date().toISOString() : a.applied_at } : a))
    );
    if (app) toast(`${app.title} -> ${status.replace("_", " ")}`, "success");
  }

  async function updateField(id: string, field: string, value: string | number | null) {
    await api.applications.update(token, id, { [field]: value } as Partial<Application>);
    setApplications((apps) => apps.map((a) => (a.id === id ? { ...a, [field]: value } : a)));
  }

  async function cyclePriority(id: string, current: string | null) {
    const order = ["P1", "P2", "P3", null];
    const idx = order.indexOf(current);
    const next = order[(idx + 1) % order.length];
    await updateField(id, "priority", next);
  }

  async function updateNotes(id: string, notes: string) {
    await api.applications.update(token, id, { notes });
    setApplications((apps) => apps.map((a) => (a.id === id ? { ...a, notes } : a)));
  }

  async function saveRecruiter(appId: string) {
    if (!recruiterForm.name && !recruiterForm.email) return;
    const res = await api.applications.patchRecruiter(token, appId, {
      recruiter_name: recruiterForm.name || undefined,
      recruiter_email: recruiterForm.email || undefined,
      recruiter_linkedin_url: recruiterForm.linkedin_url || undefined,
    });
    setApplications((apps) =>
      apps.map((a) =>
        a.id === appId
          ? { ...a, recruiter: { id: res.recruiter_id, name: recruiterForm.name, email: recruiterForm.email, linkedin_url: recruiterForm.linkedin_url || null } }
          : a
      )
    );
    setExpandedRecruiter(null);
    setRecruiterForm({ name: "", email: "", linkedin_url: "" });
    toast("Recruiter saved", "success");
  }

  async function applyToJob(app: Application) {
    if (app.job_url) window.open(app.job_url, "_blank");
    await updateStatus(app.id, "applied");
  }

  async function deleteApp(id: string) {
    if (confirmDelete !== id) {
      setConfirmDelete(id);
      setTimeout(() => setConfirmDelete(null), 3000);
      return;
    }
    const app = applications.find((a) => a.id === id);
    await api.applications.delete(token, id);
    setApplications((apps) => apps.filter((a) => a.id !== id));
    if (app) toast(`Removed: ${app.title}`, "info");
    setConfirmDelete(null);
  }

  async function handleImport() {
    if (!selectedRunId) return;
    setImporting(true);
    try {
      const res = await api.applications.importFromRun(token, {
        run_id: selectedRunId,
        min_score: importMinScore,
        limit: importLimit,
      });
      toast(`Imported ${res.created} jobs (${res.skipped} already tracked)`, "success");
      setShowImport(false);
      loadData();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Import failed", "error");
    } finally {
      setImporting(false);
    }
  }

  const filteredApps = priorityFilter === "all"
    ? applications
    : priorityFilter === "p1"
      ? applications.filter((a) => a.priority === "P1")
      : applications.filter((a) => a.priority === "P1" || a.priority === "P2");

  const byStatus = STATUSES.reduce(
    (acc, s) => ({ ...acc, [s]: filteredApps.filter((a) => a.status === s) }),
    {} as Record<ApplicationStatus, Application[]>
  );

  const visibleStatuses = STATUSES.filter(
    (s) => byStatus[s].length > 0 || ["interested", "applied", "interview"].includes(s)
  );

  const pipelineData = STATUSES.map((s) => ({
    label: s.replace("_", " "),
    count: byStatus[s].length,
    color: STATUS_STYLE[s].bar,
  })).filter((d) => d.count > 0);
  const pipelineMax = Math.max(...pipelineData.map((d) => d.count), 1);

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-end justify-between gap-4">
          <div>
            <div className="section-label mb-1">application tracker</div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-bold text-[#d4d4d8]">Tracker</h1>
              <span className="text-[#22c55e] text-sm tabular-nums text-glow-dim">{applications.length} total</span>
            </div>
          </div>
          <button
            onClick={() => setShowImport(!showImport)}
            className="flex items-center gap-2 px-3 py-2 text-[11px] border border-[#22c55e]/40 text-[#22c55e] hover:bg-[#22c55e]/10 transition-colors uppercase tracking-wider"
          >
            <Download size={11} />
            Import from Run
          </button>
        </div>

        {/* Import dropdown */}
        {showImport && (
          <div className="border border-[#2a2a2e] bg-[#0d0d0f] p-4 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-[11px] text-[#71717a] uppercase tracking-wider block mb-1">Run</label>
                <select
                  value={selectedRunId}
                  onChange={(e) => setSelectedRunId(e.target.value)}
                  className="w-full text-xs bg-[#0a0a0a] border border-[#3f3f46] text-[#a1a1aa] px-2 py-1.5 focus:border-[#22c55e] focus:outline-none"
                >
                  <option value="">Select run...</option>
                  {runs.filter((r) => r.status === "success").map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id.slice(0, 8)} ({r.job_count ?? 0} jobs)
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-[#71717a] uppercase tracking-wider block mb-1">
                  Min Score: {Math.round(importMinScore * 100)}%
                </label>
                <input
                  type="range"
                  min={0.4}
                  max={0.95}
                  step={0.05}
                  value={importMinScore}
                  onChange={(e) => setImportMinScore(Number(e.target.value))}
                  className="w-full accent-[#22c55e]"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#71717a] uppercase tracking-wider block mb-1">
                  Limit: {importLimit}
                </label>
                <input
                  type="range"
                  min={5}
                  max={100}
                  step={5}
                  value={importLimit}
                  onChange={(e) => setImportLimit(Number(e.target.value))}
                  className="w-full accent-[#22c55e]"
                />
              </div>
            </div>
            <button
              onClick={handleImport}
              disabled={!selectedRunId || importing}
              className="text-[11px] text-[#22c55e] border border-[#22c55e]/30 px-3 py-1.5 hover:bg-[#22c55e]/10 transition-colors uppercase tracking-wider disabled:opacity-30"
            >
              {importing ? "Importing..." : "Import"}
            </button>
          </div>
        )}

        {/* KPI Summary Bar */}
        {stats && (
          <div className="grid grid-cols-6 gap-px border border-[#2a2a2e] bg-[#2a2a2e] overflow-hidden">
            {[
              { label: "Total", value: stats.total, color: "#d4d4d8" },
              { label: "P1", value: stats.by_priority.P1 ?? 0, color: "#ef4444" },
              { label: "P2", value: stats.by_priority.P2 ?? 0, color: "#facc15" },
              { label: "Offers", value: stats.offers_count, color: "#22c55e" },
              { label: "Best Offer", value: stats.best_offer_lpa ? `${stats.best_offer_lpa}L` : "--", color: "#facc15" },
              { label: "Gap", value: stats.target_lpa && stats.best_offer_lpa ? `${Math.round(stats.target_lpa - stats.best_offer_lpa)}L` : "--", color: stats.target_lpa && stats.best_offer_lpa && stats.best_offer_lpa >= stats.target_lpa ? "#22c55e" : "#ef4444" },
            ].map((kpi) => (
              <div key={kpi.label} className="bg-[#0d0d0f] px-4 py-3 text-center">
                <div className="text-[11px] text-[#71717a] uppercase tracking-wider">{kpi.label}</div>
                <div className="text-lg font-bold tabular-nums mt-0.5" style={{ color: kpi.color }}>
                  {kpi.value}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pipeline bar chart */}
        {pipelineData.length > 0 && (
          <div className="border border-[#2a2a2e] bg-[#0d0d0f] p-4">
            <div className="text-[11px] text-[#71717a] uppercase tracking-wider mb-3">Pipeline</div>
            <MiniBarChart data={pipelineData} maxVal={pipelineMax} />
          </div>
        )}

        {/* Priority filter toggle */}
        <div className="flex items-center gap-1">
          {(["all", "p1", "p1p2"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setPriorityFilter(f)}
              className={
                priorityFilter === f
                  ? "bg-[var(--accent)] text-white rounded px-3 py-1 text-sm font-medium"
                  : "bg-[var(--bg-input)] text-[var(--fg-muted)] rounded px-3 py-1 text-sm hover:text-[var(--fg)]"
              }
            >
              {f === "all" ? "All" : f === "p1" ? "P1 only" : "P1 + P2"}
            </button>
          ))}
        </div>

        {/* Kanban grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {visibleStatuses.map((status) => {
            const style = STATUS_STYLE[status];
            const apps = byStatus[status];
            return (
              <div key={status} className="space-y-2">
                <div className="flex items-center gap-2 pb-1 border-b border-[#3f3f46]">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
                  <span className={`text-xs uppercase tracking-wider ${style.label}`}>
                    {status.replace("_", " ")}
                  </span>
                  <span className="text-xs text-[#71717a] ml-auto tabular-nums">
                    {apps.length}
                  </span>
                </div>

                {apps.length === 0 ? (
                  <div className="border border-dashed border-[#1e1e21] p-4 text-center">
                    <span className="text-xs text-[#52525b]">empty</span>
                  </div>
                ) : (
                  apps.map((app) => (
                    <div
                      key={app.id}
                      className={`border card-hover bg-[#111113] p-3 space-y-2 ${style.border}`}
                    >
                      {/* Title + company + priority */}
                      <div className="flex items-start gap-1.5">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-[#e4e4e7] truncate">{app.title}</div>
                          <div className="text-xs text-[#a1a1aa] truncate">{app.company}</div>
                        </div>
                        <button
                          onClick={() => cyclePriority(app.id, app.priority)}
                          className={`shrink-0 text-[11px] px-1.5 py-0.5 leading-none font-bold uppercase tracking-wider ${
                            app.priority && PRIORITY_STYLE[app.priority]
                              ? `${PRIORITY_STYLE[app.priority].bg} ${PRIORITY_STYLE[app.priority].text}`
                              : "text-[#3f3f46] hover:text-[#71717a]"
                          }`}
                          title="Click to cycle priority"
                        >
                          {app.priority ?? "--"}
                        </button>
                      </div>

                      {/* Tier + Type + Location */}
                      {(app.company_tier || app.is_contract || app.location) && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {app.company_tier && (
                            <span className={`text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-wider border ${
                              app.company_tier === "S" ? "text-[#facc15] border-[#facc15]/30 bg-[#facc15]/10" :
                              app.company_tier === "A" ? "text-[#22c55e] border-[#22c55e]/30 bg-[#22c55e]/10" :
                              app.company_tier === "B" ? "text-[#a3e635] border-[#a3e635]/30 bg-[#a3e635]/10" :
                              "text-[#71717a] border-[#3f3f46] bg-[#71717a]/10"
                            }`}>
                              {app.company_tier}
                            </span>
                          )}
                          {app.is_contract && (
                            <span className="text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-wider text-[#f97316] border border-[#f97316]/30 bg-[#f97316]/10">
                              contract
                            </span>
                          )}
                          {app.location && (
                            <span className="text-[10px] text-[#71717a] truncate">{app.location}</span>
                          )}
                        </div>
                      )}

                      {/* Score */}
                      {app.system_score != null && (
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-bold tabular-nums" style={{ color: scoreColor(app.system_score) }}>
                            {Math.round(app.system_score * 100)}%
                          </span>
                          <div className="flex-1 h-1 bg-[#1a1a1e] overflow-hidden">
                            <div
                              className="h-full"
                              style={{
                                width: `${app.system_score * 100}%`,
                                background: scoreColor(app.system_score),
                              }}
                            />
                          </div>
                          {app.resume_match_pct != null && (
                            <span className="text-[11px] text-[#71717a] tabular-nums">
                              {Math.round(app.resume_match_pct * 100)}% match
                            </span>
                          )}
                        </div>
                      )}

                      {/* Status dropdown */}
                      <select
                        value={app.status}
                        onChange={(e) => updateStatus(app.id, e.target.value as ApplicationStatus)}
                        className="w-full text-xs bg-[#0a0a0a] border border-[#3f3f46] text-[#a1a1aa] px-1.5 py-1 focus:border-[#22c55e] focus:outline-none"
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>{s.replace("_", " ")}</option>
                        ))}
                      </select>

                      {/* Interview date */}
                      {(app.status === "interview" || app.status === "phone_screen" || app.interview_date) && (
                        <div className="flex items-center gap-1.5">
                          <Calendar size={11} className="text-[#71717a] shrink-0" />
                          <input
                            type="date"
                            value={app.interview_date ? app.interview_date.slice(0, 10) : ""}
                            onChange={(e) => updateField(app.id, "interview_date", e.target.value || null)}
                            className="flex-1 text-xs bg-transparent border border-[#2a2a2e] text-[#a1a1aa] px-1.5 py-0.5 focus:border-[#22c55e] focus:outline-none"
                          />
                        </div>
                      )}

                      {/* Offer LPA */}
                      {(app.status === "offer" || app.offer_lpa != null) && (
                        <div className="flex items-center gap-1.5">
                          <DollarSign size={11} className="text-[#facc15] shrink-0" />
                          <input
                            type="number"
                            placeholder="LPA"
                            value={app.offer_lpa ?? ""}
                            onChange={(e) => updateField(app.id, "offer_lpa", e.target.value ? Number(e.target.value) : null)}
                            className="flex-1 text-xs bg-transparent border border-[#2a2a2e] text-[#facc15] px-1.5 py-0.5 focus:border-[#22c55e] focus:outline-none placeholder:text-[#3f3f46]"
                          />
                          <span className="text-[11px] text-[#71717a]">LPA</span>
                        </div>
                      )}

                      {/* Recruiter section */}
                      {app.recruiter ? (
                        <div className="flex items-center gap-1.5 text-xs">
                          <span className="text-[#a1a1aa] truncate">{app.recruiter.name ?? app.recruiter.email}</span>
                          {app.recruiter.linkedin_url && (
                            <a
                              href={app.recruiter.linkedin_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[#0a66c2] hover:text-[#a3e635] transition-colors shrink-0"
                              title="LinkedIn profile"
                            >
                              <Linkedin size={11} />
                            </a>
                          )}
                          {app.recruiter.email && (
                            <a
                              href={gmailComposeUrl(
                                app.recruiter.email,
                                emailTemplate(app, app.recruiter.name ?? "").subject,
                                emailTemplate(app, app.recruiter.name ?? "").body,
                              )}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[#22c55e] hover:text-[#a3e635] transition-colors shrink-0"
                              title="Compose email"
                            >
                              <Mail size={11} />
                            </a>
                          )}
                        </div>
                      ) : expandedRecruiter === app.id ? (
                        <div className="space-y-1.5">
                          <input
                            type="text"
                            placeholder="Name"
                            value={recruiterForm.name}
                            onChange={(e) => setRecruiterForm((f) => ({ ...f, name: e.target.value }))}
                            className="w-full text-xs bg-transparent border border-[#2a2a2e] text-[#a1a1aa] px-1.5 py-1 focus:border-[#22c55e] focus:outline-none placeholder:text-[#52525b]"
                          />
                          <input
                            type="email"
                            placeholder="Email"
                            value={recruiterForm.email}
                            onChange={(e) => setRecruiterForm((f) => ({ ...f, email: e.target.value }))}
                            className="w-full text-xs bg-transparent border border-[#2a2a2e] text-[#a1a1aa] px-1.5 py-1 focus:border-[#22c55e] focus:outline-none placeholder:text-[#52525b]"
                          />
                          <input
                            type="url"
                            placeholder="LinkedIn URL"
                            value={recruiterForm.linkedin_url}
                            onChange={(e) => setRecruiterForm((f) => ({ ...f, linkedin_url: e.target.value }))}
                            className="w-full text-xs bg-transparent border border-[#2a2a2e] text-[#a1a1aa] px-1.5 py-1 focus:border-[#22c55e] focus:outline-none placeholder:text-[#52525b]"
                          />
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => saveRecruiter(app.id)}
                              className="text-[11px] text-[#22c55e] border border-[#22c55e]/30 px-1.5 py-0.5 hover:bg-[#22c55e]/10 transition-colors uppercase tracking-wider"
                            >
                              save
                            </button>
                            <button
                              onClick={() => { setExpandedRecruiter(null); setRecruiterForm({ name: "", email: "", linkedin_url: "" }); }}
                              className="text-[11px] text-[#71717a] hover:text-[#a1a1aa] transition-colors"
                            >
                              cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={() => { setExpandedRecruiter(app.id); setRecruiterForm({ name: "", email: "", linkedin_url: "" }); }}
                          className="flex items-center gap-1 text-[11px] text-[#52525b] hover:text-[#22c55e] transition-colors"
                        >
                          <Plus size={10} />
                          recruiter
                        </button>
                      )}

                      {/* Notes toggle */}
                      <button
                        onClick={() => setExpandedNotes(expandedNotes === app.id ? null : app.id)}
                        className="flex items-center gap-1 text-[11px] text-[#52525b] hover:text-[#a1a1aa] transition-colors"
                      >
                        {expandedNotes === app.id ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                        <StickyNote size={10} />
                        {app.notes ? "notes" : "add note"}
                      </button>
                      {expandedNotes === app.id && (
                        <textarea
                          defaultValue={app.notes ?? ""}
                          onBlur={(e) => updateNotes(app.id, e.target.value)}
                          placeholder="Add notes..."
                          rows={3}
                          className="w-full text-xs bg-transparent border border-[#2a2a2e] text-[#a1a1aa] px-1.5 py-1 focus:border-[#22c55e] focus:outline-none resize-none placeholder:text-[#52525b]"
                        />
                      )}

                      {/* Action buttons */}
                      <div className="flex items-center gap-2 pt-0.5">
                        {app.status === "interested" && (
                          <button
                            onClick={() => applyToJob(app)}
                            className="flex items-center gap-1 text-[11px] text-[#22c55e] border border-[#22c55e]/30 px-1.5 py-0.5 hover:bg-[#22c55e]/10 transition-colors uppercase tracking-wider"
                          >
                            apply
                            <ExternalLink size={9} />
                          </button>
                        )}
                        {app.job_url && app.status !== "interested" && (
                          <a
                            href={app.job_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[#52525b] hover:text-[#22c55e] transition-colors"
                          >
                            <ExternalLink size={11} />
                          </a>
                        )}
                        <button
                          onClick={() => deleteApp(app.id)}
                          className={`flex items-center gap-1 text-xs ml-auto transition-colors ${
                            confirmDelete === app.id
                              ? "text-[#ef4444]"
                              : "text-[#71717a] hover:text-[#ef4444]"
                          }`}
                        >
                          <Trash2 size={11} />
                          {confirmDelete === app.id ? "confirm?" : ""}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
