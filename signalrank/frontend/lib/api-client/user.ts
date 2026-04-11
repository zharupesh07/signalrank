import type {
  OnboardingStatus,
  Profile,
  ProfileOptions,
} from "@/types";

import { request } from "./core";

export const authApi = {
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
};

export const profileApi = {
  get: (token: string) => request<Profile>("/api/profile", { token }),
  options: (token: string) => request<ProfileOptions>("/api/profile/options", { token }),
  patch: (token: string, data: Partial<Profile>) =>
    request<{ status: string }>("/api/profile", {
      method: "PATCH",
      token,
      body: JSON.stringify(data),
    }),
};

export const onboardingApi = {
  status: (token: string) => request<OnboardingStatus>("/api/onboarding/status", { token }),
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
};
