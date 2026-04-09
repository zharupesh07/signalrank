import type {
  Application,
  Job,
  JobsResponse,
  OnboardingStatus,
  ProfileOptions,
  Profile,
  Run,
  RunProgress,
  TrackerStats,
} from "@/types";

type JobsListParams = {
  page?: number;
  limit?: number;
  sort?: "final_score" | "semantic_score" | "skills_score" | "company_score" | "seniority_score" | "location_score" | "recency_score" | "date_posted";
  sortDir?: "asc" | "desc";
  search?: string;
  showArchived?: boolean;
  minScore?: number;
  tiers?: string[];
  jobType?: "all" | "fte" | "contract";
  sites?: string[];
  dateRange?: "any" | "24h" | "week" | "month";
};

type AdminUser = {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
  last_login: string | null;
  onboarding_complete: boolean;
  run_count: number;
  last_run_status: string | null;
};

type AdminUsersResponse = {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
};

type AdminUserProfileConfig = {
  user_id: string;
  email: string;
  onboarding_complete: boolean;
  target_roles: string[];
  preferred_locations: string[];
  custom_search_queries: string[];
  target_lpa: number | null;
  min_yoe: number | null;
  max_yoe: number | null;
  scraper_hours_old: number | null;
  scraper_max_terms: number | null;
  resume_template: string | null;
  config_overrides: Record<string, unknown> | null;
  title_penalty_rules: {
    strong: string[];
    adjacent: string[];
    hybrid: string[];
  };
};

type CacheSummaryResponse = {
  scrape_query_cache_count: number;
  query_plan_cache_count: number;
  sample_scrape_query_keys: {
    provider: string;
    site: string;
    term: string;
    location: string;
    country: string;
    hours_old: number;
    result_count: number;
    fresh_until: string | null;
  }[];
  sample_query_plan_keys: {
    profile_fingerprint: string;
    search_window_days: number;
    source_filter: string;
    query_version: string;
    max_terms: number;
    created_at: string | null;
  }[];
};

type CacheInvalidateRequest = {
  kind: "scrape_query_cache" | "query_plan_cache";
  clear_all?: boolean;
  provider?: string;
  site?: string;
  term?: string;
  location?: string;
  country?: string;
  hours_old?: number;
  profile_fingerprint?: string;
  search_window_days?: number;
  source_filter?: string;
  query_version?: string;
};

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const BACKEND_PROXY_PREFIX = "/api/backend";

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

type ResumePreviewValidation = {
  page_count: number;
  warnings: string[];
  fit_actions: string[];
};

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

function parseHeaderJson<T>(res: Response, name: string, fallback: T): T {
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

async function request<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...init } = options;
  const baseUrl = resolveBaseUrl();
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };
  Object.assign(headers, userTimezoneHeader());
  if (token) headers["Authorization"] = `Bearer ${token}`;
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

