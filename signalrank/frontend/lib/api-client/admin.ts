import { request } from "./core";

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

export const adminApi = {
  stats: (token: string) =>
    request<{ total_users: number; total_jobs: number; total_runs: number; total_applications: number }>(
      "/api/admin/stats",
      { token }
    ),
  users: (token: string) => request<AdminUsersResponse>("/api/admin/users", { token }),
  updateUser: (token: string, userId: string, data: { is_admin?: boolean }) =>
    request<{ status: string }>(`/api/admin/users/${userId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify(data),
    }),
  deleteUser: (token: string, userId: string) =>
    request<{ status: string }>(`/api/admin/users/${userId}`, {
      method: "DELETE",
      token,
    }),
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
    }>(`/api/admin/users/${userId}/reset-jobs`, {
      method: "POST",
      token,
    }),
  triggerRun: (token: string, userId: string, forceScrape = false) =>
    request<{ run_id: string; status: string; user_email: string }>(
      `/api/admin/users/${userId}/trigger-run`,
      { method: "POST", token, body: JSON.stringify({ force_scrape: forceScrape }) }
    ),
  forceRegenerateResumes: (token: string, userId: string) =>
    request<{ queued: number; user_id: string }>(
      `/api/admin/users/${userId}/force-regenerate-resumes`,
      { method: "POST", token }
    ),
  reparseResume: (token: string, userId: string) =>
    request<{ status: string; user_id: string }>(`/api/admin/users/${userId}/reparse-resume`, {
      method: "POST",
      token,
    }),
  reparseAllResumes: (token: string) =>
    request<{ queued: number }>("/api/admin/reparse-all-resumes", { method: "POST", token }),
  runs: (token: string) =>
    request<{
      run_id: string;
      user_email: string;
      status: string;
      job_count: number | null;
      scrape_count: number | null;
      run_kind?: string | null;
      scrape_reason?: string | null;
      started_at: string | null;
      finished_at: string | null;
    }[]>("/api/admin/runs", { token }),
  stopRun: (token: string, runId: string) =>
    request<{ stopped: boolean; status: string; message?: string }>(`/api/admin/runs/${runId}/stop`, {
      method: "POST",
      token,
    }),
  caches: (token: string) => request<CacheSummaryResponse>("/api/admin/caches", { token }),
  invalidateCache: (token: string, data: CacheInvalidateRequest) =>
    request<{ kind: string; deleted: number; clear_all: boolean }>("/api/admin/caches/invalidate", {
      method: "POST",
      token,
      body: JSON.stringify(data),
    }),
  topJobs: (token: string, userId: string) =>
    request<{
      job_id: string;
      title: string | null;
      company: string | null;
      location: string | null;
      final_score: number | null;
      semantic_score: number | null;
      skills_score: number | null;
      job_url: string;
    }[]>(`/api/admin/users/${userId}/top-jobs`, { token }),
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
};

export const devApi = {
  getDb: (token: string) =>
    request<{ target: string; railway_available: boolean; db_host: string }>("/api/dev/db", { token }),
  switchDb: (token: string, target: string) =>
    request<{ target: string; railway_available: boolean; db_host: string }>("/api/dev/db/switch", {
      method: "POST",
      token,
      body: JSON.stringify({ target }),
    }),
};
