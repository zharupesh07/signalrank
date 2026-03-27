"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
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
};

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

  const LIVE = ["pending", "running", "scraping", "ranking"];

  async function refreshList() {
    const r = await api.runs.list(token);
    setRuns(r);
  }

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api.runs.list(token),
      api.runs.latest(token).catch(() => null),
    ]).then(([list, latest]) => {
      setRuns(list);
      if (latest && LIVE.includes(latest.status)) setActiveRun(latest);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [token]);

  async function triggerRun() {
    setTriggering(true);
    try {
      const res = await api.runs.trigger(token);
      const newRun: Run = {
        id: res.run_id,
        status: "pending",
        started_at: new Date().toISOString(),
        finished_at: null,
        job_count: null,
        scrape_count: null,
        progress: null,
      };
      setActiveRun(newRun);
      toast("Run queued", "info");
      await refreshList();
    } catch {
      toast("Failed to trigger run", "error");
    } finally {
      setTriggering(false);
    }
  }

  async function handleRunComplete(completed: Run) {
    setActiveRun(completed);
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
          <button
            onClick={triggerRun}
            disabled={triggering || (activeRun != null && LIVE.includes(activeRun.status))}
            className="flex items-center gap-2 text-[11px] text-primary border border-primary/40 px-3 py-1.5 hover:bg-primary/10 transition-colors uppercase tracking-wider disabled:opacity-50"
          >
            <Play size={10} />
            {triggering ? "Triggering..." : activeRun && LIVE.includes(activeRun.status) ? "Running..." : "New Run"}
          </button>
        </div>

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
                      <div className="mt-2 text-muted-foreground">trigger a run from the dashboard</div>
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
                        <StatusBadge status={run.status} />
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
