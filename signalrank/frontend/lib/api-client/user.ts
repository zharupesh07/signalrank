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

export const desktopApi = {
  status: () =>
    request<{
      mode: "desktop";
      provider_configured: boolean;
      provider: string | null;
      active_provider: string;
      providers: { id: string; name: string; configured: boolean; active: boolean }[];
      user_id: string;
      resume_uploaded: boolean;
      onboarding_complete: boolean;
    }>("/api/desktop/status"),
  session: () =>
    request<{ access_token: string; token_type: string }>("/api/desktop/session", {
      method: "POST",
    }),
  providers: () =>
    request<{
      active_provider: string;
      providers: { id: string; name: string; configured: boolean; active: boolean }[];
    }>("/api/desktop/providers"),
  saveProviderKey: (api_key: string, provider = "openrouter") =>
    request<{ status: string; provider: string; healthy_models: string[] }>(
      "/api/desktop/provider-key",
      {
        method: "POST",
        body: JSON.stringify({ provider, api_key }),
      }
    ),
  setProviderPreference: (active_provider: string) =>
    request<{ status: string; active_provider: string }>(
      "/api/desktop/provider-preferences",
      {
        method: "PATCH",
        body: JSON.stringify({ active_provider }),
      }
    ),
};
