export interface User {
  id: string;
  email: string;
}

export interface Profile {
  user_id: string;
  email: string;
  role_intent: string | null;
  min_salary: number | null;
  min_yoe: number | null;
  max_yoe: number | null;
  target_lpa: number | null;
  skills: string[];
  target_roles: string[] | null;
  preferred_locations: string[] | null;
  custom_search_queries: string[] | null;
  config_overrides: Record<string, unknown> | null;
  scraper_hours_old: number | null;
  scraper_max_terms: number | null;
  onboarding_complete: boolean;
}

export interface ProfileOptions {
  role_options: string[];
  canonical_role_options: string[];
  location_options: string[];
  tier_options: { label: string; value: string }[];
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
  archived_by_llm: boolean | null;
  archival_reason: string | null;
}

export interface JobsResponse {
  jobs: Job[];
  total: number;
  run_total: number;
  available_sites: string[];
  page: number;
  limit: number;
}

export type ApplicationStatus =
  | "interested"
  | "applied"
  | "messaged_recruiter"
  | "phone_screen"
  | "interview"
  | "offer"
  | "rejected"
  | "archived";

export interface ApplicationRecruiter {
  id: string;
  name: string | null;
  email: string | null;
  linkedin_url: string | null;
}

export interface Application {
  id: string;
  job_id: string | null;
  company: string;
  title: string;
  status: ApplicationStatus;
  applied_at: string | null;
  notes: string | null;
  priority: "P1" | "P2" | "P3" | null;
  location_group: string | null;
  interview_date: string | null;
  offer_lpa: number | null;
  system_score: number | null;
  resume_match_pct: number | null;
  job_url: string | null;
  company_tier: string | null;
  is_contract: boolean | null;
  location: string | null;
  recruiter: ApplicationRecruiter | null;
}

export interface TrackerStats {
  total: number;
  by_priority: Record<string, number>;
  by_status: Record<string, number>;
  offers_count: number;
  best_offer_lpa: number | null;
  target_lpa: number | null;
}

export interface RunProgress {
  phase: string;
  phase_num: number;
  total_phases: number;
  jobs_found: number;
  message: string;
}

export interface Run {
  id: string;
  status: "pending" | "scraping" | "ranking" | "running" | "done" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  job_count: number | null;
  scrape_count: number | null;
  progress: RunProgress | null;
}

export interface OnboardingStatus {
  onboarding_complete: boolean;
  has_resume: boolean;
}
