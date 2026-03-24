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
  Search,
  Copy,
  FileText,
  Loader2,
  Sparkles,
} from "lucide-react";

const STATUSES: ApplicationStatus[] = [
  "interested",
  "applied",
  "messaged_recruiter",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
  "archived",
];

const PRIORITIES = ["P1", "P2", "P3"] as const;

const STATUS_STYLE: Record<ApplicationStatus, { dot: string; label: string; border: string; bar: string }> = {
  interested:   { dot: "bg-muted-foreground",  label: "text-secondary-foreground", border: "border-border",                      bar: "var(--muted-foreground)" },
  applied:      { dot: "bg-primary",           label: "text-primary",              border: "border-primary/40",                  bar: "var(--primary)" },
  messaged_recruiter: { dot: "bg-[var(--terminal-cyan)]", label: "text-[var(--terminal-cyan)]", border: "border-[var(--terminal-cyan)]/40", bar: "var(--terminal-cyan, #22d3ee)" },
  phone_screen: { dot: "bg-[var(--terminal-green-bright)]", label: "text-[var(--terminal-green-bright)]", border: "border-[var(--terminal-green-bright)]/40", bar: "var(--terminal-green-bright)" },
  interview:    { dot: "bg-primary",           label: "text-primary",              border: "border-primary/60",                  bar: "var(--primary)" },
  offer:        { dot: "bg-[var(--terminal-yellow)]", label: "text-[var(--terminal-yellow)]", border: "border-[var(--terminal-yellow)]/40", bar: "var(--terminal-yellow)" },
  rejected:     { dot: "bg-destructive",       label: "text-destructive",          border: "border-destructive/30",              bar: "var(--destructive)" },
  archived:     { dot: "bg-muted-foreground",  label: "text-muted-foreground",     border: "border-border",                      bar: "var(--muted-foreground)" },
};

const PRIORITY_STYLE: Record<string, { bg: string; text: string }> = {
  P1: { bg: "bg-destructive/15", text: "text-destructive" },
  P2: { bg: "bg-[var(--terminal-yellow)]/15", text: "text-[var(--terminal-yellow)]" },
  P3: { bg: "bg-muted-foreground/15", text: "text-muted-foreground" },
};

function scoreColor(score: number) {
  const pct = score * 100;
  if (pct >= 80) return "var(--primary)";
  if (pct >= 65) return "var(--terminal-green-bright)";
  if (pct >= 50) return "var(--terminal-yellow)";
  return "var(--chart-4)";
}

const MY_SIGNATURE = `
--
Example Candidate
Senior AI Platform Engineer, Fractal Analytics
linkedin.com/in/example-candidate`;

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

