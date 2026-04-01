"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { swr } from "@/lib/cache";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import type { Job, Run } from "@/types";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { JobCardSkeleton, StatCardSkeleton } from "@/components/skeleton";
import { RefreshCw, ExternalLink, TrendingUp, Layers, Clock, BarChart2, Plus, AlertCircle } from "lucide-react";
import Link from "next/link";
import AddJobModal from "@/components/add-job-modal";

type Analytics = {
  score_distribution: { range: string; count: number }[];
  top_companies: { company: string; count: number }[];
  sites: { site: string; count: number }[];
  total: number;
};

function MiniBarChart({ data, maxVal, color = "var(--primary)" }: { data: { label: string; count: number }[]; maxVal: number; color?: string }) {
  return (
    <div className="space-y-1.5">
      {data.map(({ label, count }) => (
        <div key={label} className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-16 shrink-0 truncate">{label}</span>
          <div className="flex-1 h-1.5 bg-muted relative overflow-hidden">
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${(count / maxVal) * 100}%`, background: color }}
            />
          </div>
          <span className="text-xs text-muted-foreground tabular-nums w-6 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

function scoreColor(score: number) {
  if (score >= 0.75) return "var(--primary)";
  if (score >= 0.60) return "var(--terminal-green-bright)";
  if (score >= 0.45) return "var(--terminal-yellow)";
  return "var(--chart-4)";
}

function ScoreDisplay({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = scoreColor(score);
  return (
    <div className="flex flex-col items-end gap-1.5 shrink-0">
      <span className="text-base font-bold tabular-nums leading-none" style={{ color }}>
        {pct}
      </span>
      <div className="score-bar w-16">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} />
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  accent = false,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  accent?: boolean;
}) {
  return (
    <div className="stat-card card-hover border border-border bg-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">{label}</span>
        <Icon size={12} className={accent ? "text-primary" : "text-muted-foreground"} />
      </div>
      <div className={`text-3xl font-bold tabular-nums leading-none ${accent ? "text-primary text-glow-dim" : "text-foreground"}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted-foreground leading-snug">{sub}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [addJobOpen, setAddJobOpen] = useState(false);
  const [onboardingComplete, setOnboardingComplete] = useState<boolean | null>(null);

  const loadJobs = useCallback(async () => {
    if (!token) return;
    const r = await api.jobs.list(token, { page: 1, limit: 10 });
    setJobs(r.jobs);
  }, [token]);

  const loadAnalytics = useCallback(async () => {
    if (!token) return;
    api.jobs.analytics(token).then(setAnalytics).catch(() => null);
  }, [token]);

  useEffect(() => {
    if (!token) {
      setJobs([]);
      setRun(null);
      setAnalytics(null);
      setTracked(new Set());
      setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all([
      swr("dash:jobs", () => api.jobs.list(token, { page: 1, limit: 10 }).then((r) => r.jobs), setJobs),
      swr("dash:run", () => api.runs.latest(token), setRun),
      swr("analytics", () => api.jobs.analytics(token), setAnalytics),
      swr("dash:tracked", () => api.applications.list(token).then((apps) => new Set(apps.filter((a) => a.job_id).map((a) => a.job_id!))), setTracked),
      api.profile.get(token).then((p) => setOnboardingComplete(p.onboarding_complete)).catch(() => null),
    ]).finally(() => setLoading(false));
  }, [token]);

  async function triggerRun() {
    setTriggering(true);
    const optimisticRun = makeQueuedRun(`local-${Date.now()}`);
    setRun(optimisticRun);
    try {
      const res = await api.runs.trigger(token);
      const queuedRun = makeQueuedRun(res.run_id);
      setRun(queuedRun);
      upsertRunCaches(queuedRun);
      toast("Run queued", "info");
    } catch (err) {
      setRun((current) => (current?.id === optimisticRun.id ? null : current));
      toast(err instanceof Error ? err.message : "Failed to trigger run", "error");
    } finally {
      setTriggering(false);
    }
  }

  async function trackJob(job: Job) {
    await api.applications.create(token, { job_id: job.id, company: job.company, title: job.title, status: "interested", system_score: job.final_score, resume_match_pct: job.semantic_score });
    setTracked((prev) => new Set(prev).add(job.id));
    toast("Added to tracker", "success");
  }

  async function handleRunComplete(completed: Run) {
    setRun(completed);
    upsertRunCaches(completed);
    loadJobs();
    loadAnalytics();
    if (completed.id && completed.status === "done") {
      try {
        const res = await api.applications.importFromRun(token, { run_id: completed.id, min_score: 0.70, limit: 20 });
        if (res.created > 0) {
          toast(`Auto-imported ${res.created} top matches to tracker`, "success");
        }
      } catch {
        // silent — auto-import is best-effort
      }
    }
  }

  const topScore = jobs.length > 0 ? Math.max(...jobs.map((j) => j.final_score ?? 0)) : null;
  const lastRunTime = run?.started_at
    ? new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;
  const isRunActive = ["pending", "running", "scraping", "ranking"].includes(run?.status ?? "");

  return (
    <>
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-7">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="section-label">dashboard</div>
            <h1 className="text-xl font-bold text-foreground tracking-tight">Top Matches</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAddJobOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded hover:opacity-90"
            >
              <Plus size={14} />
              Add Job
            </button>
            <div className="flex items-center gap-2">
              <button
                onClick={triggerRun}
                disabled={triggering || isRunActive || onboardingComplete === false}
                title={onboardingComplete === false ? "Complete onboarding first" : undefined}
                className="flex items-center gap-2 px-4 py-2.5 text-xs border border-primary/50 text-primary hover:bg-primary hover:text-background hover:border-primary transition-all duration-150 disabled:opacity-30 disabled:cursor-not-allowed uppercase tracking-widest font-bold"
              >
                <RefreshCw size={11} className={triggering || isRunActive ? "spin-slow" : ""} />
                {triggering ? "Queuing..." : isRunActive ? "Running..." : "Quick Scan"}
              </button>
              {run?.started_at && !isRunActive && (
                <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                  {new Date(run.started_at).toLocaleDateString([], { month: "short", day: "numeric" })}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Onboarding banner */}
        {onboardingComplete === false && (
          <div className="flex items-center gap-3 px-4 py-3 border border-[var(--terminal-yellow)]/30 bg-[var(--terminal-yellow)]/5">
            <AlertCircle size={14} className="text-[var(--terminal-yellow)] shrink-0" />
            <span className="text-sm text-foreground">Complete onboarding to start scanning for jobs.</span>
            <Link href="/onboarding" className="ml-auto text-xs text-primary border border-primary/50 px-3 py-1.5 hover:bg-primary hover:text-background transition-all uppercase tracking-widest font-bold">
              Complete Setup
            </Link>
          </div>
        )}

        {/* Stat cards */}
        <div className="grid grid-cols-3 gap-3">
          {loading ? (
            <><StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton /></>
          ) : (
            <>
              <StatCard label="Jobs Indexed" value={analytics?.total ?? 0} sub={run?.scrape_count != null ? `${run.scrape_count} scraped last run` : "run a scan to populate"} icon={Layers} accent />
              <StatCard
                label="Top Score"
                value={topScore != null ? `${Math.round(topScore * 100)}%` : "—"}
                sub={topScore != null ? (topScore >= 0.8 ? "Excellent match" : topScore >= 0.65 ? "Good match" : "Fair match") : "Run a scan first"}
                icon={TrendingUp}
              />
              <StatCard
                label="Last Run"
                value={lastRunTime ?? "Never"}
                sub={run ? `${run.job_count ?? 0} jobs · ${run.status}` : "No runs yet"}
                icon={Clock}
              />
            </>
          )}
        </div>

        {/* Run progress */}
        {run && <RunProgress run={run} onComplete={handleRunComplete} />}

        {/* Analytics */}
        {analytics && analytics.total > 0 && (
          <div>
            <div className="section-label mb-3">signal analytics</div>
            <div className="grid grid-cols-2 gap-3">
              <div className="stat-card border border-border bg-card p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Score Distribution</span>
                  <BarChart2 size={12} className="text-muted-foreground" />
                </div>
                <MiniBarChart
                  data={analytics.score_distribution.map((d) => ({ label: d.range, count: d.count }))}
                  maxVal={Math.max(...analytics.score_distribution.map((d) => d.count), 1)}
                />
              </div>
              <div className="stat-card border border-border bg-card p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Top Companies</span>
                  <BarChart2 size={12} className="text-muted-foreground" />
                </div>
                <MiniBarChart
                  data={analytics.top_companies.slice(0, 6).map((d) => ({ label: d.company, count: d.count }))}
                  maxVal={Math.max(...analytics.top_companies.map((d) => d.count), 1)}
                  color="var(--terminal-green-bright)"
                />
              </div>
            </div>
            {analytics.sites.length > 0 && (
              <div className="mt-3 border border-border bg-card px-5 py-4 flex items-center gap-6">
                <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em] shrink-0">Sources</span>
                <div className="flex items-center gap-4 flex-wrap">
                  {analytics.sites.map(({ site, count }) => (
                    <div key={site} className="flex items-center gap-2">
                      <span className="text-xs text-secondary-foreground">{site}</span>
                      <span className="text-xs text-muted-foreground tabular-nums">({count})</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Job list */}
        <div>
          <div className="section-label mb-3">top 10 matches</div>

          {loading ? (
            <div className="space-y-px">
              {Array.from({ length: 5 }).map((_, i) => <JobCardSkeleton key={i} />)}
            </div>
          ) : jobs.length === 0 ? (
            <div className="border border-border bg-card p-12 text-center">
              <div className="inline-block text-left font-mono text-[12px] leading-relaxed">
                <div className="text-primary/30">┌──────────────────────────────┐</div>
                <div>
                  <span className="text-primary/30">│ </span>
                  <span className="text-primary">&gt;</span>
                  <span className="text-muted-foreground"> No signals detected.</span>
                  <span className="text-primary/30">       │</span>
                </div>
                <div>
                  <span className="text-primary/30">│ </span>
                  <span className="text-primary">&gt;</span>
                  <span className="text-muted-foreground"> Click Refresh Jobs to scan.</span>
                  <span className="text-primary/30">  │</span>
                </div>
                <div>
                  <span className="text-primary/30">│ </span>
                  <span className="text-primary cursor-blink"> </span>
                  <span className="text-primary/30">                             │</span>
                </div>
                <div className="text-primary/30">└──────────────────────────────┘</div>
              </div>
            </div>
          ) : (
            <div className="space-y-px">
              {jobs.map((job, idx) => (
                <div
                  key={job.id}
                  className="job-row flex items-center gap-4 px-4 py-3.5 bg-card border border-border animate-in"
                  style={{ animationDelay: `${idx * 35}ms` }}
                >
                  <span className="text-[11px] font-bold tabular-nums w-5 shrink-0 text-center" style={{ color: idx === 0 ? "var(--terminal-green-bright)" : idx < 3 ? "var(--primary)" : "var(--border)" }}>
                    {String(idx + 1).padStart(2, "0")}
                  </span>

                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-foreground truncate">{job.title}</div>
                    <div className="text-[11px] text-muted-foreground truncate mt-0.5">
                      {job.company}{job.location ? ` · ${job.location}` : ""}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {job.company_tier && (
                      <span className="text-[11px] text-muted-foreground border border-border px-1.5 py-0.5 leading-none">{job.company_tier.replace("tier_", "").toUpperCase()}</span>
                    )}
                    {job.is_contract && (
                      <span className="text-[11px] text-[var(--terminal-yellow)] border border-[var(--terminal-yellow)]/20 px-1.5 py-0.5 leading-none">CONTRACT</span>
                    )}
                    {job.site && <span className="text-[11px] text-border hidden md:block">{job.site}</span>}
                  </div>

                  {job.final_score != null && <ScoreDisplay score={job.final_score} />}

                  {tracked.has(job.id) ? (
                    <span className="text-[11px] text-muted-foreground uppercase tracking-wider shrink-0">tracked</span>
                  ) : (
                    <button
                      onClick={() => trackJob(job)}
                      className="flex items-center gap-0.5 text-[11px] text-primary/60 border border-primary/20 px-1.5 py-0.5 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider shrink-0"
                    >
                      <Plus size={8} />track
                    </button>
                  )}

                  <a href={job.job_url} target="_blank" rel="noreferrer" className="text-border hover:text-primary transition-colors shrink-0">
                    <ExternalLink size={13} />
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
    <AddJobModal
      open={addJobOpen}
      onClose={() => setAddJobOpen(false)}
      onAdded={loadJobs}
    />
    </>
  );
}
