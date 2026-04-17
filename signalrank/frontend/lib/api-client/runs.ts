import type { Run } from "@/types";

import { normalizeRun, request, type RunPayload } from "./core";

export const runsApi = {
  list: async (token: string): Promise<Run[]> =>
    (await request<RunPayload[]>("/api/runs", { token })).map(normalizeRun),
  trigger: (
    token: string,
    mode: "quick" | "full" = "quick",
    disableScraping = false,
    executorType?: "local" | "cloud",
  ) =>
    request<{ id?: string; run_id: string; status: string }>("/api/runs/trigger", {
      method: "POST",
      token,
      body: JSON.stringify({
        mode,
        disable_scraping: disableScraping,
        ...(executorType ? { executor_type: executorType } : {}),
      }),
    }),
  stop: (token: string, runId: string) =>
    request<{ stopped: boolean; status: string; message?: string }>(`/api/runs/${runId}/stop`, {
      method: "POST",
      token,
    }),
  latest: async (token: string): Promise<Run> =>
    normalizeRun(await request<RunPayload>("/api/runs/latest", { token })),
  status: async (token: string, runId: string): Promise<Run> =>
    normalizeRun(await request<RunPayload>(`/api/runs/${runId}/status`, { token })),
};
