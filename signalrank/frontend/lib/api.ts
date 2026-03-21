import type {
  Application,
  Job,
  JobsResponse,
  OnboardingStatus,
  Profile,
  Run,
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
    list: (token: string, page = 1, limit = 50) =>
      request<JobsResponse>(`/api/jobs?page=${page}&limit=${limit}`, { token }),
    get: (token: string, id: string) =>
      request<Job>(`/api/jobs/${id}`, { token }),
  },

  runs: {
    trigger: (token: string) =>
      request<{ run_id: string; status: string }>("/api/runs/trigger", {
        method: "POST",
        token,
      }),
    latest: async (token: string): Promise<Run> => {
      const r = await request<{ run_id: string; status: string; job_count: number | null; started_at: string | null; finished_at: string | null }>("/api/runs/latest", { token });
      const status = r.status === "success" ? "done" : r.status as Run["status"];
      return { id: r.run_id, status, job_count: r.job_count, started_at: r.started_at ?? "", finished_at: r.finished_at };
    },
    status: async (token: string, runId: string): Promise<Run> => {
      const r = await request<{ run_id: string; status: string; job_count: number | null; started_at: string | null; finished_at: string | null }>(`/api/runs/${runId}/status`, { token });
      const status = r.status === "success" ? "done" : r.status as Run["status"];
      return { id: r.run_id, status, job_count: r.job_count, started_at: r.started_at ?? "", finished_at: r.finished_at };
    },
  },

  applications: {
    list: (token: string) =>
      request<Application[]>("/api/applications", { token }),
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
};
