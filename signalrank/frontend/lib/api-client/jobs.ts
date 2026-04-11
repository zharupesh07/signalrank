import type {
  Application,
  Job,
  JobsResponse,
  TrackerStats,
} from "@/types";

import { request } from "./core";

export type JobsListParams = {
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

export const jobsApi = {
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
  get: (token: string, id: string) => request<Job>(`/api/jobs/${id}`, { token }),
  analytics: (token: string) =>
    request<{
      score_distribution: { range: string; count: number }[];
      top_companies: { company: string; count: number }[];
      sites: { site: string; count: number }[];
      total: number;
    }>("/api/jobs/analytics", { token }),
  archiveUnsuitable: (token: string) =>
    request<{ queued: number; message?: string }>("/api/jobs/archive-unsuitable", {
      method: "POST",
      token,
    }),
  archiveStatus: (token: string) =>
    request<{ total: number; done: number; pending: number; running: number; failed: number }>(
      "/api/jobs/archive-status",
      { token }
    ),
};

export const applicationsApi = {
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
  patchRecruiter: (
    token: string,
    id: string,
    data: {
      recruiter_name?: string;
      recruiter_email?: string;
      recruiter_linkedin_url?: string;
    }
  ) =>
    request<{ recruiter_id: string }>(`/api/applications/${id}/recruiter`, {
      method: "PATCH",
      token,
      body: JSON.stringify(data),
    }),
  stats: (token: string) => request<TrackerStats>("/api/applications/stats", { token }),
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
};

export const recruitersApi = {
  list: (token: string, company?: string) =>
    request<{ id: string; company: string; name: string | null; email: string | null; linkedin_url: string | null; domain: string | null }[]>(
      `/api/recruiters${company ? `?company=${encodeURIComponent(company)}` : ""}`,
      { token }
    ),
  find: (token: string, data: { company: string; domain?: string; max_results?: number }) =>
    request<{
      found: number;
      inserted: number;
      skipped: number;
      recruiters: { name: string | null; email: string | null; linkedin_url: string; domain: string | null; confidence: string }[];
    }>("/api/recruiters/find", {
      method: "POST",
      token,
      body: JSON.stringify(data),
    }),
};

export const ingestApi = {
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
};
