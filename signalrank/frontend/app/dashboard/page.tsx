"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Job, Run } from "@/types";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { JobCardSkeleton, StatCardSkeleton } from "@/components/skeleton";
import { RefreshCw, ExternalLink } from "lucide-react";

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`text-xs font-bold tabular-nums ${score >= 0.8 ? "text-[#22c55e]" : score >= 0.6 ? "text-[#facc15]" : "text-[#ef4444]"}`}>
        {(score * 100).toFixed(0)}
      </span>
      <div className="score-bar w-16">
        <div className="score-bar-fill" style={{ width: `${score * 100}%` }} />
      </div>
    </div>
  );
}

function StatCard({ label, value, accent = false }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className="border border-[#3f3f46] bg-[#18181b] p-4">
      <div className="text-[10px] text-[#52525b] uppercase tracking-widest mb-2">{label}</div>
      <div className={`text-2xl font-bold tabular-nums ${accent ? "text-[#22c55e] text-glow-green" : "text-[#e4e4e7]"}`}>
        {value}
      </div>
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

  return (
    <div className="pt-12 min-h-screen">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">

        <div className="flex items-center justify-between">
          <div>
            <div className="text-[10px] text-[#52525b] uppercase tracking-widest mb-1">// DASHBOARD</div>
            <h1 className="text-lg font-bold text-[#e4e4e7]">Top Matches</h1>
          </div>
          <button
            onClick={triggerRun}
            disabled={triggering || run?.status === "running" || run?.status === "pending"}
            className="flex items-center gap-2 px-4 py-2 text-xs border border-[#22c55e] text-[#22c55e] hover:bg-[#22c55e] hover:text-[#0a0a0a] transition-colors disabled:opacity-40 disabled:cursor-not-allowed uppercase tracking-wider"
          >
            <RefreshCw size={12} className={triggering ? "spin-slow" : ""} />
            {triggering ? "Queuing..." : "Refresh Jobs"}
          </button>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {loading ? (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          ) : (
            <>
              <StatCard label="Jobs Ranked" value={run?.job_count ?? jobs.length} accent />
              <StatCard label="Top Score" value={topScore != null ? `${(topScore * 100).toFixed(0)}%` : "—"} />
              <StatCard label="Last Run" value={lastRunTime ?? "Never"} />
            </>
          )}
        </div>

        {run && (run.status === "pending" || run.status === "running" || run.status === "done" || run.status === "failed") && (
          <RunProgress run={run} onComplete={handleRunComplete} />
        )}

        <div className="space-y-1">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] text-[#52525b] uppercase tracking-widest">// TOP 10</span>
          </div>

          {loading ? (
            <div className="space-y-1">
              {Array.from({ length: 5 }).map((_, i) => <JobCardSkeleton key={i} />)}
            </div>
          ) : jobs.length === 0 ? (
            <div className="border border-[#3f3f46] bg-[#18181b] p-8 text-center space-y-2">
              <div className="text-[#52525b] text-xs font-mono">
                <div>&gt; No signals detected.</div>
                <div>&gt; Run your first scan to rank jobs.</div>
                <div className="text-[#22c55e] cursor-blink mt-2">&gt; </div>
              </div>
            </div>
          ) : (
            <div className="space-y-px">
              {jobs.map((job, idx) => (
                <div key={job.id} className="job-row flex items-center gap-4 px-4 py-3 bg-[#18181b] border border-[#3f3f46]">
                  <span className="text-[10px] text-[#22c55e] w-4 tabular-nums shrink-0">{String(idx + 1).padStart(2, "0")}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-[#e4e4e7] truncate">{job.title}</div>
                    <div className="text-[11px] text-[#71717a] truncate">
                      {job.company}
                      {job.location ? ` · ${job.location}` : ""}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {job.company_tier && (
                      <span className="text-[9px] text-[#52525b] border border-[#3f3f46] px-1.5 py-0.5">
                        T{job.company_tier}
                      </span>
                    )}
                    {job.is_contract && (
                      <span className="text-[9px] text-[#facc15] border border-[#facc15]/30 px-1.5 py-0.5">
                        CONTRACT
                      </span>
                    )}
                    {job.final_score != null && <ScoreBar score={job.final_score} />}
                    <a
                      href={job.job_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[#52525b] hover:text-[#22c55e] transition-colors"
                    >
                      <ExternalLink size={12} />
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
