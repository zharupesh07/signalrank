"use client";

import { Fragment, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useToast } from "@/components/toast";
import { TagInput } from "@/components/tag-input";
import { Users, Activity, BarChart2, Play, Trash2, Shield, ShieldOff, CheckCircle, XCircle, ChevronDown, ChevronRight, ExternalLink, RefreshCw, RotateCcw, FileText, ScanText } from "lucide-react";

type AdminUser = {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
  last_login: string | null;
  onboarding_complete: boolean;
  run_count: number;
  last_run_status: string | null;
};

type TopJob = {
  job_id: string;
  title: string | null;
  company: string | null;
  location: string | null;
  final_score: number | null;
  semantic_score: number | null;
  skills_score: number | null;
  job_url: string;
};

type AdminRun = {
  run_id: string;
  user_email: string;
  status: string;
  job_count: number | null;
  started_at: string | null;
  finished_at: string | null;
};

type Stats = {
  total_users: number;
  total_jobs: number;
  total_runs: number;
  total_applications: number;
};

type UserProfileConfig = {
  user_id: string;
  email: string;
  onboarding_complete: boolean;
  target_roles: string[];
  preferred_locations: string[];
  custom_search_queries: string[];
  target_lpa: number | null;
  min_yoe: number | null;
  max_yoe: number | null;
  scraper_hours_old: number | null;
  scraper_max_terms: number | null;
  resume_template: string | null;
  config_overrides: Record<string, unknown> | null;
  title_penalty_rules: {
    strong: string[];
    adjacent: string[];
    hybrid: string[];
  };
};

type UserProfileConfigDraft = {
  onboarding_complete: boolean;
  target_roles: string[];
  preferred_locations: string[];
  custom_search_queries: string[];
  target_lpa: string;
  min_yoe: string;
  max_yoe: string;
  scraper_hours_old: string;
  scraper_max_terms: string;
  resume_template: string;
};

function toDraft(config: UserProfileConfig): UserProfileConfigDraft {
  return {
    onboarding_complete: config.onboarding_complete,
    target_roles: [...config.target_roles],
    preferred_locations: [...config.preferred_locations],
    custom_search_queries: [...config.custom_search_queries],
    target_lpa: config.target_lpa != null ? String(config.target_lpa) : "",
    min_yoe: config.min_yoe != null ? String(config.min_yoe) : "",
    max_yoe: config.max_yoe != null ? String(config.max_yoe) : "",
    scraper_hours_old: config.scraper_hours_old != null ? String(config.scraper_hours_old) : "",
    scraper_max_terms: config.scraper_max_terms != null ? String(config.scraper_max_terms) : "",
    resume_template: config.resume_template ?? "",
  };
}

function normalizeDraft(draft: UserProfileConfigDraft) {
  return JSON.stringify({
    onboarding_complete: draft.onboarding_complete,
    target_roles: draft.target_roles,
    preferred_locations: draft.preferred_locations,
    custom_search_queries: draft.custom_search_queries,
    target_lpa: draft.target_lpa.trim(),
    min_yoe: draft.min_yoe.trim(),
    max_yoe: draft.max_yoe.trim(),
    scraper_hours_old: draft.scraper_hours_old.trim(),
    scraper_max_terms: draft.scraper_max_terms.trim(),
    resume_template: draft.resume_template.trim(),
  });
}

function isDraftDirty(draft: UserProfileConfigDraft | undefined, config: UserProfileConfig | undefined) {
  if (!draft || !config) return false;
  return normalizeDraft(draft) !== normalizeDraft(toDraft(config));
}

const INPUT_CLASS =
  "w-full bg-background border border-border px-2.5 py-2 text-xs text-foreground outline-none focus:border-primary transition-colors";

function StatPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-border/70 bg-background px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-medium text-foreground tabular-nums">{value}</div>
    </div>
  );
}

