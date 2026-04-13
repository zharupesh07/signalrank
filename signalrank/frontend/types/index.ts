export interface ResumeEditorExperience {
  title: string;
  company: string;
  dates: string;
  location: string;
  bullets: string[];
}

export interface ResumeEditorProject {
  name: string;
  url: string;
  description: string;
}

export interface ResumeEditorSkillGroup {
  category: string;
  items: string[];
}

export interface ResumeEditor {
  name: string;
  position: string;
  email: string;
  phone: string;
  location: string;
  linkedin: string;
  github: string;
  website: string;
  summary: string;
  experiences: ResumeEditorExperience[];
  projects: ResumeEditorProject[];
  skills: ResumeEditorSkillGroup[];
  certifications: string[];
}

export interface User {
  id: string;
  email: string;
}

export interface Profile {
  user_id: string;
  email: string;
  is_admin: boolean;
  resume_text: string | null;
  resume_editor: ResumeEditor;
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
  resume_template: string | null;
  scraper_hours_old: number | null;
  scraper_max_terms: number | null;
  onboarding_complete: boolean;
}

export interface ProfileOptions {
  role_options: string[];
  canonical_role_options: string[];
  location_options: string[];
  tier_options: { label: string; value: string }[];
  title_penalty_rules: {
    strong: string[];
    adjacent: string[];
    hybrid: string[];
  };
  company_tier_lists: {
    tier_ss: string[];
    tier_s: string[];
  };
}

export interface Job {
  id: string;
  title: string;
  company: string;
  location: string | null;
  site: string | null;
  job_url: string;
  date_posted: string | null;
  is_new_find: boolean;
  description?: string | null;
  final_score: number | null;
  semantic_score: number | null;
  skills_score: number | null;
  company_score: number | null;
  seniority_score: number | null;
  location_score: number | null;
  recency_score: number | null;
  title_relevance_score: number | null;
  company_tier: string | null;
  is_contract: boolean;
  rank_reason_up?: string | null;
  rank_reason_down?: string | null;
  rank_stage?: "deterministic" | "structured";
  freshness_bucket?: "fresh" | "recent" | "aging" | "stale" | "unknown";
  is_direct_source?: boolean;
  preference_score?: number | null;
  preference_bucket_key?: "top_fit" | "strong_fit" | "possible_fit" | "stretch" | "hide";
  preference_bucket?: "Top fit" | "Strong fit" | "Possible fit" | "Stretch" | "Hide";
  preference_tags?: string[];
  archived_by_llm: boolean | null;
  archival_reason: string | null;
}

export interface JobsResponse {
  jobs: Job[];
  total: number;
  run_total: number;
  new_good_matches: number;
  available_sites: string[];
  page: number;
  limit: number;
}

export interface JobPreferenceWeightedItem {
  value: string;
  label: string;
  weight: number;
}

export interface JobPreferenceExample {
  job_id?: string | null;
  company?: string | null;
  title?: string | null;
  location?: string | null;
  site?: string | null;
  keywords?: string[];
}

export interface JobPreferenceState {
  location_preferences: JobPreferenceWeightedItem[];
  role_preferences: JobPreferenceWeightedItem[];
  positive_tags: JobPreferenceWeightedItem[];
  negative_tags: JobPreferenceWeightedItem[];
  hidden_companies: string[];
  preferred_sources: JobPreferenceWeightedItem[];
  work_mode_preferences: JobPreferenceWeightedItem[];
  positive_examples: JobPreferenceExample[];
  negative_examples: JobPreferenceExample[];
  explanation_snippets: string[];
}

export interface JobFeedbackEvent {
  id: string;
  feedback_text: string | null;
  quick_actions: string[];
  job_ids: string[];
  job_snapshots: {
    job_id: string;
    title?: string | null;
    company?: string | null;
    location?: string | null;
    site?: string | null;
  }[];
  created_at: string | null;
}

export interface JobPreferencesResponse {
  state: JobPreferenceState;
  summary_chips: string[];
  has_learned_preferences: boolean;
  updated_at: string | null;
  recent_feedback: JobFeedbackEvent[];
}

export interface JobFeedbackRequest {
  feedbackText?: string | null;
  quickActions?: string[];
  jobIds?: string[];
  sessionIntent?: string | null;
  page?: number;
  limit?: number;
  sort?: "final_score" | "semantic_score" | "skills_score" | "company_score" | "seniority_score" | "location_score" | "recency_score" | "title_relevance_score" | "date_posted";
  sortDir?: "asc" | "desc";
  search?: string;
  showArchived?: boolean;
  minScore?: number;
  tiers?: string[];
  jobType?: "all" | "fte" | "contract";
  sites?: string[];
  dateRange?: "any" | "24h" | "week" | "month";
}

export interface JobFeedbackResponse {
  preferences: JobPreferencesResponse;
  jobs_payload: JobsResponse;
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
  phase?: string;
  phase_num?: number;
  total_phases?: number;
  jobs_found?: number;
  message?: string;
  requested_mode?: "quick" | "full";
  force_scrape?: boolean;
  disable_scraping?: boolean;
  scrape_executed?: boolean;
  scrape_reason?: string | null;
  run_kind?: string | null;
  auto_refresh?: boolean;
}

export interface Run {
  id: string;
  status: "pending" | "scraping" | "ranking" | "syncing" | "running" | "done" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  job_count: number | null;
  scrape_count: number | null;
  progress: RunProgress | null;
  run_kind?: string | null;
  scrape_reason?: string | null;
  jobs_snapshot?: JobsResponse | null;
  error?: string | null;
  executor_type?: string | null;
}

export interface OnboardingStatus {
  onboarding_complete: boolean;
  has_resume: boolean;
}
