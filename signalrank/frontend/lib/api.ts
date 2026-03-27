import type {
  Application,
  Job,
  JobsResponse,
  OnboardingStatus,
  Profile,
  Run,
  RunProgress,
  TrackerStats,
} from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...init } = options;
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
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
    patch: (token: string, data: Partial<Profile>) =>
      request<{ status: string }>("/api/profile", {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      }),
  },

  jobs: {
    list: (token: string, page = 1, limit = 50, search = "", showArchived = true) =>
      request<JobsResponse>(`/api/jobs?page=${page}&limit=${limit}&show_archived=${showArchived}${search ? `&search=${encodeURIComponent(search)}` : ""}`, { token }),
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
      request<{ run_id: string; status: string; job_count: number | null; scrape_count: number | null; started_at: string | null; finished_at: string | null; progress: RunProgress | null }[]>("/api/runs", { token }),
    trigger: (token: string) =>
      request<{ run_id: string; status: string }>("/api/runs/trigger", {
        method: "POST",
        token,
      }),
    stop: (token: string, runId: string) =>
      request<{ stopped: boolean; status: string; message?: string }>(`/api/runs/${runId}/stop`, {
        method: "POST",
        token,
      }),
    latest: async (token: string): Promise<Run> => {
      const r = await request<{ run_id: string; status: string; job_count: number | null; scrape_count: number | null; started_at: string | null; finished_at: string | null; progress: RunProgress | null }>("/api/runs/latest", { token });
      const status = r.status === "success" ? "done" : r.status as Run["status"];
      return { id: r.run_id, status, job_count: r.job_count, scrape_count: r.scrape_count, started_at: r.started_at ?? "", finished_at: r.finished_at, progress: r.progress };
    },
    status: async (token: string, runId: string): Promise<Run> => {
      const r = await request<{ run_id: string; status: string; job_count: number | null; scrape_count: number | null; started_at: string | null; finished_at: string | null; progress: RunProgress | null }>(`/api/runs/${runId}/status`, { token });
      const status = r.status === "success" ? "done" : r.status as Run["status"];
      return { id: r.run_id, status, job_count: r.job_count, scrape_count: r.scrape_count, started_at: r.started_at ?? "", finished_at: r.finished_at, progress: r.progress };
    },
  },

  applications: {
    list: (token: string) =>
      request<{ applications: Application[]; total: number }>("/api/applications", { token })
        .then((r) => r.applications),
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
    tailor: (token: string, data: { job_id: string; template?: string }) =>
      request<{ status: string; job_id: string; template: string; content: Record<string, unknown>; pdf_available: boolean }>(
        "/api/resume/tailor",
        { method: "POST", token, body: JSON.stringify(data) }
      ),
    download: async (token: string, jobId: string): Promise<"ok" | "pending"> => {
      const res = await fetch(`${BASE_URL}/api/resume/tailor/${jobId}`, {
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
    refine: (token: string, question_id: string, answer: string | string[]) =>
      request<{ status: string }>("/api/onboarding/refine", {
        method: "POST",
        token,
        body: JSON.stringify({ question_id, answer }),
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
