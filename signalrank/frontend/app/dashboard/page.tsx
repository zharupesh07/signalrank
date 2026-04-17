"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { usePathname, useRouter } from "next/navigation";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { JobCardSkeleton, StatCardSkeleton } from "@/components/skeleton";
import { RefreshCw, ExternalLink, TrendingUp, Layers, Clock, BarChart2, Plus, AlertCircle, ArrowRight, BriefcaseBusiness, Sparkles, Radar, History } from "lucide-react";
import Link from "next/link";
import AddJobModal from "@/components/add-job-modal";
import { MiniBarChart, ScoreDisplay, explainJob, StatCard } from "./dashboard-ui";
import { useDashboardData } from "./use-dashboard-data";
import { isLiveRunStatus } from "@/types";

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const isAdmin = (session as { isAdmin?: boolean })?.isAdmin ?? false;
  const { toast } = useToast();

  const [addJobOpen, setAddJobOpen] = useState(false);
  const {
    analytics,
    handleRunComplete,
    jobs,
    loadJobs,
    loading,
    mounted,
    newGoodMatches,
    onboardingComplete,
    run,
    tracked,
    trackJob,
    triggering,
    triggerRun,
  } = useDashboardData({ token, toast });

  const topScore = jobs.length > 0 ? Math.max(...jobs.map((j) => j.final_score ?? 0)) : null;
  const lastRunTime = run?.started_at
    ? new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;
  const isRunActive = isLiveRunStatus(run?.status);
  const topMatches = jobs.slice(0, 3);
  const nextActionLabel = isRunActive
    ? "A scan is in progress. Keep this page open for live status, then jump straight into the explorer."
    : jobs.length > 0
      ? "Review top matches first, then move the strongest ones into the tracker."
      : "Run a scan to populate your first batch of ranked jobs.";

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(`/login?callbackUrl=${encodeURIComponent(pathname)}`);
    }
  }, [pathname, router, status]);

  if (status === "loading" || status === "unauthenticated") {
    return (
      <div className="pt-14 min-h-screen page-content">
        <div className="max-w-4xl mx-auto px-6 py-8">
          <div className="border border-border bg-card p-6 text-sm text-muted-foreground">
            Loading dashboard session...
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-7">

        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="section-label">matches workspace</div>
            <h1 className="text-xl font-bold text-foreground tracking-tight">Command Center</h1>
            <p className="text-sm text-muted-foreground max-w-2xl">
              Start scans, watch progress, review the strongest signals, and move the best roles into your tracker from one place.
            </p>
          </div>
          <div className="flex min-w-[148px] shrink-0 flex-col items-stretch gap-2">
            <button
              onClick={() => setAddJobOpen(true)}
              className="inline-flex items-center justify-center gap-1.5 border border-border bg-card px-3 py-2 text-[10px] font-bold uppercase tracking-[0.18em] text-foreground transition-all hover:border-primary/40 hover:text-primary"
            >
              <Plus size={10} />
              Add Job
            </button>
            {isAdmin && (
              <button
                onClick={triggerRun}
                disabled={triggering || isRunActive || onboardingComplete === false}
                title={onboardingComplete === false ? "Complete onboarding first" : undefined}
                className="inline-flex items-center justify-center gap-1.5 border border-primary/40 bg-primary/8 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-primary transition-all duration-150 hover:bg-primary hover:text-background hover:border-primary disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <RefreshCw size={10} className={triggering || isRunActive ? "spin-slow" : ""} />
                {triggering ? "Queuing..." : isRunActive ? "Refreshing..." : "Refresh Jobs"}
              </button>
            )}
            {mounted && run?.started_at && !isRunActive && (
              <span className="text-[10px] text-right text-muted-foreground whitespace-nowrap">
                Last run {new Date(run.started_at).toLocaleDateString([], { month: "short", day: "numeric" })}
              </span>
            )}
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

        <div className="grid grid-cols-1 md:grid-cols-[1.4fr_1fr] gap-3">
          <div className="stat-card border border-border bg-card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Primary Flow</div>
                <h2 className="text-lg font-semibold text-foreground mt-1">Scan, review, track</h2>
              </div>
              <Radar size={14} className="text-primary" />
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {nextActionLabel}
            </p>
            <div className="flex flex-wrap gap-2">
              <Link href="/jobs" className="inline-flex items-center gap-1.5 px-3 py-2 text-xs border border-primary/40 text-primary hover:bg-primary hover:text-background transition-all uppercase tracking-wider font-bold">
                Review All Matches
                <ArrowRight size={11} />
              </Link>
              <Link href="/tracker" className="inline-flex items-center gap-1.5 px-3 py-2 text-xs border border-border text-foreground hover:border-primary hover:text-primary transition-all uppercase tracking-wider font-bold">
                Open Tracker
              </Link>
            </div>
          </div>

          <div className="stat-card border border-border bg-card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">What Happens Next</div>
                <h2 className="text-lg font-semibold text-foreground mt-1">Latest run summary</h2>
              </div>
              <History size={14} className="text-muted-foreground" />
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Corpus update</span>
                <span className="text-foreground font-medium tabular-nums">
                  {run?.scrape_reason === "executed"
                    ? `${run.scrape_count ?? 0} scraped`
                    : run?.run_kind === "rerank_only"
                      ? "re-rank only"
                      : run?.scrape_reason === "recent_auto_refresh"
                        ? "reused recent scrape"
                        : "pending"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Top matches ranked</span>
                <span className="text-foreground font-medium tabular-nums">{jobs.length}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Already tracked</span>
                <span className="text-foreground font-medium tabular-nums">{tracked.size}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">New good matches</span>
                <span className="text-foreground font-medium tabular-nums">{newGoodMatches}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {loading ? (
            <><StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton /></>
          ) : (
            <>
              <StatCard label="Jobs Indexed" value={analytics?.total ?? 0} sub={run?.scrape_reason === "executed" ? `${run.scrape_count ?? 0} scraped last refresh` : run?.run_kind === "rerank_only" ? "last run reused current corpus" : "run a refresh to update corpus"} icon={Layers} accent />
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
              <StatCard
                label="Tracked"
                value={tracked.size}
                sub={tracked.size > 0 ? "roles already moved forward" : "save promising jobs here"}
                icon={BriefcaseBusiness}
              />
              <StatCard
                label="New Good Matches"
                value={newGoodMatches}
                sub={newGoodMatches > 0 ? "fresh strong matches from the latest run" : "no fresh strong matches right now"}
                icon={Sparkles}
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

        {/* Top match strip */}
        <div>
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <div className="section-label">top matches</div>
              <div className="text-sm text-muted-foreground mt-1">Start here before opening the full explorer.</div>
            </div>
            <Link href="/jobs" className="text-xs text-primary hover:text-[var(--terminal-green-bright)] transition-colors uppercase tracking-widest font-bold">
              open explorer
            </Link>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              {Array.from({ length: 3 }).map((_, i) => <JobCardSkeleton key={i} />)}
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
                  <span className="text-muted-foreground"> Click Refresh Jobs to update the corpus.</span>
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
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              {topMatches.map((job, idx) => {
                const reasons = explainJob(job);
                return (
                <div
                  key={job.id}
                  className="job-row bg-card border border-border p-4 space-y-4 animate-in"
                  style={{ animationDelay: `${idx * 35}ms` }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-[11px] font-bold tabular-nums px-2 py-1 border border-border" style={{ color: idx === 0 ? "var(--terminal-green-bright)" : "var(--primary)" }}>
                          #{idx + 1}
                        </span>
                        {job.company_tier && (
                          <span className="text-[11px] text-muted-foreground border border-border px-1.5 py-0.5 leading-none">
                            {job.company_tier.replace("tier_", "").toUpperCase()}
                          </span>
                        )}
                      </div>
                      <div className="text-[15px] font-semibold text-foreground leading-snug">{job.title}</div>
                      <div className="text-[12px] text-muted-foreground mt-1">
                        {job.company}{job.location ? ` · ${job.location}` : ""}
                      </div>
                    </div>
                    {job.final_score != null && <ScoreDisplay score={job.final_score} />}
                  </div>

                  <div className="space-y-2">
                    <div className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Why it matched</div>
                    <div className="flex flex-wrap gap-2">
                      {reasons.length > 0 ? reasons.map((reason) => (
                        <span key={reason} className="text-[11px] px-2 py-1 border border-primary/20 text-primary/90 bg-primary/5">
                          {reason}
                        </span>
                      )) : (
                        <span className="text-[11px] text-muted-foreground">high blended score across title, skills, and recency</span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      {job.site && <span className="text-[11px] text-border">{job.site}</span>}
                      {job.is_contract && (
                        <span className="text-[11px] text-[var(--terminal-yellow)] border border-[var(--terminal-yellow)]/20 px-1.5 py-0.5 leading-none">CONTRACT</span>
                      )}
                      {job.is_new_find && (
                        <span className="text-[11px] text-[var(--terminal-green-bright)] border border-[var(--terminal-green-bright)]/25 px-1.5 py-0.5 leading-none uppercase tracking-wider">new find</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {tracked.has(job.id) ? (
                        <span className="text-[11px] text-muted-foreground uppercase tracking-wider shrink-0">tracked</span>
                      ) : (
                        <button
                          onClick={() => trackJob(job)}
                          className="flex items-center gap-1 text-[11px] text-primary/70 border border-primary/20 px-2 py-1 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider"
                        >
                          <Plus size={8} />
                          track
                        </button>
                      )}
                      <a href={job.job_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-muted-foreground border border-border px-2 py-1 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider">
                        open
                        <ExternalLink size={11} />
                      </a>
                    </div>
                  </div>
                </div>
              )})}
            </div>
          )}
        </div>

        {jobs.length > topMatches.length && (
          <div className="border border-border bg-card px-4 py-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Sparkles size={14} className="text-primary" />
              <span>{jobs.length - topMatches.length} more ranked jobs are ready in the explorer.</span>
            </div>
            <Link href="/jobs" className="text-xs text-primary border border-primary/40 px-3 py-1.5 hover:bg-primary hover:text-background transition-all uppercase tracking-widest font-bold">
              Review All Jobs
            </Link>
          </div>
        )}
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
