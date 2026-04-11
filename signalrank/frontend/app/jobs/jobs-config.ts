import type { SortingState } from "@tanstack/react-table";

export const TIER_DESCRIPTIONS: Record<string, string> = {
  tier_ss: "SS — Elite (FAANG, top-5 unicorns). Best comp & brand.",
  tier_s: "S — Excellent (top startups, strong mid-caps). Great comp.",
  tier_a: "A — Strong (solid growth-stage companies). Good comp.",
  tier_b: "B — Decent (stable mid-size). Market comp.",
  tier_c: "C — Fair (small or unknown companies).",
  tier_d: "D — Below target (low tier or uncertain).",
};

export type JobsSortField =
  | "final_score"
  | "semantic_score"
  | "skills_score"
  | "company_score"
  | "seniority_score"
  | "location_score"
  | "recency_score"
  | "date_posted";

export interface Filters {
  minScore: number;
  tiers: string[];
  jobType: "all" | "fte" | "contract";
  sites: string[];
  dateRange: "any" | "24h" | "week" | "month";
}

export const DEFAULT_FILTERS: Filters = {
  minScore: 0,
  tiers: [],
  jobType: "all",
  sites: [],
  dateRange: "any",
};

export const TIERS = [
  { value: "tier_ss", label: "Tier SS" },
  { value: "tier_s", label: "Tier S" },
  { value: "tier_a", label: "Tier A" },
  { value: "tier_b", label: "Tier B" },
  { value: "tier_c", label: "Tier C" },
  { value: "tier_d", label: "Tier D" },
  { value: "unknown", label: "Unknown" },
];

export const JOB_PRESETS = [
  {
    key: "best",
    label: "Best Matches",
    apply: () => ({
      filters: { ...DEFAULT_FILTERS, minScore: 70 },
      search: "",
      sorting: [{ id: "final_score", desc: true }] as SortingState,
      showArchived: true,
    }),
  },
  {
    key: "fresh",
    label: "Fresh",
    apply: () => ({
      filters: { ...DEFAULT_FILTERS, dateRange: "week" as const },
      search: "",
      sorting: [{ id: "date_posted", desc: true }] as SortingState,
      showArchived: true,
    }),
  },
  {
    key: "top-companies",
    label: "Top Companies",
    apply: () => ({
      filters: { ...DEFAULT_FILTERS, tiers: ["tier_ss", "tier_s", "tier_a"] },
      search: "",
      sorting: [{ id: "final_score", desc: true }] as SortingState,
      showArchived: true,
    }),
  },
  {
    key: "no-contract",
    label: "No Contract",
    apply: () => ({
      filters: { ...DEFAULT_FILTERS, jobType: "fte" as const },
      search: "",
      sorting: [{ id: "final_score", desc: true }] as SortingState,
      showArchived: true,
    }),
  },
  {
    key: "remote",
    label: "Remote",
    apply: () => ({
      filters: { ...DEFAULT_FILTERS },
      search: "remote",
      sorting: [{ id: "final_score", desc: true }] as SortingState,
      showArchived: true,
    }),
  },
];

export function getApiSort(
  sorting: SortingState
): { sort: JobsSortField; sortDir: "asc" | "desc" } {
  const current = sorting[0];
  if (!current) {
    return { sort: "final_score", sortDir: "desc" };
  }
  const allowed = new Set<JobsSortField>([
    "final_score",
    "semantic_score",
    "skills_score",
    "company_score",
    "seniority_score",
    "location_score",
    "recency_score",
    "date_posted",
  ]);
  if (!allowed.has(current.id as JobsSortField)) {
    return { sort: "final_score", sortDir: "desc" };
  }
  return {
    sort: current.id as JobsSortField,
    sortDir: current.desc ? "desc" : "asc",
  };
}

export function countActiveFilters(filters: Filters): number {
  let n = 0;
  if (filters.minScore > 0) n++;
  if (filters.tiers.length > 0) n++;
  if (filters.jobType !== "all") n++;
  if (filters.sites.length > 0) n++;
  if (filters.dateRange !== "any") n++;
  return n;
}

export function toggleItem<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter((x) => x !== item) : [...arr, item];
}
