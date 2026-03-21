export interface User {
  id: string;
  email: string;
}

export interface Profile {
  user_id: string;
  role_intent: string | null;
  min_salary: number | null;
  skills: string[];
  onboarding_complete: boolean;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  location: string | null;
  site: string | null;
  job_url: string;
  date_posted: string | null;
  description: string | null;
  final_score: number | null;
  semantic_score: number | null;
  skills_score: number | null;
  company_score: number | null;
  seniority_score: number | null;
  location_score: number | null;
  recency_score: number | null;
  company_tier: string | null;
  is_contract: boolean;
}

export interface JobsResponse {
  jobs: Job[];
  total: number;
  page: number;
  limit: number;
}

export type ApplicationStatus =
  | "interested"
  | "applied"
  | "phone_screen"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export interface Application {
  id: string;
  job_id: string | null;
  company: string;
  title: string;
  status: ApplicationStatus;
  applied_at: string | null;
  notes: string | null;
}

export interface Run {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  started_at: string;
  finished_at: string | null;
  job_count: number | null;
}

export interface OnboardingStatus {
  onboarding_complete: boolean;
  has_resume: boolean;
}
