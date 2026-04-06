"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { swr } from "@/lib/cache";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import { CheckCircle, XCircle, Play, Square } from "lucide-react";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import type { Run } from "@/types";

type RunRecord = {
  run_id: string;
  status: string;
  job_count: number | null;
  scrape_count: number | null;
  started_at: string | null;
  finished_at: string | null;
  error?: string | null;
  trigger_source?: string | null;
  executor_type?: string | null;
};

const LIVE = ["pending", "claimed", "running", "scraping", "ranking"];

function StatusBadge({ status }: { status: string }) {
  if (status === "success" || status === "done") {
    return (
      <div className="flex items-center gap-1.5 text-primary">
        <CheckCircle size={11} />
        <span className="text-xs uppercase tracking-wider">done</span>
      </div>
    );
  }
  if (status === "failed" || status === "error") {
    return (
      <div className="flex items-center gap-1.5 text-destructive">
        <XCircle size={11} />
        <span className="text-xs uppercase tracking-wider">failed</span>
      </div>
    );
  }
  if (status === "running") {
    return (
      <div className="flex items-center gap-1.5 text-primary">
        <span className="pulse-dot-fast" />
        <span className="text-xs uppercase tracking-wider">running</span>
      </div>
    );
  }
  if (status === "cancelled") {
    return (
      <div className="flex items-center gap-1.5 text-[var(--terminal-yellow)]">
        <span className="pulse-dot" />
        <span className="text-xs uppercase tracking-wider">cancelled</span>
      </div>
    );
  }
  if (status === "claimed") {
    return (
      <div className="flex items-center gap-1.5 text-[var(--terminal-cyan)]">
        <span className="pulse-dot" />
        <span className="text-xs uppercase tracking-wider">claimed</span>
      </div>
    );
  }
  if (status === "timed_out" || status === "stale") {
    return (
      <div className="flex items-center gap-1.5 text-[var(--terminal-yellow)]">
        <XCircle size={11} />
        <span className="text-xs uppercase tracking-wider">timed out</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 text-[var(--terminal-yellow)]">
      <span className="pulse-dot" />
      <span className="text-xs uppercase tracking-wider">pending</span>
    </div>
  );
}

function formatDate(s: string | null) {
  if (!s) return "—";
  const d = new Date(s);
  return d.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function duration(start: string | null, end: string | null) {
  if (!start || !end) return null;
  const secs = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (secs < 60) return `${secs}s`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${s}s`;
}

export default function RunsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";

  const { toast } = useToast();
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [stoppingRunId, setStoppingRunId] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<Run | null>(null);

  async function refreshList() {
    const r = await api.runs.list(token);
    setRuns(r);
  }

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    Promise.all([
      swr("runs:list", () => api.runs.list(token), setRuns),
      api.runs.latest(token).then((latest) => {
        if (latest && LIVE.includes(latest.status)) setActiveRun(latest);
      }).catch(() => null),
    ]).finally(() => setLoading(false));
  }, [token]);

  async function triggerRun() {
    setTriggering(true);
    const optimisticRun = makeQueuedRun(`local-${Date.now()}`);
    setActiveRun(optimisticRun);
    setRuns((prev) => [
      {
        run_id: optimisticRun.id,
        status: optimisticRun.status,
        job_count: optimisticRun.job_count,
        scrape_count: optimisticRun.scrape_count,
        started_at: optimisticRun.started_at,
        finished_at: optimisticRun.finished_at,
        progress: optimisticRun.progress,
        error: optimisticRun.error,
      },
      ...prev.filter((run) => run.run_id !== optimisticRun.id),
    ]);
    try {
      const res = await api.runs.trigger(token);
      const newRun = makeQueuedRun(res.run_id);
      setActiveRun(newRun);
      setRuns((prev) => [
        {
          run_id: newRun.id,
          status: newRun.status,
          job_count: newRun.job_count,
          scrape_count: newRun.scrape_count,
          started_at: newRun.started_at,
          finished_at: newRun.finished_at,
          error: newRun.error,
        },
        ...prev.filter((run) => run.run_id !== newRun.id),
      ]);
      upsertRunCaches(newRun);
      toast("Run queued", "info");
    } catch {
      setActiveRun((current) => (current?.id === optimisticRun.id ? null : current));
      setRuns((prev) => prev.filter((run) => run.run_id !== optimisticRun.id));
      toast("Failed to trigger run", "error");
    } finally {
      setTriggering(false);
    }
  }

  async function handleRunComplete(completed: Run) {
    setActiveRun(completed);
    upsertRunCaches(completed);
    await refreshList();
  }

  async function stopRun(runId: string) {
    setStoppingRunId(runId);
    try {
      const result = await api.runs.stop(token, runId);
      if (result.stopped) {
        toast("Run stopping...", "success");
        // Refresh the list immediately to show updated status
        const r = await api.runs.list(token);
        setRuns(r);
        if (activeRun?.id === runId) {
          const cancelledRun: Run = { ...activeRun, status: "cancelled" };
          setActiveRun(cancelledRun);
          upsertRunCaches(cancelledRun);
        }
      } else {
        toast(`Failed to stop run: ${result.message}`, "error");
      }
    } catch {
      toast("Failed to stop run", "error");
    } finally {
      setStoppingRunId(null);
    }
  }

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-5">
        <div className="flex items-end justify-between">
          <div>
            <div className="section-label mb-1">run history</div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-bold text-foreground">Runs</h1>
              {!loading && (
                <span className="text-primary text-sm tabular-nums text-glow-dim">{runs.length}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={triggerRun}
              disabled={triggering || (activeRun != null && LIVE.includes(activeRun.status))}
              className="flex items-center gap-2 text-[11px] text-primary border border-primary/40 px-3 py-1.5 hover:bg-primary/10 transition-colors uppercase tracking-wider disabled:opacity-50"
            >
              <Play size={10} />
              {triggering ? "Triggering..." : activeRun && LIVE.includes(activeRun.status) ? "Running..." : "Quick Run"}
            </button>
            <button
              className="terminal-btn text-xs px-3 py-1.5"
              onClick={async () => {
                try {
                  await api.runs.trigger(token, "quick", true);
                  toast("Rank-only run started", "success");
                } catch {
                  toast("Failed to start rank-only run", "error");
                }
              }}
              title="Re-rank existing jobs without scraping"
            >
              <Play size={11} className="inline mr-1" />
              Rank only
            </button>
          </div>
        </div>
        {(() => {
          const pendingRuns = runs.filter((r) => r.status === "pending");
          if (pendingRuns.length === 0) return null;
          const oldestPending = pendingRuns[pendingRuns.length - 1];
          const waitSecs = oldestPending.started_at
            ? Math.floor((Date.now() - new Date(oldestPending.started_at).getTime()) / 1000)
            : 0;
          if (waitSecs < 60) return null;
          return (
            <div className="text-xs text-[var(--terminal-yellow)] mt-2 opacity-70">
              Run has been pending for {waitSecs}s — is a worker running?
            </div>
          );
        })()}

        {activeRun && <RunProgress run={activeRun} onComplete={handleRunComplete} />}

        <div className="border border-border overflow-hidden">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-border bg-card">
                {["Run ID", "Status", "Scraped", "Ranked", "Started", "Duration", "Actions"].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs text-muted-foreground uppercase tracking-[0.15em]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-muted">
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="skeleton h-3 rounded" style={{ width: ["120px", "60px", "40px", "40px", "140px", "60px"][j] }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center">
                    <div className="font-mono text-muted-foreground text-xs space-y-1">
                      <div>┌─────────────────────┐</div>
                      <div>│   no runs found     │</div>
                      <div>└─────────────────────┘</div>
                      <div className="mt-2 text-muted-foreground">trigger a quick run from the dashboard or a deep scan from settings</div>
                    </div>
                  </td>
                </tr>
              ) : (
                runs.map((run, idx) => {
                  const dur = duration(run.started_at, run.finished_at);
                  const canCancel = ["pending", "scraping", "ranking"].includes(run.status);
                  const isStopping = stoppingRunId === run.run_id;
                  return (
                    <tr
                      key={run.run_id}
                      className="job-row border-b border-muted bg-card animate-in"
                      style={{ animationDelay: `${idx * 30}ms` }}
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-muted-foreground text-xs">{run.run_id.slice(0, 8)}…</span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="space-y-1">
                          <StatusBadge status={run.status} />
                          {run.status === "failed" && run.error && (
                            <div className="text-[10px] text-destructive max-w-56 truncate" title={run.error}>
                              {run.error}
                            </div>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-muted-foreground tabular-nums">{run.scrape_count ?? "—"}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-secondary-foreground tabular-nums">{run.job_count ?? "—"}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-muted-foreground tabular-nums">{formatDate(run.started_at)}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-muted-foreground tabular-nums">{dur ?? "—"}</span>
                      </td>
                      <td className="px-4 py-3">
                        {canCancel && (
                          <button
                            onClick={() => stopRun(run.run_id)}
                            disabled={isStopping}
                            className="flex items-center gap-1.5 text-[10px] text-destructive border border-destructive/40 px-2 py-1 hover:bg-destructive/10 transition-colors uppercase tracking-wider disabled:opacity-50"
                            title="Stop run"
                          >
                            <Square size={10} fill="current" />
                            {isStopping ? "Stopping…" : "Stop"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