function humanizePenaltyRule(value: string) {
  return value
    .replace(/\\b/g, "")
    .replace(/\\/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function RuleBucket({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="space-y-2 border border-border/60 bg-background/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">{label}</span>
        <span className="text-[10px] tabular-nums text-muted-foreground">{values.length}</span>
      </div>
      {values.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className="px-2 py-1 text-[10px] border border-border text-muted-foreground bg-background"
            >
              {humanizePenaltyRule(value)}
            </span>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-muted-foreground">No rules in this bucket.</div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: "text-primary border-primary/30",
    done: "text-primary border-primary/30",
    failed: "text-destructive border-destructive/30",
    pending: "text-[var(--terminal-yellow)] border-[var(--terminal-yellow)]/30",
    scraping: "text-blue-400 border-blue-400/30",
    ranking: "text-blue-400 border-blue-400/30",
    cancelled: "text-muted-foreground border-border",
  };
  return (
    <span className={`text-[11px] border px-1.5 py-0.5 leading-none uppercase ${colors[status] ?? "text-muted-foreground border-border"}`}>
      {status}
    </span>
  );
}

export default function AdminPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const isAdmin = (session as { isAdmin?: boolean })?.isAdmin ?? false;
  const { toast } = useToast();

  const [tab, setTab] = useState<"users" | "runs">("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [runs, setRuns] = useState<AdminRun[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedUser, setExpandedUser] = useState<string | null>(null);
  const [topJobsCache, setTopJobsCache] = useState<Record<string, TopJob[]>>({});
  const [profileConfigCache, setProfileConfigCache] = useState<Record<string, UserProfileConfig>>({});
  const [profileDrafts, setProfileDrafts] = useState<Record<string, UserProfileConfigDraft>>({});
  const [loadingJobs, setLoadingJobs] = useState<string | null>(null);
  const [loadingConfig, setLoadingConfig] = useState<string | null>(null);
  const [savingConfig, setSavingConfig] = useState<string | null>(null);

  useEffect(() => {
    if (session && !isAdmin) {
      router.replace("/dashboard");
    }
  }, [session, isAdmin, router]);

  useEffect(() => {
    if (!token || !isAdmin) return;
    setLoading(true);
    Promise.all([
      api.admin.stats(token).then(setStats),
      api.admin.users(token).then((r) => setUsers(r.users)),
      api.admin.runs(token).then(setRuns),
    ])
      .catch((err) =>
        toast(
          err instanceof Error ? `Failed to load admin data: ${err.message}` : "Failed to load admin data",
          "error",
        )
      )
      .finally(() => setLoading(false));
  }, [token, isAdmin, toast]);

  async function toggleAdmin(userId: string, current: boolean) {
    await api.admin.updateUser(token, userId, { is_admin: !current });
    setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, is_admin: !current } : u)));
    toast(`Admin ${!current ? "granted" : "revoked"}`, "success");
  }

  async function deleteUser(userId: string, email: string) {
    if (!confirm(`Delete ${email} and all their data?`)) return;
    try {
      await api.admin.deleteUser(token, userId);
      setUsers((prev) => prev.filter((u) => u.id !== userId));
      toast(`Deleted ${email}`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete user", "error");
    }
  }

  async function resetUserJobs(userId: string, email: string) {
    if (!confirm(`Reset ranked jobs and run history for ${email}? Shared jobs_raw rows will be preserved.`)) return;
    try {
      const res = await api.admin.resetJobs(token, userId);
      setTopJobsCache((prev) => {
        const next = { ...prev };
        delete next[userId];
        return next;
      });
      setExpandedUser((prev) => (prev === userId ? null : prev));
      const [updatedRuns, updatedStats, updatedUsers] = await Promise.all([
        api.admin.runs(token),
        api.admin.stats(token),
        api.admin.users(token),
      ]);
      setRuns(updatedRuns);
      setStats(updatedStats);
      setUsers(updatedUsers.users);
      toast(
        `Reset ${res.user_email}: removed ${res.job_results_deleted} results and ${res.runs_deleted} runs; shared jobs preserved`,
        "success",
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to reset jobs", "error");
    }
  }

  async function toggleExpand(userId: string) {
    if (expandedUser === userId) {
      setExpandedUser(null);
      return;
    }
    setExpandedUser(userId);
    const needsJobs = !topJobsCache[userId];
    const needsConfig = !profileConfigCache[userId];
    if (!needsJobs && !needsConfig) return;

    if (needsJobs) setLoadingJobs(userId);
    if (needsConfig) setLoadingConfig(userId);
    try {
      const [jobs, config] = await Promise.all([
        needsJobs ? api.admin.topJobs(token, userId) : Promise.resolve(null),
        needsConfig ? api.admin.profileConfig(token, userId) : Promise.resolve(null),
      ]);
      if (jobs) {
        const seen = new Set<string>();
        const deduped = jobs.filter((j) => { if (seen.has(j.job_id)) return false; seen.add(j.job_id); return true; });
        setTopJobsCache((prev) => ({ ...prev, [userId]: deduped }));
      }
      if (config) {
        setProfileConfigCache((prev) => ({ ...prev, [userId]: config }));
        setProfileDrafts((prev) => ({ ...prev, [userId]: toDraft(config) }));
      }
    } catch {
      toast("Failed to load user details", "error");
    } finally {
      setLoadingJobs(null);
      setLoadingConfig(null);
    }
  }

  function updateDraft(userId: string, patch: Partial<UserProfileConfigDraft>) {
    setProfileDrafts((prev) => ({
      ...prev,
      [userId]: { ...prev[userId], ...patch },
    }));
  }

  function resetDraft(userId: string) {
    const config = profileConfigCache[userId];
    if (!config) return;
    setProfileDrafts((prev) => ({ ...prev, [userId]: toDraft(config) }));
  }

  async function saveUserConfig(userId: string, email: string) {
    const draft = profileDrafts[userId];
    if (!draft) return;
    setSavingConfig(userId);
    try {
      const payload = {
        onboarding_complete: draft.onboarding_complete,
        target_roles: draft.target_roles,
        preferred_locations: draft.preferred_locations,
        custom_search_queries: draft.custom_search_queries,
        target_lpa: draft.target_lpa ? Number(draft.target_lpa) : null,
        min_yoe: draft.min_yoe ? Number(draft.min_yoe) : null,
        max_yoe: draft.max_yoe ? Number(draft.max_yoe) : null,
        scraper_hours_old: draft.scraper_hours_old ? Number(draft.scraper_hours_old) : null,
        scraper_max_terms: draft.scraper_max_terms ? Number(draft.scraper_max_terms) : null,
        resume_template: draft.resume_template || null,
      };
      await api.admin.updateProfileConfig(token, userId, payload);
      const updated = await api.admin.profileConfig(token, userId);
      setProfileConfigCache((prev) => ({ ...prev, [userId]: updated }));
      setProfileDrafts((prev) => ({ ...prev, [userId]: toDraft(updated) }));
      setUsers((prev) => prev.map((u) => (
        u.id === userId ? { ...u, onboarding_complete: updated.onboarding_complete } : u
      )));
      toast(`Updated configuration for ${email}`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update configuration", "error");
    } finally {
      setSavingConfig(null);
    }
  }

  async function triggerRun(userId: string, forceScrape = false) {
    const res = await api.admin.triggerRun(token, userId, forceScrape);
    toast(`Run queued for ${res.user_email}${forceScrape ? " (force scrape)" : ""}`, "success");
    const updated = await api.admin.runs(token);
    setRuns(updated);
  }

  async function forceRegenerateResumes(userId: string, email: string) {
    if (!confirm(`Force regenerate all tailored resumes for ${email}? Existing cached PDFs will be cleared.`)) return;
    const res = await api.admin.forceRegenerateResumes(token, userId);
    toast(`Queued ${res.queued} resume generation task(s) for ${email}`, "success");
  }

  async function reparseResume(userId: string, email: string) {
    try {
      await api.admin.reparseResume(token, userId);
      toast(`Re-parsing resume for ${email} in background`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to queue reparse", "error");
    }
  }

  async function reparseAllResumes() {
    if (!confirm("Re-run resume parse + verify pipeline for ALL users? This will update their resume editor and search profile in the background.")) return;
    try {
      const res = await api.admin.reparseAllResumes(token);
      toast(`Queued re-parse for ${res.queued} users`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to queue reparse", "error");
    }
  }

  if (!isAdmin) return null;

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="mx-auto w-full max-w-7xl px-6 py-8 space-y-7">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="section-label">admin</div>
            <h1 className="text-xl font-bold text-foreground tracking-tight">System Administration</h1>
          </div>
          <button
            onClick={reparseAllResumes}
            className="flex items-center gap-2 px-3 py-2 text-[11px] uppercase tracking-widest border border-border text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors"
            title="Re-run resume parse + verify pipeline for all users"
          >
            <ScanText size={12} />
            Reparse All Resumes
          </button>
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "Users", value: stats.total_users, icon: Users },
              { label: "Jobs", value: stats.total_jobs, icon: BarChart2 },
              { label: "Runs", value: stats.total_runs, icon: Activity },
              { label: "Applications", value: stats.total_applications, icon: CheckCircle },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="stat-card border border-border bg-card p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">{label}</span>
                  <Icon size={12} className="text-muted-foreground" />
                </div>
                <div className="text-3xl font-bold tabular-nums leading-none text-foreground">{value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-border">
          {(["users", "runs"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-xs uppercase tracking-widest transition-colors ${
                tab === t ? "text-primary border-b-2 border-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-center py-12 text-muted-foreground text-sm">Loading...</div>
        ) : tab === "users" ? (
          <div className="overflow-hidden border border-border bg-card">
            <div className="overflow-x-auto">
              <table className="min-w-[1100px] w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/20 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="w-10 px-4 py-3 text-left font-normal"></th>
                    <th className="px-4 py-3 text-left font-normal">Email</th>
                    <th className="px-4 py-3 text-left font-normal">Onboarding</th>
                    <th className="px-4 py-3 text-left font-normal">Runs</th>
                    <th className="px-4 py-3 text-left font-normal">Last Login</th>
                    <th className="px-4 py-3 text-left font-normal">Role</th>
                    <th className="px-4 py-3 text-right font-normal">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <Fragment key={u.id}>
                      <tr key={u.id} className="border-b border-border/70 align-middle">
                        <td className="px-4 py-3">
                          <button
                            onClick={() => toggleExpand(u.id)}
                            className="text-muted-foreground hover:text-foreground transition-colors"
                            title="View top jobs"
                          >
                            {expandedUser === u.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </button>
                        </td>
                        <td className="px-4 py-3 text-foreground">
                          <div className="max-w-[320px] truncate">{u.email}</div>
                        </td>
                        <td className="px-4 py-3">
                          {u.onboarding_complete ? (
                            <div className="inline-flex items-center gap-2 text-primary">
                              <CheckCircle size={14} />
                              <span className="text-xs uppercase tracking-[0.18em]">done</span>
                            </div>
                          ) : (
                            <div className="inline-flex items-center gap-2 text-[var(--terminal-yellow)]">
                              <XCircle size={14} />
                              <span className="text-xs uppercase tracking-[0.18em]">pending</span>
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="tabular-nums text-foreground">{u.run_count}</span>
                            {u.last_run_status && <StatusBadge status={u.last_run_status} />}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs text-muted-foreground">
                          {u.last_login ? new Date(u.last_login).toLocaleDateString([], { month: "short", day: "numeric" }) : "Never"}
                        </td>
                        <td className="px-4 py-3">
                          {u.is_admin ? (
                            <span className="text-[11px] text-primary border border-primary/30 px-1.5 py-0.5 leading-none uppercase">admin</span>
                          ) : (
                            <span className="text-xs text-muted-foreground">user</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => triggerRun(u.id)}
                              className="p-1.5 text-muted-foreground hover:text-primary transition-colors"
                              title="Trigger run"
                            >
                              <Play size={12} />
                            </button>
                            <button
                              onClick={() => triggerRun(u.id, true)}
                              className="p-1.5 text-muted-foreground hover:text-blue-400 transition-colors"
                              title="Force scrape + run"
                            >
                              <RefreshCw size={12} />
                            </button>
                            <button
                              onClick={() => reparseResume(u.id, u.email)}
                              className="p-1.5 text-muted-foreground hover:text-purple-400 transition-colors"
                              title="Re-parse resume (update resume editor + search profile)"
                            >
                              <ScanText size={12} />
                            </button>
                            <button
                              onClick={() => forceRegenerateResumes(u.id, u.email)}
                              className="p-1.5 text-muted-foreground hover:text-green-400 transition-colors"
                              title="Force regenerate all tailored resumes"
                            >
                              <FileText size={12} />
                            </button>
                            <button
                              onClick={() => resetUserJobs(u.id, u.email)}
                              className="p-1.5 text-muted-foreground hover:text-[var(--terminal-yellow)] transition-colors"
                              title="Reset this user's ranked jobs and run history"
                            >
                              <RotateCcw size={12} />
                            </button>
                            <button
                              onClick={() => toggleAdmin(u.id, u.is_admin)}
                              className="p-1.5 text-muted-foreground hover:text-[var(--terminal-yellow)] transition-colors"
                              title={u.is_admin ? "Revoke admin" : "Grant admin"}
                            >
                              {u.is_admin ? <ShieldOff size={12} /> : <Shield size={12} />}
                            </button>
                            <button
                              onClick={() => deleteUser(u.id, u.email)}
                              className="p-1.5 text-muted-foreground hover:text-destructive transition-colors"
                              title="Delete user"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {expandedUser === u.id && (
                        <tr className="border-b border-border/70 bg-muted/25">
                          <td colSpan={7} className="px-6 py-4">
                            <div className="space-y-4">
                              <div className="border border-border/70 bg-card/60 p-4 space-y-3">
                                <div className="flex items-center justify-between gap-3">
                                  <div className="space-y-1">
                                    <div className="text-[11px] uppercase tracking-widest text-muted-foreground">Current Configuration</div>
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <div className="text-sm text-foreground">{u.email}</div>
                                      {isDraftDirty(profileDrafts[u.id], profileConfigCache[u.id]) ? (
                                        <span className="text-[10px] uppercase tracking-[0.16em] border border-[var(--terminal-yellow)]/30 text-[var(--terminal-yellow)] px-2 py-1">
                                          unsaved changes
                                        </span>
                                      ) : (
                                        <span className="text-[10px] uppercase tracking-[0.16em] border border-primary/25 text-primary px-2 py-1">
                                          synced
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <button
                                      onClick={() => resetDraft(u.id)}
                                      disabled={!isDraftDirty(profileDrafts[u.id], profileConfigCache[u.id])}
                                      className="px-3 py-1.5 text-[11px] uppercase tracking-widest border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                    >
                                      Reset
                                    </button>
                                    <button
                                      onClick={() => saveUserConfig(u.id, u.email)}
                                      disabled={savingConfig === u.id || !profileDrafts[u.id]}
                                      className="px-3 py-1.5 text-[11px] uppercase tracking-widest border border-primary/30 text-primary hover:bg-primary/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                    >
                                      {savingConfig === u.id ? "Saving..." : "Save Config"}
                                    </button>
                                  </div>
                                </div>
                                {loadingConfig === u.id || !profileDrafts[u.id] ? (
                                  <div className="text-xs text-muted-foreground py-2">Loading configuration...</div>
                                ) : (
                                  <div className="space-y-3">
                                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                                      <StatPill label="Roles" value={profileDrafts[u.id].target_roles.length} />
                                      <StatPill label="Locations" value={profileDrafts[u.id].preferred_locations.length} />
                                      <StatPill label="Queries" value={profileDrafts[u.id].custom_search_queries.length} />
                                      <StatPill label="Template" value={profileDrafts[u.id].resume_template || "default"} />
                                    </div>

                                    <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
                                      <div className="space-y-3 border border-border/60 bg-background/40 p-3">
                                        <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Search Intent</div>
                                        <div className="grid gap-3 lg:grid-cols-3">
                                          <TagInput
                                            label="Target Roles"
                                            value={profileDrafts[u.id].target_roles}
                                            onChange={(tags) => updateDraft(u.id, { target_roles: tags })}
                                            placeholder="Add target role"
                                          />
                                          <TagInput
                                            label="Preferred Locations"
                                            value={profileDrafts[u.id].preferred_locations}
                                            onChange={(tags) => updateDraft(u.id, { preferred_locations: tags })}
                                            placeholder="Add preferred location"
                                          />
                                          <TagInput
                                            label="Custom Search Queries"
                                            value={profileDrafts[u.id].custom_search_queries}
                                            onChange={(tags) => updateDraft(u.id, { custom_search_queries: tags })}
                                            placeholder="Add search query"
                                          />
                                        </div>
                                      </div>

                                      <div className="space-y-3 border border-border/60 bg-background/40 p-3">
                                        <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Run Controls</div>
                                        <div className="grid gap-3 sm:grid-cols-2">
                                          <label className="space-y-1">
                                            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Target LPA</span>
                                            <input
                                              value={profileDrafts[u.id].target_lpa}
                                              onChange={(e) => updateDraft(u.id, { target_lpa: e.target.value })}
                                              className={INPUT_CLASS}
                                            />
                                          </label>
                                          <label className="space-y-1">
                                            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Resume Template</span>
                                            <input
                                              value={profileDrafts[u.id].resume_template}
                                              onChange={(e) => updateDraft(u.id, { resume_template: e.target.value })}
                                              className={INPUT_CLASS}
                                            />
                                          </label>
                                          <label className="space-y-1">
                                            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Min YOE</span>
                                            <input
                                              value={profileDrafts[u.id].min_yoe}
                                              onChange={(e) => updateDraft(u.id, { min_yoe: e.target.value })}
                                              className={INPUT_CLASS}
                                            />
                                          </label>
                                          <label className="space-y-1">
                                            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Max YOE</span>
                                            <input
                                              value={profileDrafts[u.id].max_yoe}
                                              onChange={(e) => updateDraft(u.id, { max_yoe: e.target.value })}
                                              className={INPUT_CLASS}
                                            />
                                          </label>
                                          <label className="space-y-1">
                                            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Scraper Hours Old</span>
                                            <input
                                              value={profileDrafts[u.id].scraper_hours_old}
                                              onChange={(e) => updateDraft(u.id, { scraper_hours_old: e.target.value })}
                                              className={INPUT_CLASS}
                                            />
                                          </label>
                                          <label className="space-y-1">
                                            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Scraper Max Terms</span>
                                            <input
                                              value={profileDrafts[u.id].scraper_max_terms}
                                              onChange={(e) => updateDraft(u.id, { scraper_max_terms: e.target.value })}
                                              className={INPUT_CLASS}
                                            />
                                          </label>
                                        </div>

                                        <label className="flex items-center justify-between gap-3 border border-border/60 bg-card px-3 py-2">
                                          <div>
                                            <div className="text-[11px] uppercase tracking-widest text-muted-foreground">Onboarding Complete</div>
                                            <div className="text-xs text-muted-foreground mt-1">Controls whether the user is treated as fully configured.</div>
                                          </div>
                                          <input
                                            type="checkbox"
                                            checked={profileDrafts[u.id].onboarding_complete}
                                            onChange={(e) => updateDraft(u.id, { onboarding_complete: e.target.checked })}
                                            className="h-4 w-4"
                                          />
                                        </label>
                                      </div>
                                    </div>

                                    <div className="space-y-3">
                                      <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Effective Role Penalties</div>
                                      <div className="grid gap-3 lg:grid-cols-3">
                                        <RuleBucket
                                          label="Strong Penalties"
                                          values={profileConfigCache[u.id]?.title_penalty_rules?.strong ?? []}
                                        />
                                        <RuleBucket
                                          label="Adjacent Roles"
                                          values={profileConfigCache[u.id]?.title_penalty_rules?.adjacent ?? []}
                                        />
                                        <RuleBucket
                                          label="Hybrid Roles"
                                          values={profileConfigCache[u.id]?.title_penalty_rules?.hybrid ?? []}
                                        />
                                      </div>
                                    </div>

                                    <details className="border border-border/60 bg-background/40 px-3 py-2">
                                      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[11px] uppercase tracking-widest text-muted-foreground">
                                        <span>Stored Config Overrides</span>
                                        <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">read only</span>
                                      </summary>
                                      <pre className="mt-3 max-h-44 overflow-auto bg-background border border-border px-3 py-3 text-[11px] text-muted-foreground whitespace-pre-wrap break-words">
                                        {JSON.stringify(profileConfigCache[u.id]?.config_overrides ?? {}, null, 2)}
                                      </pre>
                                    </details>
                                  </div>
                                )}
                              </div>
                              <details className="border border-border/70 bg-card/60 px-4 py-3">
                                <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                                  <div>
                                    <div className="text-[11px] uppercase tracking-widest text-muted-foreground">Top Jobs</div>
                                    <div className="text-xs text-muted-foreground mt-1">Expand to inspect this user’s highest-ranked current jobs.</div>
                                  </div>
                                  <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                                    {topJobsCache[u.id]?.length ?? 0} rows
                                  </span>
                                </summary>
                                <div className="mt-3">
                                  {loadingJobs === u.id ? (
                                    <div className="text-xs text-muted-foreground py-2">Loading top jobs...</div>
                                  ) : topJobsCache[u.id]?.length ? (
                                    <div className="max-h-[420px] overflow-auto">
                                      <table className="min-w-[760px] w-full text-xs">
                                        <thead>
                                          <tr className="text-muted-foreground uppercase tracking-widest">
                                            <th className="pb-2 pr-3 text-left font-normal w-[35%]">Title</th>
                                            <th className="pb-2 pr-3 text-left font-normal w-[20%]">Company</th>
                                            <th className="pb-2 pr-3 text-left font-normal w-[15%]">Location</th>
                                            <th className="pb-2 text-right font-normal w-[10%]">Final</th>
                                            <th className="pb-2 text-right font-normal w-[10%]">Semantic</th>
                                            <th className="pb-2 text-right font-normal w-[10%]">Skills</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {topJobsCache[u.id].map((j) => (
                                            <tr key={j.job_id} className="border-t border-border/50">
                                              <td className="py-1.5 pr-3">
                                                <a href={j.job_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 truncate text-foreground hover:text-primary">
                                                  {j.title ?? "—"}
                                                  <ExternalLink size={10} className="shrink-0 text-muted-foreground" />
                                                </a>
                                              </td>
                                              <td className="py-1.5 pr-3 text-muted-foreground truncate">{j.company ?? "—"}</td>
                                              <td className="py-1.5 pr-3 text-muted-foreground truncate">{j.location ?? "—"}</td>
                                              <td className="py-1.5 text-right tabular-nums font-medium text-foreground">{j.final_score != null ? j.final_score.toFixed(2) : "—"}</td>
                                              <td className="py-1.5 text-right tabular-nums text-muted-foreground">{j.semantic_score != null ? j.semantic_score.toFixed(2) : "—"}</td>
                                              <td className="py-1.5 text-right tabular-nums text-muted-foreground">{j.skills_score != null ? j.skills_score.toFixed(2) : "—"}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  ) : (
                                    <div className="text-xs text-muted-foreground py-2">No job results yet.</div>
                                  )}
                                </div>
                              </details>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="overflow-hidden border border-border bg-card">
            <div className="overflow-x-auto">
              <table className="min-w-[920px] w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/20 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="px-4 py-3 text-left font-normal">User</th>
                    <th className="px-4 py-3 text-left font-normal">Status</th>
                    <th className="px-4 py-3 text-left font-normal">Jobs</th>
                    <th className="px-4 py-3 text-left font-normal">Started</th>
                    <th className="px-4 py-3 text-left font-normal">Finished</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id} className="border-b border-border/70">
                      <td className="px-4 py-3 text-foreground">
                        <div className="max-w-[320px] truncate">{r.user_email}</div>
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                      <td className="px-4 py-3 tabular-nums text-foreground">{r.job_count ?? "—"}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {r.started_at ? new Date(r.started_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {r.finished_at ? new Date(r.finished_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {runs.length === 0 && (
              <div className="text-center py-8 text-muted-foreground text-sm">No runs yet</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