export const api = {
  auth: {
    register: (email: string, password: string) =>
      request<{ id: string; email: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    login: (email: string, password: string) =>
      request<{ access_token: string; token_type: string }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
  },

  profile: {
    get: (token: string) =>
      request<Profile>("/api/profile", { token }),
    options: (token: string) =>
      request<ProfileOptions>("/api/profile/options", { token }),
    patch: (token: string, data: Partial<Profile>) =>
      request<{ status: string }>("/api/profile", {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      }),
  },

  jobs: {
    list: (token: string, params: JobsListParams = {}) => {
      const {
        page = 1,
        limit = 50,
        sort = "final_score",
        sortDir = "desc",
        search = "",
        showArchived = true,
        minScore = 0,
        tiers = [],
        jobType = "all",
        sites = [],
        dateRange = "any",
      } = params;
      const qs = new URLSearchParams({
        page: String(page),
        limit: String(limit),
        sort,
        sort_dir: sortDir,
        show_archived: String(showArchived),
        min_score: String(minScore),
        job_type: jobType,
        date_range: dateRange,
      });
      if (search) qs.set("search", search);
      for (const tier of tiers) qs.append("tiers", tier);
      for (const site of sites) qs.append("sites", site);
      return request<JobsResponse>(`/api/jobs?${qs.toString()}`, { token });
    },
    get: (token: string, id: string) =>
      request<Job>(`/api/jobs/${id}`, { token }),
    analytics: (token: string) =>
      request<{
        score_distribution: { range: string; count: number }[];
        top_companies: { company: string; count: number }[];
        sites: { site: string; count: number }[];
        total: number;
      }>("/api/jobs/analytics", { token }),
    archiveUnsuitable: (token: string) =>
      request<{ queued: number; message?: string }>("/api/jobs/archive-unsuitable", { method: "POST", token }),
    archiveStatus: (token: string) =>
      request<{ total: number; done: number; pending: number; running: number; failed: number }>("/api/jobs/archive-status", { token }),
  },

  runs: {
    list: (token: string) =>
      request<{ run_id: string; status: string; job_count: number | null; scrape_count: number | null; started_at: string | null; finished_at: string | null; progress: RunProgress | null; run_kind?: string | null; scrape_reason?: string | null; jobs_snapshot?: JobsResponse | null; error: string | null }[]>("/api/runs", { token }),
    trigger: (
      token: string,
      mode: "quick" | "full" = "quick",
      disableScraping = false,
      executorType?: "local" | "cloud",
    ) =>
      request<{ run_id: string; status: string }>("/api/runs/trigger", {
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
    latest: async (token: string): Promise<Run> => {
      const r = await request<{ run_id: string; status: string; job_count: number | null; scrape_count: number | null; started_at: string | null; finished_at: string | null; progress: RunProgress | null; run_kind?: string | null; scrape_reason?: string | null; jobs_snapshot?: JobsResponse | null; error: string | null }>("/api/runs/latest", { token });
      const status = r.status === "success" ? "done" : r.status as Run["status"];
      return { id: r.run_id, status, job_count: r.job_count, scrape_count: r.scrape_count, started_at: r.started_at ?? "", finished_at: r.finished_at, progress: r.progress, run_kind: r.run_kind ?? r.progress?.run_kind ?? null, scrape_reason: r.scrape_reason ?? r.progress?.scrape_reason ?? null, jobs_snapshot: r.jobs_snapshot, error: r.error };
    },
    status: async (token: string, runId: string): Promise<Run> => {
      const r = await request<{ run_id: string; status: string; job_count: number | null; scrape_count: number | null; started_at: string | null; finished_at: string | null; progress: RunProgress | null; run_kind?: string | null; scrape_reason?: string | null; jobs_snapshot?: JobsResponse | null; error: string | null }>(`/api/runs/${runId}/status`, { token });
      const status = r.status === "success" ? "done" : r.status as Run["status"];
      return { id: r.run_id, status, job_count: r.job_count, scrape_count: r.scrape_count, started_at: r.started_at ?? "", finished_at: r.finished_at, progress: r.progress, run_kind: r.run_kind ?? r.progress?.run_kind ?? null, scrape_reason: r.scrape_reason ?? r.progress?.scrape_reason ?? null, jobs_snapshot: r.jobs_snapshot, error: r.error };
    },
  },

  applications: {
    list: (token: string) =>
      request<{ applications: Application[]; total: number }>("/api/applications?limit=200", { token })
        .then((r) => r.applications),
    trackedJobIds: (token: string) =>
      request<{ job_ids: string[] }>("/api/applications/tracked-job-ids", { token })
        .then((r) => r.job_ids),
    create: (token: string, data: Partial<Application>) =>
      request<Application>("/api/applications", {
        method: "POST",
        token,
        body: JSON.stringify(data),
      }),
    update: (token: string, id: string, data: Partial<Application>) =>
      request<Application>(`/api/applications/${id}`, {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      }),
    delete: (token: string, id: string) =>
      request<void>(`/api/applications/${id}`, {
        method: "DELETE",
        token,
      }),
    patchRecruiter: (token: string, id: string, data: { recruiter_name?: string; recruiter_email?: string; recruiter_linkedin_url?: string }) =>
      request<{ recruiter_id: string }>(`/api/applications/${id}/recruiter`, {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      }),
    stats: (token: string) =>
      request<TrackerStats>("/api/applications/stats", { token }),
    importFromRun: (token: string, data: { run_id: string; min_score?: number; limit?: number }) =>
      request<{ created: number; skipped: number }>("/api/applications/import-from-run", {
        method: "POST",
        token,
        body: JSON.stringify(data),
      }),
    recruitersByCompany: (token: string, company: string) =>
      request<{ id: string; name: string | null; email: string; linkedin_url: string | null }[]>(
        `/api/applications/recruiters?company=${encodeURIComponent(company)}`,
        { token }
      ),
  },

  recruiters: {
    list: (token: string, company?: string) =>
      request<{ id: string; company: string; name: string | null; email: string | null; linkedin_url: string | null; domain: string | null }[]>(
        `/api/recruiters${company ? `?company=${encodeURIComponent(company)}` : ""}`,
        { token }
      ),
    find: (token: string, data: { company: string; domain?: string; max_results?: number }) =>
      request<{ found: number; inserted: number; skipped: number; recruiters: { name: string | null; email: string | null; linkedin_url: string; domain: string | null; confidence: string }[] }>(
        "/api/recruiters/find",
        { method: "POST", token, body: JSON.stringify(data) }
      ),
  },

  resume: {
    templates: (token: string) =>
      request<{ templates: string[] }>("/api/resume/templates", { token }),
    preview: async (
      token: string,
      data: {
        template?: string;
        resume_editor?: unknown;
      }
    ): Promise<ResumePreviewValidation> => {
      const res = await fetch(`${resolveBaseUrl()}/api/resume/preview`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      const validation = parseHeaderJson<ResumePreviewValidation>(res, "X-Resume-Validation", {
        page_count: 1,
        warnings: [],
        fit_actions: [],
      });
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
      return validation;
    },
    tailor: (token: string, data: { job_id: string; template?: string }) =>
      request<{ status: string; job_id: string; template: string; content: Record<string, unknown>; pdf_available: boolean }>(
        "/api/resume/tailor",
        { method: "POST", token, body: JSON.stringify(data) }
      ),
    download: async (token: string, jobId: string): Promise<"ok" | "pending"> => {
      const res = await fetch(`${resolveBaseUrl()}/api/resume/tailor/${jobId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 202) return "pending";
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="(.+?)"/);
      a.download = match ? match[1] : `resume_${jobId.slice(0, 8)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      return "ok";
    },
    email: (token: string, data: { job_id: string; recruiter_name: string }) =>
      request<{ subject: string; body: string }>(
        "/api/resume/email",
        { method: "POST", token, body: JSON.stringify(data) }
      ),
  },

  onboarding: {
    status: (token: string) =>
      request<OnboardingStatus>("/api/onboarding/status", { token }),
    uploadResume: (token: string, file: File) => {
      const form = new FormData();
      form.append("file", file);
      return request<{ extracted: object; questions: object[] }>(
        "/api/onboarding/resume",
        { method: "POST", token, body: form }
      );
    },
    parsed: (token: string) =>
      request<{
        parsing: boolean;
        prefill: {
          target_roles: string[];
          preferred_locations: string[];
          exclusions: string[];
          salary_lpa: number | null;
          min_yoe: number | null;
          max_yoe: number | null;
          role_intent: string | null;
        };
      }>("/api/onboarding/parsed", { token }),
    refine: (token: string, question_id: string, answer: string | string[]) =>
      request<{ status: string }>("/api/onboarding/refine", {
        method: "POST",
        token,
        body: JSON.stringify({ question_id, answer }),
      }),
  },

  admin: {
    stats: (token: string) =>
      request<{ total_users: number; total_jobs: number; total_runs: number; total_applications: number }>("/api/admin/stats", { token }),
    users: (token: string) =>
      request<AdminUsersResponse>("/api/admin/users", { token }),
    updateUser: (token: string, userId: string, data: { is_admin?: boolean }) =>
      request<{ status: string }>(`/api/admin/users/${userId}`, { method: "PATCH", token, body: JSON.stringify(data) }),
    deleteUser: (token: string, userId: string) =>
      request<{ status: string }>(`/api/admin/users/${userId}`, { method: "DELETE", token }),
    resetJobs: (token: string, userId: string) =>
      request<{
        status: string;
        user_email: string;
        runs_deleted: number;
        job_results_deleted: number;
        generation_queue_deleted: number;
        tailored_resumes_deleted: number;
        archival_queue_deleted: number;
        jobs_preserved: boolean;
      }>(`/api/admin/users/${userId}/reset-jobs`, { method: "POST", token }),
    triggerRun: (token: string, userId: string, forceScrape = false) =>
      request<{ run_id: string; status: string; user_email: string }>(`/api/admin/users/${userId}/trigger-run`, { method: "POST", token, body: JSON.stringify({ force_scrape: forceScrape }) }),
    forceRegenerateResumes: (token: string, userId: string) =>
      request<{ queued: number; user_id: string }>(`/api/admin/users/${userId}/force-regenerate-resumes`, { method: "POST", token }),
    reparseResume: (token: string, userId: string) =>
      request<{ status: string; user_id: string }>(`/api/admin/users/${userId}/reparse-resume`, { method: "POST", token }),
    reparseAllResumes: (token: string) =>
      request<{ queued: number }>("/api/admin/reparse-all-resumes", { method: "POST", token }),
    runs: (token: string) =>
      request<{ run_id: string; user_email: string; status: string; job_count: number | null; scrape_count: number | null; run_kind?: string | null; scrape_reason?: string | null; started_at: string | null; finished_at: string | null }[]>("/api/admin/runs", { token }),
    stopRun: (token: string, runId: string) =>
      request<{ stopped: boolean; status: string; message?: string }>(`/api/admin/runs/${runId}/stop`, { method: "POST", token }),
    caches: (token: string) =>
      request<CacheSummaryResponse>("/api/admin/caches", { token }),
    invalidateCache: (token: string, data: CacheInvalidateRequest) =>
      request<{ kind: string; deleted: number; clear_all: boolean }>("/api/admin/caches/invalidate", {
        method: "POST",
        token,
        body: JSON.stringify(data),
      }),
    topJobs: (token: string, userId: string) =>
      request<{ job_id: string; title: string | null; company: string | null; location: string | null; final_score: number | null; semantic_score: number | null; skills_score: number | null; job_url: string }[]>(`/api/admin/users/${userId}/top-jobs`, { token }),
    profileConfig: (token: string, userId: string) =>
      request<AdminUserProfileConfig>(`/api/admin/users/${userId}/profile-config`, { token }),
    updateProfileConfig: (
      token: string,
      userId: string,
      data: {
        onboarding_complete?: boolean;
        target_roles?: string[];
        preferred_locations?: string[];
        custom_search_queries?: string[];
        target_lpa?: number | null;
        min_yoe?: number | null;
        max_yoe?: number | null;
        scraper_hours_old?: number | null;
        scraper_max_terms?: number | null;
        resume_template?: string | null;
        config_overrides?: Record<string, unknown> | null;
      }
    ) =>
      request<{ status: string }>(`/api/admin/users/${userId}/profile-config`, {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      }),
  },

  dev: {
    getDb: (token: string) =>
      request<{ target: string; railway_available: boolean; db_host: string }>("/api/dev/db", { token }),
    switchDb: (token: string, target: string) =>
      request<{ target: string; railway_available: boolean; db_host: string }>("/api/dev/db/switch", {
        method: "POST",
        token,
        body: JSON.stringify({ target }),
      }),
  },

  ingest: {
    extract: (token: string, payload: { url?: string; text?: string }) =>
      request<{
        title: string;
        company: string;
        location: string;
        job_url: string;
        date_posted: string | null;
        description: string;
      }>("/api/jobs/ingest", {
        method: "POST",
        token,
        body: JSON.stringify(payload),
      }),

    confirm: (
      token: string,
      payload: {
        title: string;
        company: string;
        location: string;
        job_url: string;
        date_posted: string | null;
        description: string;
      }
    ) =>
      request<
        | { application_id: string; priority: string }
        | { error: string; application_id?: string }
      >("/api/jobs/ingest/confirm", {
        method: "POST",
        token,
        body: JSON.stringify(payload),
      }),
  },
};
