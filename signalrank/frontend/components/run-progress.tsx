"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { Check } from "lucide-react";
import { api } from "@/lib/api";
import { formatElapsed } from "@/lib/formatting";
import type { Run } from "@/types";
import { useToast } from "@/components/toast";

interface RunProgressProps {
  run: Run;
  onComplete?: (run: Run) => void;
}

export default function RunProgress({ run: initialRun, onComplete }: RunProgressProps) {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [runOverride, setRunOverride] = useState<Run | null>(null);
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completedRef = useRef(false);
  const onCompleteRef = useRef(onComplete);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  });

  useEffect(() => {
    completedRef.current = false;
  }, [initialRun.id]);

  const run = runOverride && runOverride.id === initialRun.id ? runOverride : initialRun;

  const isLiveStatus = (s: string) =>
    s === "pending" || s === "running" || s === "scraping" || s === "ranking";

  useEffect(() => {
    if (isLiveStatus(run.status)) {
      intervalRef.current = setInterval(() => setTick((t) => t + 1), 1000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [run.status]);

  useEffect(() => {
    if (!token || !run.id) return;
    if (run.id.startsWith("local-")) return;
    if (!isLiveStatus(run.status)) return;
    if (completedRef.current) return;

    let delay = 3000;
    const MAX_DELAY = 60000;

    function schedulePoll() {
      pollRef.current = setTimeout(async () => {
        try {
          const updated = await api.runs.status(token, run.id);
          setRunOverride(updated);
          if (updated.status === "done" && !completedRef.current) {
            completedRef.current = true;
            toast(`Run complete — ${updated.job_count ?? 0} jobs ranked`, "success");
            onCompleteRef.current?.({ ...updated, status: "done" });
            return;
          } else if (updated.status === "failed" && !completedRef.current) {
            completedRef.current = true;
            toast(updated.error ? `Run failed: ${updated.error}` : "Run failed", "error");
            return;
          } else if (updated.status === "cancelled" && !completedRef.current) {
            completedRef.current = true;
            return;
          }
        } catch {
          /* ignore transient errors */
        }
        const multiplier = document.hidden ? 2.0 : 1.5;
        delay = Math.min(delay * multiplier, MAX_DELAY);
        schedulePoll();
      }, document.hidden ? Math.max(delay, 15000) : delay);
    }

    schedulePoll();

    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [token, run.id, run.status, toast]);

  const isLive = isLiveStatus(run.status);
  const p = run.progress;

  const PHASES = [
    { key: "jobspy_indeed",   label: "Indeed" },
    { key: "jobspy_linkedin", label: "LinkedIn" },
    { key: "parallel",        label: "Other sources" },
    { key: "ranking",         label: "Ranking" },
  ];

  const activePhaseKey = p?.phase ?? (run.status === "ranking" ? "ranking" : null);
  const activeIdx = PHASES.findIndex((ph) => ph.key === activePhaseKey);

  const barPct =
    run.status === "done"      ? 100 :
    run.status === "failed"    ? 0 :
    run.status === "cancelled" ? 0 :
    p ? Math.round(((p.phase_num - 1) / (p.total_phases + 1)) * 100) :
    null;

  const statusLabel =
    run.status === "pending"   ? "Queued..." :
    run.status === "done"      ? "Complete" :
    run.status === "failed"    ? "Failed" :
    run.status === "cancelled" ? "Cancelled" :
    p?.message                 ? p.message :
    run.status === "scraping"  ? "Scraping..." :
    run.status === "ranking"   ? "Ranking jobs..." :
    "Running...";

  const jobsFound = p?.jobs_found ?? run.scrape_count ?? run.job_count;

  return (
    <div className="border border-border bg-card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {run.status === "done"      && <span className="w-2 h-2 rounded-full bg-primary inline-block" />}
          {run.status === "failed"    && <span className="w-2 h-2 rounded-full bg-destructive inline-block" />}
          {run.status === "cancelled" && <span className="w-2 h-2 rounded-full bg-[var(--terminal-yellow)] inline-block" />}
          {run.status === "pending"   && <span className="w-2 h-2 rounded-full bg-[var(--terminal-yellow)] pulse-dot inline-block" />}
          {isLive && run.status !== "pending" && <span className="w-2 h-2 rounded-full bg-primary pulse-dot-fast inline-block" />}
          <span className="text-xs text-muted-foreground uppercase tracking-wider">{statusLabel}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {jobsFound != null && (
            <span className="text-primary tabular-nums">{jobsFound.toLocaleString()} jobs</span>
          )}
          {isLive && run.started_at && <span key={tick}>{formatElapsed(run.started_at)}</span>}
          {!isLive && run.finished_at && run.started_at && <span>{formatElapsed(run.started_at)} total</span>}
        </div>
      </div>

      {/* Progress bar */}
      <div className="score-bar w-full">
        {isLive && barPct === null ? (
          <div className="progress-indeterminate h-0.5 bg-gradient-to-r from-transparent via-primary to-transparent" />
        ) : (
          <div
            className="score-bar-fill transition-all duration-700"
            style={{ width: `${barPct ?? (run.status === "done" ? 100 : 0)}%` }}
          />
        )}
      </div>

      {/* Phase steps — visible while running */}
      {isLive && (
        <div className="flex items-center text-[10px] flex-wrap gap-y-1">
          {PHASES.map((ph, i) => {
            const isDone   = activeIdx > i;
            const isActive = activeIdx === i;
            return (
              <div key={ph.key} className="flex items-center">
                <span className={
                  isDone   ? "text-primary" :
                  isActive ? "text-foreground" :
                             "text-muted-foreground/40"
                }>
                  {isActive && <span className="mr-0.5 text-primary animate-pulse">▶</span>}
                  {isDone   && <Check size={8} className="inline mr-0.5 text-primary" />}
                  {ph.label}
                </span>
                {i < PHASES.length - 1 && (
                  <span className="mx-1.5 text-border">›</span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center gap-4 text-[10px] text-muted-foreground flex-wrap">
        <span>RUN {run.id?.slice(0, 8).toUpperCase() ?? "--------"}</span>
        {run.started_at && <span>{new Date(run.started_at).toLocaleTimeString()}</span>}
        {run.status === "failed" && run.error && (
          <span className="text-destructive" title={run.error}>
            {run.error.length > 120 ? `${run.error.slice(0, 120)}…` : run.error}
          </span>
        )}
      </div>
    </div>
  );
}
