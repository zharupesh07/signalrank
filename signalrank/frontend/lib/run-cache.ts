import { getCached, setCache } from "@/lib/cache";
import type { Run } from "@/types";

type CachedRunListItem = {
  run_id: string;
  status: string;
  job_count: number | null;
  scrape_count: number | null;
  started_at: string | null;
  finished_at: string | null;
  progress: Run["progress"];
};

export function makeQueuedRun(runId: string): Run {
  return {
    id: runId,
    status: "pending",
    started_at: new Date().toISOString(),
    finished_at: null,
    job_count: null,
    scrape_count: null,
    progress: null,
  };
}

export function upsertRunCaches(run: Run): void {
  setCache("dash:run", run);

  const existing = getCached<CachedRunListItem[]>("runs:list") ?? [];
  const nextItem: CachedRunListItem = {
    run_id: run.id,
    status: run.status,
    job_count: run.job_count,
    scrape_count: run.scrape_count,
    started_at: run.started_at,
    finished_at: run.finished_at,
    progress: run.progress,
  };

  const nextList = [nextItem, ...existing.filter((item) => item.run_id !== run.id)];
  setCache("runs:list", nextList);
}
