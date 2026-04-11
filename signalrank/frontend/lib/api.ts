import { adminApi, devApi } from "@/lib/api-client/admin";
import { applicationsApi, ingestApi, jobsApi, recruitersApi } from "@/lib/api-client/jobs";
import { resumeApi } from "@/lib/api-client/resume";
import { runsApi } from "@/lib/api-client/runs";
import { authApi, onboardingApi, profileApi } from "@/lib/api-client/user";

export { type JobsListParams } from "@/lib/api-client/jobs";

export const api = {
  auth: authApi,
  profile: profileApi,
  jobs: jobsApi,
  runs: runsApi,
  applications: applicationsApi,
  recruiters: recruitersApi,
  resume: resumeApi,
  onboarding: onboardingApi,
  admin: adminApi,
  dev: devApi,
  ingest: ingestApi,
};
