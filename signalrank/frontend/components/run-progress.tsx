"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Run } from "@/types";
import { useToast } from "@/components/toast";

interface RunProgressProps {
  run: Run;
  onComplete?: (run: Run) => void;
}

function elapsed(startedAt: string): string {
  const secs = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

export default function RunProgress({ run: initialRun, onComplete }: RunProgressProps) {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [run, setRun] = useState(initialRun);
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    setRun(initialRun);
    completedRef.current = false;
  }, [initialRun.id]);

  useEffect(() => {
    if (run.status === "pending" || run.status === "running") {
      intervalRef.current = setInterval(() => setTick((t) => t + 1), 1000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [run.status]);

  useEffect(() => {
    if (!token || !run.id) return;
    if (run.status !== "pending" && run.status !== "running") return;
    if (completedRef.current) return;

    pollRef.current = setInterval(async () => {
      try {
        const updated = await api.runs.status(token, run.id);
        setRun(updated);
        const finished = updated.status === "done";
        if (finished && !completedRef.current) {
          completedRef.current = true;
          toast(`Run complete — ${updated.job_count ?? 0} jobs ranked`, "success");
          onComplete?.({ ...updated, status: "done" });
          clearInterval(pollRef.current!);
        } else if (updated.status === "failed" && !completedRef.current) {
          completedRef.current = true;
          toast("Run failed", "error");
          clearInterval(pollRef.current!);
        }
      } catch {
        /* ignore transient errors */
      }
    }, 2000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [token, run.id, run.status, onComplete, toast]);

  const isLive = run.status === "pending" || run.status === "running";

  return (
    <div className="border border-[#3f3f46] bg-[#18181b] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {run.status === "done" && (
            <span className="w-2 h-2 rounded-full bg-[#22c55e] inline-block" />
          )}
          {run.status === "failed" && (
            <span className="w-2 h-2 rounded-full bg-[#ef4444] inline-block" />
          )}
          {run.status === "pending" && (
            <span className="w-2 h-2 rounded-full bg-[#facc15] pulse-dot inline-block" />
          )}
          {run.status === "running" && (
            <span className="w-2 h-2 rounded-full bg-[#22c55e] pulse-dot-fast inline-block" />
          )}
          <span className="text-xs text-[#71717a] uppercase tracking-wider">
            {run.status === "pending" && "Queued..."}
            {run.status === "running" && "Scoring jobs..."}
            {run.status === "done" && "Complete"}
            {run.status === "failed" && "Failed"}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs text-[#52525b]">
          {run.job_count != null && (
            <span className="text-[#22c55e]">{run.job_count} jobs</span>
          )}
          {isLive && run.started_at && (
            <span key={tick}>{elapsed(run.started_at)}</span>
          )}
          {!isLive && run.finished_at && run.started_at && (
            <span>
              {elapsed(run.started_at)} total
            </span>
          )}
        </div>
      </div>

      <div className="score-bar w-full">
        {isLive ? (
          <div className="progress-indeterminate h-0.5 bg-gradient-to-r from-transparent via-[#22c55e] to-transparent" />
        ) : (
          <div
            className="score-bar-fill"
            style={{ width: run.status === "done" ? "100%" : "0%" }}
          />
        )}
      </div>

      <div className="flex items-center gap-4 text-[10px] text-[#52525b]">
        <span>RUN {run.id?.slice(0, 8).toUpperCase() ?? "--------"}</span>
        {run.started_at && (
          <span>{new Date(run.started_at).toLocaleTimeString()}</span>
        )}
      </div>
    </div>
  );
}