function gmailComposeUrl(to: string, subject: string, body: string) {
  return `https://mail.google.com/mail/?view=cm&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function mailtoUrl(to: string, subject: string, body: string) {
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function linkedinRecruiterSearchUrl(company: string) {
  const query = `site:linkedin.com/in "${company}" "technical recruiter" OR "talent acquisition" OR "hiring manager"`;
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

function emailTemplate(app: Application, recruiterName: string) {
  const firstName = recruiterName.split(" ")[0] || recruiterName;
  const subject = `${app.title} — built 400+ AI agents at scale (applied)`;
  const jobLink = app.job_url ? `I applied for the ${app.title} role (${app.job_url}) and ` : `I applied for the ${app.title} role and `;
  const body = `Hi ${firstName},

${jobLink}wanted to share quick context that might not come through on a resume:

At Fractal Analytics, I built an "Agentic Factory" that standardised 400+ AI agents for a Fortune 5 US Telecom — the platform handles the full lifecycle from CI/CD to production deployment on GCP, supporting 16,000+ deployments with 90-second onboarding.

That experience maps directly to what ${app.company} is building. Happy to jump on a 15-min call if you think there's a fit.

Best,${MY_SIGNATURE}`;

  return { subject, body };
}

function MiniBarChart({ data, maxVal }: { data: { label: string; count: number; color: string }[]; maxVal: number }) {
  return (
    <div className="space-y-1">
      {data.map(({ label, count, color }) => (
        <div key={label} className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground w-20 shrink-0 truncate">{label}</span>
          <div className="flex-1 h-1.5 bg-muted relative overflow-hidden">
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${maxVal > 0 ? (count / maxVal) * 100 : 0}%`, background: color }}
            />
          </div>
          <span className="text-[11px] text-muted-foreground tabular-nums w-5 text-right">{count}</span>
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
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(new Set());
  const [tailoring, setTailoring] = useState<Set<string>>(new Set());
  const [generatedEmails, setGeneratedEmails] = useState<Map<string, { subject: string; body: string }>>(new Map());
  const [expandedEmail, setExpandedEmail] = useState<string | null>(null);
  const COLUMN_LIMIT = 10;

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
    if (recruiterForm.email && !isValidEmail(recruiterForm.email)) {
      toast("Invalid email address", "error");
      return;
    }
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

  async function mailAllRecruiters(app: Application) {
    if (!app.company) return;
    const recs = await api.applications.recruitersByCompany(token, app.company);
    const emails = recs.filter((r: { email: string }) => isValidEmail(r.email)).map((r: { email: string }) => r.email);
    if (!emails.length) { toast("No emails found for this company", "info"); return; }
    const to = emails.join(",");
    const { subject, body } = emailTemplate(app, recs[0]?.name ?? "Recruiter");
    window.open(gmailComposeUrl(to, subject, body), "_blank");
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

  async function downloadAndEmail(app: Application) {
    if (!app.job_id) {
      toast("No job linked", "error");
      return;
    }
    setTailoring((prev) => new Set(prev).add(app.id));
    try {
      const recs = app.company ? await api.applications.recruitersByCompany(token, app.company) : [];
      const recruiterName = recs[0]?.name || app.recruiter?.name || "Hiring Manager";
      const email = await api.resume.email(token, { job_id: app.job_id, recruiter_name: recruiterName });

      if (email.body) {
        setGeneratedEmails((prev) => new Map(prev).set(app.id, email));
        setExpandedEmail(app.id);
        const emails = recs.filter((r: { email: string }) => isValidEmail(r.email)).map((r: { email: string }) => r.email);
        const to = emails.length ? emails[0] : (app.recruiter?.email && isValidEmail(app.recruiter.email) ? app.recruiter.email : "");
        const tab = window.open(gmailComposeUrl(to, email.subject, email.body + MY_SIGNATURE), "_blank", "noopener,noreferrer");
        tab?.blur();
        window.focus();
      }
      if (app.job_url) {
        const tab = window.open(app.job_url, "_blank", "noopener,noreferrer");
        tab?.blur();
        window.focus();
      }

      // Mark as applied
      await updateStatus(app.id, "applied");

      // PDF download — show clear message if still generating
      const dlResult = await api.resume.download(token, app.job_id).catch(() => "error" as const);
      if (dlResult === "pending") {
        toast("Resume still generating — check back in ~2 min and click Apply again to download", "info");
      } else if (dlResult === "error") {
        toast("Resume download failed", "error");
      } else {
        toast(`Applied to ${app.title}`, "success");
      }
    } catch (e) {
      toast(`Failed: ${e instanceof Error ? e.message : "unknown error"}`, "error");
    } finally {
      setTailoring((prev) => { const n = new Set(prev); n.delete(app.id); return n; });
    }
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
              <h1 className="text-xl font-bold text-foreground">Tracker</h1>
              <span className="text-primary text-sm tabular-nums text-glow-dim">{applications.length} total</span>
            </div>
          </div>
          <button
            onClick={() => setShowImport(!showImport)}
            className="flex items-center gap-2 px-3 py-2 text-[11px] border border-primary/40 text-primary hover:bg-primary/10 transition-colors uppercase tracking-wider"
          >
            <Download size={11} />
            Import from Run
          </button>
        </div>

        {/* Import dropdown */}
        {showImport && (
          <div className="border border-border bg-muted p-4 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-[11px] text-muted-foreground uppercase tracking-wider block mb-1">Run</label>
                <select
                  value={selectedRunId}
                  onChange={(e) => setSelectedRunId(e.target.value)}
                  className="w-full text-xs bg-background border border-border text-secondary-foreground px-2 py-1.5 focus:border-primary focus:outline-none"
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
                <label className="text-[11px] text-muted-foreground uppercase tracking-wider block mb-1">
                  Min Score: {Math.round(importMinScore * 100)}%
                </label>
                <input
                  type="range"
                  min={0.4}
                  max={0.95}
                  step={0.05}
                  value={importMinScore}
                  onChange={(e) => setImportMinScore(Number(e.target.value))}
                  className="w-full accent-primary"
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
                  className="w-full accent-primary"
                />
              </div>
            </div>
            <button
              onClick={handleImport}
              disabled={!selectedRunId || importing}
              className="text-[11px] text-primary border border-primary/30 px-3 py-1.5 hover:bg-primary/10 transition-colors uppercase tracking-wider disabled:opacity-30"
            >
              {importing ? "Importing..." : "Import"}
            </button>
          </div>
        )}

        {/* KPI Summary Bar */}
        {stats && (
          <div className="grid grid-cols-6 gap-px border border-border bg-border overflow-hidden">
            {[
              { label: "Total", value: stats.total, color: "var(--foreground)" },
              { label: "P1", value: stats.by_priority.P1 ?? 0, color: "var(--destructive)" },
              { label: "P2", value: stats.by_priority.P2 ?? 0, color: "var(--terminal-yellow)" },
              { label: "Offers", value: stats.offers_count, color: "var(--primary)" },
              { label: "Best Offer", value: stats.best_offer_lpa ? `${stats.best_offer_lpa}L` : "--", color: "var(--terminal-yellow)" },
              { label: "Gap", value: stats.target_lpa && stats.best_offer_lpa ? `${Math.round(stats.target_lpa - stats.best_offer_lpa)}L` : "--", color: stats.target_lpa && stats.best_offer_lpa && stats.best_offer_lpa >= stats.target_lpa ? "var(--primary)" : "var(--destructive)" },
            ].map((kpi) => (
              <div key={kpi.label} className="bg-card px-4 py-3 text-center">
                <div className="text-[11px] text-muted-foreground uppercase tracking-wider">{kpi.label}</div>
                <div className="text-lg font-bold tabular-nums mt-0.5" style={{ color: kpi.color }}>
                  {kpi.value}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pipeline bar chart */}
        {pipelineData.length > 0 && (
          <div className="border border-border bg-card p-4">
            <div className="text-[11px] text-muted-foreground uppercase tracking-wider mb-3">Pipeline</div>
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
            const isExpanded = expandedColumns.has(status);
            const visibleApps = isExpanded ? apps : apps.slice(0, COLUMN_LIMIT);
            const hiddenCount = apps.length - COLUMN_LIMIT;
            return (
              <div key={status} className="space-y-2">
                <div className="flex items-center gap-2 pb-1 border-b border-border">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
                  <span className={`text-xs uppercase tracking-wider ${style.label}`}>
                    {status.replace("_", " ")}
                  </span>
                  <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                    {apps.length}
                  </span>
                </div>

                {apps.length === 0 ? (
                  <div className="border border-dashed border-border/40 p-3 text-center opacity-40">
                    <span className="text-[10px] text-muted-foreground">—</span>
                  </div>
                ) : (
                  visibleApps.map((app) => {
                    const appliedDaysAgo = app.applied_at ? Math.floor((Date.now() - new Date(app.applied_at).getTime()) / 86400000) : null;
                    const needsFollowUp = app.status === "applied" && appliedDaysAgo != null && appliedDaysAgo >= 5;
                    return (
                    <div
                      key={app.id}
                      className={`border card-hover bg-card p-3 space-y-2 ${needsFollowUp ? "border-[var(--terminal-yellow)]/50" : style.border}`}
                      style={needsFollowUp ? { boxShadow: "0 0 8px color-mix(in srgb, var(--terminal-yellow) 15%, transparent)" } : {}}
                    >
                      {/* Title + company + priority */}
                      <div className="flex items-start gap-1.5">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-foreground truncate">{app.title}</div>
                          <div className="text-xs text-secondary-foreground truncate">{app.company}</div>
                        </div>
                        <button
                          onClick={() => cyclePriority(app.id, app.priority)}
                          className={`shrink-0 text-[11px] px-1.5 py-0.5 leading-none font-bold uppercase tracking-wider ${
                            app.priority && PRIORITY_STYLE[app.priority]
                              ? `${PRIORITY_STYLE[app.priority].bg} ${PRIORITY_STYLE[app.priority].text}`
                              : "text-border hover:text-muted-foreground"
                          }`}
                          title="Click to cycle priority"
                        >
                          {app.priority ?? "--"}
                        </button>
                      </div>

                      {/* Days old + follow-up nudge */}
                      {app.applied_at && (() => {
                        const days = Math.floor((Date.now() - new Date(app.applied_at).getTime()) / 86400000);
                        const label = days === 0 ? "today" : days < 7 ? `${days}d ago` : days < 30 ? `${Math.floor(days / 7)}w ago` : `${Math.floor(days / 30)}mo ago`;
                        const color = days < 7 ? "var(--terminal-green-bright)" : days < 21 ? "var(--terminal-yellow)" : "var(--muted-foreground)";
                        return (
                          <div className="flex items-center gap-2">
                            <span className="text-[10px]" style={{ color }}>applied {label}</span>
                            {needsFollowUp && (
                              <span className="text-[10px] text-[var(--terminal-yellow)] font-bold uppercase tracking-wider animate-pulse">
                                follow up
                              </span>
                            )}
                          </div>
                        );
                      })()}

                      {/* Tier + Type + Location */}
                      {(app.company_tier || app.is_contract || app.location) && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {app.company_tier && (
                            <span className={`text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-wider border ${
                              app.company_tier === "S" ? "text-[var(--terminal-yellow)] border-[var(--terminal-yellow)]/30 bg-[var(--terminal-yellow)]/10" :
                              app.company_tier === "A" ? "text-primary border-primary/30 bg-primary/10" :
                              app.company_tier === "B" ? "text-[var(--terminal-green-bright)] border-[var(--terminal-green-bright)]/30 bg-[var(--terminal-green-bright)]/10" :
                              "text-muted-foreground border-border bg-muted-foreground/10"
                            }`}>
                              {app.company_tier}
                            </span>
                          )}
                          {app.is_contract && (
                            <span className="text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-wider text-[var(--chart-4)] border border-[var(--chart-4)]/30 bg-[var(--chart-4)]/10">
                              contract
                            </span>
                          )}
                          {app.location && (
                            <span className="text-[10px] text-muted-foreground truncate">{app.location}</span>
                          )}
                        </div>
                      )}

                      {/* Score */}
                      {app.system_score != null && (
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-bold tabular-nums" style={{ color: scoreColor(app.system_score) }}>
                            {Math.round(app.system_score * 100)}%
                          </span>
                          <div className="flex-1 h-1 bg-muted overflow-hidden">
                            <div
                              className="h-full"
                              style={{
                                width: `${app.system_score * 100}%`,
                                background: scoreColor(app.system_score),
                              }}
                            />
                          </div>
                          {app.resume_match_pct != null && (
                            <span className="text-[11px] text-muted-foreground tabular-nums">
                              {Math.round(app.resume_match_pct * 100)}% match
                            </span>
                          )}
                        </div>
                      )}

                      {/* Status dropdown */}
                      <select
                        value={app.status}
                        onChange={(e) => updateStatus(app.id, e.target.value as ApplicationStatus)}
                        className="w-full text-xs bg-background border border-border text-secondary-foreground px-1.5 py-1 focus:border-primary focus:outline-none"
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>{s.replace("_", " ")}</option>
                        ))}
                      </select>

                      {/* Interview date */}
                      {(app.status === "interview" || app.status === "phone_screen" || app.interview_date) && (
                        <div className="flex items-center gap-1.5">
                          <Calendar size={11} className="text-muted-foreground shrink-0" />
                          <input
                            type="date"
                            value={app.interview_date ? app.interview_date.slice(0, 10) : ""}
                            onChange={(e) => updateField(app.id, "interview_date", e.target.value || null)}
                            className="flex-1 text-xs bg-transparent border border-border text-secondary-foreground px-1.5 py-0.5 focus:border-primary focus:outline-none"
                          />
                        </div>
                      )}

                      {/* Offer LPA */}
                      {(app.status === "offer" || app.offer_lpa != null) && (
                        <div className="flex items-center gap-1.5">
                          <DollarSign size={11} className="text-[var(--terminal-yellow)] shrink-0" />
                          <input
                            type="number"
                            placeholder="LPA"
                            value={app.offer_lpa ?? ""}
                            onChange={(e) => updateField(app.id, "offer_lpa", e.target.value ? Number(e.target.value) : null)}
                            className="flex-1 text-xs bg-transparent border border-border text-[var(--terminal-yellow)] px-1.5 py-0.5 focus:border-primary focus:outline-none placeholder:text-border"
                          />
                          <span className="text-[11px] text-muted-foreground">LPA</span>
                        </div>
                      )}

                      {/* Recruiter section */}
                      {app.recruiter ? (
                        <div className="flex items-center gap-1.5 text-xs">
                          <span className="text-secondary-foreground truncate">{app.recruiter.name ?? app.recruiter.email}</span>
                          {app.recruiter.linkedin_url && (
                            <a
                              href={app.recruiter.linkedin_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[#0a66c2] hover:text-[var(--terminal-green-bright)] transition-colors shrink-0"
                              title="LinkedIn profile"
                            >
                              <Linkedin size={11} />
                            </a>
                          )}
                          {app.recruiter.email && isValidEmail(app.recruiter.email) && (
                            <a
                              href={gmailComposeUrl(
                                app.recruiter.email,
                                emailTemplate(app, app.recruiter.name ?? "Recruiter").subject,
                                emailTemplate(app, app.recruiter.name ?? "Recruiter").body,
                              )}
                              target="_blank"
                              rel="noreferrer"
                              className="mail-glow shrink-0"
                              title={`Email ${app.recruiter.email} via Gmail`}
                            >
                              <Mail size={15} />
                            </a>
                          )}
                          {app.recruiter.email && !isValidEmail(app.recruiter.email) && (
                            <span className="text-[10px] text-destructive" title="Invalid email address">⚠</span>
                          )}
                          <a
                            href={linkedinRecruiterSearchUrl(app.company)}
                            target="_blank"
                            rel="noreferrer"
                            className="text-muted-foreground hover:text-[#0a66c2] transition-colors shrink-0"
                            title={`Find more recruiters at ${app.company}`}
                          >
                            <Search size={9} />
                          </a>
                        </div>
                      ) : expandedRecruiter === app.id ? (
                        <div className="space-y-1.5">
                          <input
                            type="text"
                            placeholder="Name"
                            value={recruiterForm.name}
                            onChange={(e) => setRecruiterForm((f) => ({ ...f, name: e.target.value }))}
                            className="w-full text-xs bg-transparent border border-border text-secondary-foreground px-1.5 py-1 focus:border-primary focus:outline-none placeholder:text-muted-foreground"
                          />
                          <div className="relative">
                            <input
                              type="email"
                              placeholder="Email"
                              value={recruiterForm.email}
                              onChange={(e) => setRecruiterForm((f) => ({ ...f, email: e.target.value }))}
                              className={`w-full text-xs bg-transparent border text-secondary-foreground px-1.5 py-1 focus:outline-none placeholder:text-muted-foreground ${
                                recruiterForm.email && !isValidEmail(recruiterForm.email)
                                  ? "border-destructive focus:border-destructive"
                                  : "border-border focus:border-primary"
                              }`}
                            />
                            {recruiterForm.email && !isValidEmail(recruiterForm.email) && (
                              <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] text-destructive">invalid</span>
                            )}
                          </div>
                          <input
                            type="url"
                            placeholder="LinkedIn URL"
                            value={recruiterForm.linkedin_url}
                            onChange={(e) => setRecruiterForm((f) => ({ ...f, linkedin_url: e.target.value }))}
                            className="w-full text-xs bg-transparent border border-border text-secondary-foreground px-1.5 py-1 focus:border-primary focus:outline-none placeholder:text-muted-foreground"
                          />
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => saveRecruiter(app.id)}
                              className="text-[11px] text-primary border border-primary/30 px-1.5 py-0.5 hover:bg-primary/10 transition-colors uppercase tracking-wider"
                            >
                              save
                            </button>
                            <button
                              onClick={() => { setExpandedRecruiter(null); setRecruiterForm({ name: "", email: "", linkedin_url: "" }); }}
                              className="text-[11px] text-muted-foreground hover:text-secondary-foreground transition-colors"
                            >
                              cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => { setExpandedRecruiter(app.id); setRecruiterForm({ name: "", email: "", linkedin_url: "" }); }}
                            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary transition-colors"
                          >
                            <Plus size={10} />
                            recruiter
                          </button>
                          <a
                            href={linkedinRecruiterSearchUrl(app.company)}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1 text-[11px] text-[#0a66c2] hover:text-primary transition-colors"
                            title={`Search LinkedIn for recruiters at ${app.company}`}
                          >
                            <Search size={9} />
                            <Linkedin size={9} />
                          </a>
                        </div>
                      )}

                      {/* Notes toggle */}
                      <button
                        onClick={() => setExpandedNotes(expandedNotes === app.id ? null : app.id)}
                        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-secondary-foreground transition-colors"
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
                          className="w-full text-xs bg-transparent border border-border text-secondary-foreground px-1.5 py-1 focus:border-primary focus:outline-none resize-none placeholder:text-muted-foreground"
                        />
                      )}

                      {/* Action buttons */}
                      <div className="flex items-center gap-2 pt-0.5">
                        {app.status !== "interested" && app.status !== "applied" && app.status !== "phone_screen" && app.status !== "interview" && app.status !== "offer" && app.status !== "rejected" && app.status !== "archived" && (
                          <button
                            onClick={() => updateStatus(app.id, "applied")}
                            className="flex items-center gap-1 text-[11px] text-muted-foreground border border-border px-1.5 py-0.5 hover:text-primary hover:border-primary/30 transition-colors uppercase tracking-wider"
                            title="Move to applied"
                          >
                            → applied
                          </button>
                        )}
                        {app.job_url && app.status !== "interested" && (
                          <a
                            href={app.job_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-muted-foreground hover:text-primary transition-colors"
                          >
                            <ExternalLink size={11} />
                          </a>
                        )}
                        <button
                          onClick={() => mailAllRecruiters(app)}
                          className="mail-glow transition-colors"
                          title={`Mail all recruiters at ${app.company}`}
                        >
                          <Mail size={15} />
                        </button>
                        <button
                          onClick={() => {
                            const { subject, body } = emailTemplate(app, app.recruiter?.name ?? "Recruiter");
                            navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
                            toast("Email copied to clipboard", "success");
                          }}
                          className="text-muted-foreground hover:text-primary transition-colors"
                          title="Copy email to clipboard"
                        >
                          <Copy size={11} />
                        </button>
                        {app.job_id && (
                          <button
                            onClick={() => downloadAndEmail(app)}
                            disabled={tailoring.has(app.id)}
                            className="flex items-center gap-1 text-[11px] text-[var(--terminal-green-bright)] border border-[var(--terminal-green-bright)]/30 px-1.5 py-0.5 hover:bg-[var(--terminal-green-bright)]/10 transition-colors uppercase tracking-wider disabled:opacity-50"
                            title="Download resume + open cold email draft"
                          >
                            {tailoring.has(app.id) ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                            apply
                          </button>
                        )}
                        <button
                          onClick={() => deleteApp(app.id)}
                          className={`flex items-center gap-1 text-xs ml-auto transition-colors ${
                            confirmDelete === app.id
                              ? "text-destructive"
                              : "text-muted-foreground hover:text-destructive"
                          }`}
                        >
                          <Trash2 size={11} />
                          {confirmDelete === app.id ? "confirm?" : ""}
                        </button>
                      </div>

                      {/* Generated email preview */}
                      {generatedEmails.has(app.id) && (
                        <div className="mt-1">
                          <button
                            onClick={() => setExpandedEmail(expandedEmail === app.id ? null : app.id)}
                            className="flex items-center gap-1 text-[10px] text-[var(--terminal-green-bright)] uppercase tracking-wider"
                          >
                            <ChevronRight size={10} className={`transition-transform ${expandedEmail === app.id ? "rotate-90" : ""}`} />
                            generated email
                          </button>
                          {expandedEmail === app.id && (() => {
                            const email = generatedEmails.get(app.id)!;
                            const recruiterEmail = app.recruiter?.email;
                            return (
                              <div className="mt-1.5 border border-[var(--terminal-green-bright)]/20 bg-[var(--terminal-green-bright)]/5 p-2 space-y-1.5">
                                <div className="text-[11px] font-medium text-secondary-foreground">{email.subject}</div>
                                <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap leading-relaxed">{email.body}</pre>
                                <div className="flex gap-2 pt-1">
                                  <button
                                    onClick={() => { navigator.clipboard.writeText(`Subject: ${email.subject}\n\n${email.body}`); toast("Copied", "success"); }}
                                    className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary border border-border px-1.5 py-0.5 uppercase tracking-wider"
                                  >
                                    <Copy size={9} /> copy
                                  </button>
                                  {recruiterEmail && isValidEmail(recruiterEmail) && (
                                    <a
                                      href={gmailComposeUrl(recruiterEmail, email.subject, email.body + MY_SIGNATURE)}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="flex items-center gap-1 text-[10px] text-primary border border-primary/30 px-1.5 py-0.5 hover:bg-primary/10 uppercase tracking-wider"
                                    >
                                      <Mail size={9} /> gmail
                                    </a>
                                  )}
                                </div>
                              </div>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                    );})
                )}
                {apps.length > COLUMN_LIMIT && (
                  <button
                    onClick={() => setExpandedColumns((prev) => {
                      const next = new Set(prev);
                      if (isExpanded) next.delete(status); else next.add(status);
                      return next;
                    })}
                    className="w-full text-[10px] text-muted-foreground hover:text-primary transition-colors py-1.5 border border-dashed border-border/50 hover:border-primary/30 uppercase tracking-wider"
                  >
                    {isExpanded ? `show less` : `+${hiddenCount} more`}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
