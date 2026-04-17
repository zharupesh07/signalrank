import type {
  JobsResponse,
  Run,
  RunProgress,
} from "@/types";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const BACKEND_PROXY_PREFIX = "/api/backend";

export type ResumePreviewValidation = {
  page_count: number;
  warnings: string[];
  fit_actions: string[];
};

export type RunPayload = {
  id?: string;
  run_id: string;
  status: string;
  job_count: number | null;
  scrape_count: number | null;
  ranked_count?: number | null;
  visible_count?: number | null;
  started_at: string | null;
  finished_at: string | null;
  progress: RunProgress | null;
  run_kind?: string | null;
  scrape_reason?: string | null;
  jobs_snapshot?: JobsResponse | null;
  error: string | null;
};

function resolveBaseUrl() {
  if (typeof window !== "undefined") return BACKEND_PROXY_PREFIX;

  const origin =
    process.env.NEXTAUTH_URL ??
    process.env.AUTH_URL ??
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : null) ??
    "http://localhost:3000";

  return `${origin.replace(/\/+$/, "")}${BACKEND_PROXY_PREFIX}`;
}

function requestTimeoutMs() {
  const raw =
    (typeof window === "undefined"
      ? process.env.API_REQUEST_TIMEOUT_MS
      : process.env.NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS) ?? "";
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && parsed >= 1000) return parsed;
  return typeof window === "undefined" ? 30000 : 25000;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryDelayMs(res: Response, attempt: number) {
  const retryAfter = res.headers.get("Retry-After");
  const seconds = retryAfter ? Number(retryAfter) : NaN;
  if (Number.isFinite(seconds) && seconds >= 0) {
    return seconds * 1000;
  }
  return Math.min(500 * 2 ** attempt, 2000);
}

export function parseHeaderJson<T>(res: Response, name: string, fallback: T): T {
  const raw = res.headers.get(name);
  if (!raw) return fallback;
  try {
    return JSON.parse(decodeURIComponent(raw)) as T;
  } catch {
    return fallback;
  }
}

function userTimezoneHeader() {
  if (typeof window === "undefined") return {};
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return tz ? { "X-User-Timezone": tz } : {};
}

export async function request<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...init } = options;
  const baseUrl = resolveBaseUrl();
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };
  Object.assign(headers, userTimezoneHeader());
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const method = (init.method ?? "GET").toUpperCase();
  const shouldRetry = SAFE_METHODS.has(method);

  for (let attempt = 0; ; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), requestTimeoutMs());
    let res: Response;
    try {
      res = await fetch(`${baseUrl}${path}`, { ...init, headers, signal: controller.signal });
    } catch (error) {
      clearTimeout(timeout);
      if (error instanceof Error && error.name === "AbortError") {
        throw new Error(`Backend request timed out for ${path}`);
      }
      const message = error instanceof Error ? error.message : "Unknown network error";
      throw new Error(`Backend request failed for ${path}: ${message}`);
    }
    clearTimeout(timeout);

    if (res.ok) {
      if (res.status === 204) return undefined as T;
      return res.json();
    }

    if ((res.status === 503 || res.status === 429) && shouldRetry && attempt < 2) {
      await sleep(retryDelayMs(res, attempt));
      continue;
    }

    if (res.status === 401 && typeof window !== "undefined") {
      const { signOut } = await import("next-auth/react");
      signOut({ callbackUrl: "/login" });
    }
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
}

export function normalizeRun(payload: RunPayload): Run {
  const status = (payload.status === "success" || payload.status === "completed"
    ? "done"
    : payload.status) as Run["status"];
  return {
    id: payload.id ?? payload.run_id,
    status,
    job_count: payload.job_count,
    scrape_count: payload.scrape_count,
    ranked_count: payload.ranked_count ?? payload.progress?.jobs_found ?? null,
    visible_count: payload.visible_count ?? null,
    started_at: payload.started_at ?? "",
    finished_at: payload.finished_at,
    progress: payload.progress,
    run_kind: payload.run_kind ?? payload.progress?.run_kind ?? null,
    scrape_reason: payload.scrape_reason ?? payload.progress?.scrape_reason ?? null,
    jobs_snapshot: payload.jobs_snapshot,
    error: payload.error,
    executor_type: (payload as RunPayload & { executor_type?: string | null }).executor_type ?? null,
  };
}

export async function authorizedFetch(
  path: string,
  token: string,
  init: RequestInit = {}
) {
  return fetch(`${resolveBaseUrl()}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.headers as Record<string, string> | undefined),
    },
  });
}
