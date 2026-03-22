"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Job, Run } from "@/types";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { JobCardSkeleton, StatCardSkeleton } from "@/components/skeleton";
import { RefreshCw, ExternalLink, TrendingUp, Layers, Clock } from "lucide-react";

function scoreColor(score: number) {
  if (score >= 0.8) return "#22c55e";
  if (score >= 0.65) return "#a3e635";
  if (score >= 0.5) return "#facc15";
  return "#f97316";
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
    <div className="stat-card card-hover border border-[#2a2a2e] bg-[#111113] p-5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[#52525b] uppercase tracking-[0.15em]">{label}</span>
        <Icon size={12} className={accent ? "text-[#22c55e]" : "text-[#3f3f46]"} />
      </div>
      <div className={`text-3xl font-bold tabular-nums leading-none ${accent ? "text-[#22c55e] text-glow-dim" : "text-[#d4d4d8]"}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-[#52525b] leading-snug">{sub}</div>}
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

  const loadJobs = useCallback(async () => {
    if (!token) return;
    const r = await api.jobs.list(token, 1, 10);
    setJobs(r.jobs);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api.jobs.list(token, 1, 10).then((r) => setJobs(r.jobs)),
      api.runs.latest(token).then(setRun).catch(() => null),
    ]).finally(() => setLoading(false));
  }, [token]);

  async function triggerRun() {
    setTriggering(true);
    try {
      const res = await api.runs.trigger(token);
      setRun({
        id: res.run_id,
        status: "pending",
        started_at: new Date().toISOString(),
        finished_at: null,
        job_count: null,
      });
      toast("Run queued", "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to trigger run", "error");
    } finally {
      setTriggering(false);
    }
  }

  function handleRunComplete(completed: Run) {
    setRun(completed);
    loadJobs();
  }

  const topScore = jobs.length > 0 ? Math.max(...jobs.map((j) => j.final_score ?? 0)) : null;
  const lastRunTime = run?.started_at
    ? new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;
  const isRunActive = run?.status === "pending" || run?.status === "running";

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-7">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="section-label">dashboard</div>
            <h1 className="text-xl font-bold text-[#d4d4d8] tracking-tight">Top Matches</h1>
          </div>
          <button
            onClick={triggerRun}
            disabled={triggering || isRunActive}
            className="flex items-center gap-2 px-4 py-2.5 text-xs border border-[#22c55e]/50 text-[#22c55e] hover:bg-[#22c55e] hover:text-[#080808] hover:border-[#22c55e] transition-all duration-150 disabled:opacity-30 disabled:cursor-not-allowed uppercase tracking-widest font-bold"
          >
            <RefreshCw size={11} className={triggering || isRunActive ? "spin-slow" : ""} />
            {triggering ? "Queuing..." : isRunActive ? "Running..." : "Refresh Jobs"}
          </button>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-3 gap-3">
          {loading ? (
            <><StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton /></>
          ) : (
            <>
              <StatCard label="Jobs Ranked" value={run?.job_count ?? jobs.length} sub="in latest run" icon={Layers} accent />
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

        {/* Job list */}
        <div>
          <div className="section-label mb-3">top 10 matches</div>

          {loading ? (
            <div className="space-y-px">
              {Array.from({ length: 5 }).map((_, i) => <JobCardSkeleton key={i} />)}
            </div>
          ) : jobs.length === 0 ? (
            <div className="border border-[#2a2a2e] bg-[#111113] p-12 text-center">
              <div className="inline-block text-left font-mono text-[12px] leading-relaxed">
                <div className="text-[#22c55e]/30">┌──────────────────────────────┐</div>
                <div>
                  <span className="text-[#22c55e]/30">│ </span>
                  <span className="text-[#22c55e]">&gt;</span>
                  <span className="text-[#52525b]"> No signals detected.</span>
                  <span className="text-[#22c55e]/30">       │</span>
                </div>
                <div>
                  <span className="text-[#22c55e]/30">│ </span>
                  <span className="text-[#22c55e]">&gt;</span>
                  <span className="text-[#52525b]"> Click Refresh Jobs to scan.</span>
                  <span className="text-[#22c55e]/30">  │</span>
                </div>
                <div>
                  <span className="text-[#22c55e]/30">│ </span>
                  <span className="text-[#22c55e] cursor-blink"> </span>
                  <span className="text-[#22c55e]/30">                             │</span>
                </div>
                <div className="text-[#22c55e]/30">└──────────────────────────────┘</div>
              </div>
            </div>
          ) : (
            <div className="space-y-px">
              {jobs.map((job, idx) => (
                <div
                  key={job.id}
                  className="job-row flex items-center gap-4 px-4 py-3.5 bg-[#111113] border border-[#2a2a2e] animate-in"
                  style={{ animationDelay: `${idx * 35}ms` }}
                >
                  <span className="text-[11px] font-bold tabular-nums w-5 shrink-0 text-center" style={{ color: idx === 0 ? "#a3e635" : idx < 3 ? "#22c55e" : "#2a2a2e" }}>
                    {String(idx + 1).padStart(2, "0")}
                  </span>

                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-[#d4d4d8] truncate">{job.title}</div>
                    <div className="text-[11px] text-[#52525b] truncate mt-0.5">
                      {job.company}{job.location ? ` · ${job.location}` : ""}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {job.company_tier && (
                      <span className="text-[9px] text-[#3f3f46] border border-[#2a2a2e] px-1.5 py-0.5 leading-none">T{job.company_tier}</span>
                    )}
                    {job.is_contract && (
                      <span className="text-[9px] text-[#facc15] border border-[#facc15]/20 px-1.5 py-0.5 leading-none">CONTRACT</span>
                    )}
                    {job.site && <span className="text-[9px] text-[#2a2a2e] hidden md:block">{job.site}</span>}
                  </div>

                  {job.final_score != null && <ScoreDisplay score={job.final_score} />}

                  <a href={job.job_url} target="_blank" rel="noreferrer" className="text-[#2a2a2e] hover:text-[#22c55e] transition-colors shrink-0">
                    <ExternalLink size={13} />
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
