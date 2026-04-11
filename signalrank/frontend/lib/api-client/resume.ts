import { authorizedFetch, parseHeaderJson, request, type ResumePreviewValidation } from "./core";

export const resumeApi = {
  templates: (token: string) =>
    request<{ templates: string[] }>("/api/resume/templates", { token }),
  preview: async (
    token: string,
    data: {
      template?: string;
      resume_editor?: unknown;
    }
  ): Promise<ResumePreviewValidation> => {
    const res = await authorizedFetch("/api/resume/preview", token, {
      method: "POST",
      headers: {
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
    const res = await authorizedFetch(`/api/resume/tailor/${jobId}`, token);
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
};
