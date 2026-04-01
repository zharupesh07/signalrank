"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import { api } from "@/lib/api";
import type { Job } from "@/types";
import { useToast } from "@/components/toast";
import { TableRowSkeleton } from "@/components/skeleton";
import { ExternalLink, ChevronUp, ChevronDown, Search, X, Plus, ChevronRight, ChevronLeft, SlidersHorizontal, XCircle, Archive, Loader2 } from "lucide-react";

const col = createColumnHelper<Job>();

function scoreColor(pct: number): string {
  if (pct >= 75) return "var(--primary)";
  if (pct >= 60) return "var(--terminal-green-bright)";
  if (pct >= 45) return "var(--terminal-yellow)";
  return "var(--destructive)";
}

const TIER_COLORS: Record<string, string> = {
  tier_ss: "var(--primary)",
  tier_s:  "var(--terminal-green-bright)",
  tier_a:  "#4ade80",
  tier_b:  "var(--terminal-yellow)",
  tier_c:  "#f97316",
  tier_d:  "var(--muted-foreground)",
};

function parseApiDate(value: string | null): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatJobAge(value: string | null): { label: string; color: string } | null {
  const postedAt = parseApiDate(value);
  if (!postedAt) return null;

  const days = Math.max(0, Math.floor((Date.now() - postedAt.getTime()) / 86400000));
  if (days === 0) {
    return { label: "today", color: "var(--terminal-green-bright)" };
  }
  if (days < 14) {
    return { label: `${days}d`, color: "var(--terminal-green-bright)" };
  }
  if (days < 60) {
    return { label: `${Math.floor(days / 7)}w`, color: "var(--terminal-yellow)" };
  }
  return { label: `${Math.floor(days / 30)}mo`, color: "var(--muted-foreground)" };
}

function ScoreCell({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const pct = value * 100;
  const color = scoreColor(pct);
  return (
    <div className="flex items-center gap-2">
      <span className="tabular-nums text-xs font-bold" style={{ color }}>
        {pct.toFixed(0)}
      </span>
      <div className="score-bar w-12">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

const columns = [
  col.accessor("title", {
    header: "Title",
    size: 260,
    cell: (i) => (
      <span className="text-secondary-foreground text-xs font-medium leading-snug block">
        {i.getValue() ?? "—"}
      </span>
    ),
  }),
  col.accessor("company", {
    header: "Company",
    size: 160,
    cell: (i) => {
      const v = i.getValue();
      return v ? (
        <span className="text-secondary-foreground text-xs line-clamp-2">{v}</span>
      ) : (
        <span className="text-muted-foreground text-xs italic">Unknown</span>
      );
    },
  }),
  col.accessor("location", {
    header: "Location",
    size: 90,
    cell: (i) => (
      <span className="text-muted-foreground text-xs">{i.getValue() ?? "—"}</span>
    ),
  }),
  col.accessor("final_score", {
    header: "Score",
    size: 100,
    cell: (i) => <ScoreCell value={i.getValue()} />,
  }),
  col.accessor("company_tier", {
    header: "Tier",
    size: 60,
    cell: (i) => {
      const v = i.getValue();
      const label = v ? v.replace("tier_", "").toUpperCase() : null;
      const color = v ? TIER_COLORS[v] ?? "var(--muted-foreground)" : null;
      return label && color ? (
        <span
          className="text-[11px] px-1.5 py-0.5 border"
          style={{ color, borderColor: `${color}60` }}
        >
          {label}
        </span>
      ) : <span className="text-muted-foreground">—</span>;
    },
  }),
  col.accessor("is_contract", {
    header: "Type",
    size: 80,
    cell: (i) => i.getValue() ? (
      <span className="text-[11px] text-[var(--terminal-yellow)] border border-[var(--terminal-yellow)]/30 px-1.5 py-0.5">
        CONTRACT
      </span>
    ) : null,
  }),
  col.accessor("site", {
    header: "Source",
    size: 70,
    cell: (i) => (
      <span className="text-muted-foreground text-xs">{i.getValue() ?? "—"}</span>
    ),
  }),
  col.accessor("date_posted", {
    header: "Age",
    size: 50,
    cell: (i) => {
      const age = formatJobAge(i.getValue());
      if (!age) return <span className="text-muted-foreground text-xs">—</span>;
      return <span className="text-xs" style={{ color: age.color }}>{age.label}</span>;
    },
  }),
  col.display({
    id: "link",
    header: "",
    size: 32,
    cell: (i) => (
      <a
        href={i.row.original.job_url}
        target="_blank"
        rel="noreferrer"
        className="text-muted-foreground hover:text-primary transition-colors"
      >
        <ExternalLink size={12} />
      </a>
    ),
  }),
];

type JobsSortField =
  | "final_score"
  | "semantic_score"
  | "skills_score"
  | "company_score"
  | "seniority_score"
  | "location_score"
  | "recency_score"
  | "date_posted";

function getApiSort(sorting: SortingState): { sort: JobsSortField; sortDir: "asc" | "desc" } {
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

const TIERS = [
  { value: "tier_ss", label: "Tier SS" },
  { value: "tier_s", label: "Tier S" },
  { value: "tier_a", label: "Tier A" },
  { value: "tier_b", label: "Tier B" },
  { value: "tier_c", label: "Tier C" },
  { value: "tier_d", label: "Tier D" },
  { value: "unknown", label: "Unknown" },
];

interface Filters {
  minScore: number;
  tiers: string[];
  jobType: "all" | "fte" | "contract";
  sites: string[];
  dateRange: "any" | "24h" | "week" | "month";
}

const DEFAULT_FILTERS: Filters = {
  minScore: 0,
  tiers: [],
  jobType: "all",
  sites: [],
  dateRange: "any",
};

function countActiveFilters(filters: Filters): number {
  let n = 0;
  if (filters.minScore > 0) n++;
  if (filters.tiers.length > 0) n++;
  if (filters.jobType !== "all") n++;
  if (filters.sites.length > 0) n++;
  if (filters.dateRange !== "any") n++;
  return n;
}

function toggleItem<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter((x) => x !== item) : [...arr, item];
}

export default function JobsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const isAdmin = Boolean((session as { isAdmin?: boolean })?.isAdmin);
  const { toast } = useToast();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [runTotal, setRunTotal] = useState(0);
  const [availableSites, setAvailableSites] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([{ id: "final_score", desc: true }]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [selectedJobLoading, setSelectedJobLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [pageSize, setPageSize] = useState(50);
  const [showArchived, setShowArchived] = useState(true);
  const [archiveStatus, setArchiveStatus] = useState<{ total: number; done: number; pending: number; running: number } | null>(null);
  const [archiving, setArchiving] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("signalrank-sidebar-collapsed");
    if (saved === "true") setCollapsed(true);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!token) {
      setTracked(new Set());
      return;
    }
    api.applications.trackedJobIds(token).then((ids) =>
      setTracked(new Set(ids))
    ).catch(() => null);
  }, [token]);

  useEffect(() => {
    if (!token) {
      setJobs([]);
      setTotal(0);
      setRunTotal(0);
      setAvailableSites([]);
      setLoading(false);
      return;
    }
  }, [token]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, filters, showArchived, pageSize, sorting]);

  const loadJobs = useCallback(async () => {
    if (!token) return;
    const hasJobs = jobs.length > 0;
    if (hasJobs) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const { sort, sortDir } = getApiSort(sorting);
      const response = await api.jobs.list(token, {
        page,
        limit: pageSize,
        sort,
        sortDir,
        search: debouncedSearch,
        showArchived,
        minScore: filters.minScore,
        tiers: filters.tiers,
        jobType: filters.jobType,
        sites: filters.sites,
        dateRange: filters.dateRange,
      });
      setJobs(response.jobs);
      setTotal(response.total);
      setRunTotal(response.run_total);
      setAvailableSites(response.available_sites);
      setSelectedJob((current) => {
        if (!current) return null;
        const updated = response.jobs.find((job) => job.id === current.id);
        return updated ? { ...current, ...updated } : current;
      });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, page, pageSize, debouncedSearch, showArchived, filters, sorting, jobs.length]);

  useEffect(() => {
    loadJobs().catch(() => null);
  }, [loadJobs]);

  const toggleSelectedJob = useCallback(async (job: Job) => {
    const isSelected = selectedJob?.id === job.id;
    if (isSelected) {
      setSelectedJob(null);
      setSelectedJobLoading(false);
      return;
    }

    setSelectedJob(job);
    if (job.description !== undefined) {
      setSelectedJobLoading(false);
      return;
    }

    setSelectedJobLoading(true);
    try {
      const detail = await api.jobs.get(token, job.id);
      setSelectedJob((current) => (current?.id === job.id ? { ...current, ...detail } : current));
    } catch {
      toast("Failed to load job details", "error");
    } finally {
      setSelectedJobLoading(false);
    }
  }, [selectedJob?.id, toast, token]);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("signalrank-sidebar-collapsed", String(next));
      return next;
    });
  }

  const trackJob = useCallback(async (job: Job) => {
    try {
      await api.applications.create(token, { job_id: job.id, company: job.company, title: job.title, status: "interested", system_score: job.final_score, resume_match_pct: job.semantic_score });
      setTracked((prev) => new Set(prev).add(job.id));
      toast("Added to tracker", "success");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.startsWith("409")) {
        setTracked((prev) => new Set(prev).add(job.id));
        toast("Already tracked", "info");
      } else {
        toast(msg || "Failed to track job", "error");
      }
    }
  }, [token, toast]);

  async function triggerArchive() {
    if (!isAdmin) return;
    setArchiving(true);
    try {
      const res = await api.jobs.archiveUnsuitable(token);
      toast(`Queued ${res.queued} jobs for evaluation`, "success");
      pollArchiveStatus();
    } catch {
      toast("Failed to start archival", "error");
    } finally {
      setArchiving(false);
    }
  }

  const pollArchiveStatus = useCallback(() => {
    if (!isAdmin) return;
    let delay = 5000;
    const MAX_DELAY = 60000;
    const timeoutRef = { current: undefined as ReturnType<typeof setTimeout> | undefined };

    function schedule() {
      timeoutRef.current = setTimeout(async () => {
        try {
          const status = await api.jobs.archiveStatus(token);
          setArchiveStatus(status);
          if (status.pending === 0 && status.running === 0 && status.total > 0) {
            loadJobs().catch(() => null);
            return;
          }
          const multiplier = document.hidden ? 2.0 : 1.5;
          delay = Math.min(delay * multiplier, MAX_DELAY);
          schedule();
        } catch {
          clearTimeout(timeoutRef.current);
        }
      }, document.hidden ? Math.max(delay, 15000) : delay);
    }

    schedule();
  }, [isAdmin, token, loadJobs]);

  useEffect(() => {
    if (!token || !isAdmin) {
      setArchiveStatus(null);
      return;
    }
    api.jobs.archiveStatus(token).then((s) => {
      setArchiveStatus(s);
      if (s.pending > 0 || s.running > 0) pollArchiveStatus();
    }).catch(() => null);
  }, [token, isAdmin, pollArchiveStatus]);

  const totalPages = Math.ceil(total / pageSize) || 1;
  const activeFilterCount = countActiveFilters(filters);

  const allColumns = useMemo(() => [
    ...columns,
    col.display({
      id: "track",
      header: "",
      size: 80,
      cell: (i) => {
        const job = i.row.original;
        return tracked.has(job.id) ? (
          <span className="text-[11px] text-muted-foreground uppercase tracking-wider">tracked</span>
        ) : (
          <button
            onClick={(e) => { e.stopPropagation(); trackJob(job); }}
            className="flex items-center gap-0.5 text-[11px] text-primary/60 border border-primary/20 px-1.5 py-0.5 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider"
          >
            <Plus size={8} />track
          </button>
        );
      },
    }),
  ], [tracked, trackJob]);

  const table = useReactTable({
    data: jobs,
    columns: allColumns,
    state: { sorting },
    onSortingChange: setSorting,
    manualSorting: true,
    getCoreRowModel: getCoreRowModel(),
  });


  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-end justify-between gap-4 mb-5">
          <div>
            <div className="section-label mb-1">job index</div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-bold text-foreground">All Jobs</h1>
              <span className="text-primary text-sm tabular-nums text-glow-dim">{total}</span>
              {activeFilterCount > 0 && (
                <span className="text-[11px] text-muted-foreground">of {runTotal}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {isAdmin && (
              <button
                onClick={triggerArchive}
                disabled={archiving || (archiveStatus !== null && (archiveStatus.pending > 0 || archiveStatus.running > 0))}
                className="flex items-center gap-1.5 text-[11px] border border-border px-3 py-2 hover:border-primary hover:text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed uppercase tracking-wider"
                title="Queue archival evaluation in the background for the current successful run"
              >
                {archiving || (archiveStatus && (archiveStatus.pending > 0 || archiveStatus.running > 0)) ? (
                  <><Loader2 size={11} className="animate-spin" />archiving {archiveStatus ? `${archiveStatus.done}/${archiveStatus.total}` : ""}</>
                ) : (
                  <><Archive size={11} />manual archive run</>
                )}
              </button>
            )}
          </div>
          <div className="flex items-center border border-border bg-input focus-within:border-primary transition-colors w-64">
            <Search size={11} className="text-muted-foreground ml-3 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="search title, company..."
              suppressHydrationWarning
              className="flex-1 bg-transparent px-2 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
            {search && (
              <button onClick={() => setSearch("")} className="pr-2 text-muted-foreground hover:text-secondary-foreground transition-colors">
                <X size={11} />
              </button>
            )}
          </div>
        </div>

        <div className="flex gap-4">
          {/* Sidebar */}
          <aside
            className="shrink-0 sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto"
            style={{ width: collapsed ? 40 : 220 }}
          >
            {collapsed ? (
              <button
                onClick={toggleCollapsed}
                className="flex flex-col items-center gap-1 w-full pt-3 text-muted-foreground hover:text-primary transition-colors"
                title={`Filters${activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}`}
              >
                <SlidersHorizontal size={14} />
                <ChevronRight size={12} />
                {activeFilterCount > 0 && (
                  <span className="text-[10px] font-bold text-primary tabular-nums">{activeFilterCount}</span>
                )}
              </button>
            ) : (
              <div className="border border-border bg-card p-3 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide">Filters</span>
                  <button
                    onClick={toggleCollapsed}
                    className="text-muted-foreground hover:text-primary transition-colors"
                    title="Collapse"
                  >
                    <ChevronLeft size={13} />
                  </button>
                </div>

                {activeFilterCount > 0 && (
                  <button
                    onClick={() => setFilters(DEFAULT_FILTERS)}
                    className="text-xs text-primary hover:underline"
                  >
                    Reset filters ({activeFilterCount})
                  </button>
                )}

                {/* Min Score */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">
                    Min Score <span className="tabular-nums text-secondary-foreground normal-case font-normal">{filters.minScore}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={filters.minScore}
                    onChange={(e) => setFilters((f) => ({ ...f, minScore: Number(e.target.value) }))}
                    suppressHydrationWarning
                    className="w-full accent-primary"
                  />
                </div>

                <hr className="border-border" />

                {/* Job Type */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Job Type</div>
                  <div className="flex gap-1">
                    {(["all", "fte", "contract"] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setFilters((f) => ({ ...f, jobType: t }))}
                        className="flex-1 text-[10px] py-1 border transition-colors uppercase tracking-wide"
                        style={{
                          background: filters.jobType === t ? "var(--primary)" : "transparent",
                          borderColor: filters.jobType === t ? "var(--primary)" : "var(--muted-foreground)",
                          color: filters.jobType === t ? "var(--primary-foreground)" : "var(--muted-foreground)",
                        }}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>

                <hr className="border-border" />

                {/* Company Tier */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Tier</div>
                  <div className="space-y-1">
                    {TIERS.map((tier) => (
                      <label key={tier.value || "unknown"} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={filters.tiers.includes(tier.value)}
                          onChange={() => setFilters((f) => ({ ...f, tiers: toggleItem(f.tiers, tier.value) }))}
                          suppressHydrationWarning
                          className="accent-[#22c55e] w-3 h-3"
                        />
                        <span className="text-sm text-foreground">
                          {tier.label}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <hr className="border-border" />

                {/* Date Posted */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Date Posted</div>
                  <select
                    value={filters.dateRange}
                    onChange={(e) => setFilters((f) => ({ ...f, dateRange: e.target.value as Filters["dateRange"] }))}
                    suppressHydrationWarning
                    className="w-full bg-input border border-muted-foreground/40 text-xs text-foreground px-2 py-1.5 outline-none focus:border-primary transition-colors"
                  >
                    <option value="any">Any time</option>
                    <option value="24h">Last 24h</option>
                    <option value="week">Last week</option>
                    <option value="month">Last month</option>
                  </select>
                </div>

                {availableSites.length > 0 && (
                  <>
                    <hr className="border-border" />
                    <div>
                      <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Source</div>
                      <div className="space-y-1">
                        {availableSites.map((site) => (
                          <label key={site} className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={filters.sites.includes(site)}
                              onChange={() => setFilters((f) => ({ ...f, sites: toggleItem(f.sites, site) }))}
                              suppressHydrationWarning
                              className="accent-[#22c55e] w-3 h-3"
                            />
                            <span className="text-sm text-foreground">{site}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </>
                )}

                <hr className="border-border" />

                {/* Show Archived */}
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={showArchived}
                    onChange={() => setShowArchived((v) => !v)}
                    suppressHydrationWarning
                    className="accent-[#22c55e] w-3 h-3"
                  />
                  <span className="text-xs text-foreground">Show archived</span>
                </label>
              </div>
            )}
          </aside>

          {/* Main content + detail panel */}
          <div className="flex-1 min-w-0 flex gap-4">
          <div className={`space-y-5 ${selectedJob ? "flex-1 min-w-0" : "w-full"}`}>
            <div className="border border-border overflow-x-auto relative">
              {refreshing && (
                <div className="absolute inset-0 z-10 bg-background/35 pointer-events-none" />
              )}
              <table className="jobs-table w-full text-xs border-collapse min-w-[900px]">
                <colgroup>
                  <col style={{ width: 260 }} />
                  <col style={{ width: 160 }} />
                  <col style={{ width: 90 }} />
                  <col style={{ width: 100 }} />
                  <col style={{ width: 60 }} />
                  <col style={{ width: 80 }} />
                  <col style={{ width: 70 }} />
                  <col style={{ width: 50 }} />
                  <col style={{ width: 32 }} />
                  <col style={{ width: 80 }} />
                </colgroup>
                <thead>
                  <tr className="border-b border-border bg-input">
                    {table.getHeaderGroups()[0].headers.map((h) => (
                      <th
                        key={h.id}
                        onClick={h.column.getToggleSortingHandler()}
                        className="px-3 py-3 text-left text-xs text-muted-foreground uppercase tracking-[0.15em] cursor-pointer select-none hover:text-primary transition-colors overflow-hidden"
                      >
                        <div className="flex items-center gap-1">
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {h.column.getIsSorted() === "asc" ? (
                            <ChevronUp size={10} className="text-primary" />
                          ) : h.column.getIsSorted() === "desc" ? (
                            <ChevronDown size={10} className="text-primary" />
                          ) : null}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    Array.from({ length: 10 }).map((_, i) => (
                      <TableRowSkeleton key={i} cols={10} />
                    ))
                  ) : table.getRowModel().rows.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="px-4 py-16 text-center">
                        <div className="font-mono text-muted-foreground text-xs space-y-1">
                          <div>┌─────────────────────┐</div>
                          <div>│   no jobs found     │</div>
                          <div>└─────────────────────┘</div>
                          <div className="mt-2">
                            {runTotal === 0
                              ? "trigger a scan from the dashboard to populate results"
                              : "try adjusting your filters"}
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    table.getRowModel().rows.map((row) => {
                      const job = row.original;
                      const isSelected = selectedJob?.id === job.id;
                      return (
                        <tr
                          key={row.id}
                          onClick={() => { toggleSelectedJob(job).catch(() => null); }}
                          className="job-row-item border-b border-border bg-card"
                          style={{
                            ...(isSelected ? { boxShadow: "inset 2px 0 0 var(--primary)", background: "color-mix(in srgb, var(--primary) 5%, transparent)" } : {}),
                            ...(job.archived_by_llm ? { opacity: 0.45 } : {}),
                            ...(refreshing ? { opacity: 0.7 } : {}),
                          }}
                        >
                          {row.getVisibleCells().map((cell) => (
                            <td key={cell.id} className="px-3 py-2.5 overflow-hidden">
                              {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </td>
                          ))}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                {total === 0
                  ? "Showing 0"
                  : `Showing ${((page - 1) * pageSize) + 1}–${Math.min(page * pageSize, total)} of ${total}`}
              </span>
              <div className="flex items-center gap-3" suppressHydrationWarning>
                <div className="flex items-center gap-1 font-mono">
                  {[25, 50, 100].map((s) => (
                    <button
                      key={s}
                      onClick={() => setPageSize(s)}
                      className={`px-2 py-1 border transition-colors ${pageSize === s ? "border-primary text-primary font-semibold" : "border-muted-foreground/40 hover:border-primary hover:text-primary"}`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2 font-mono">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="px-3 py-1.5 border border-muted-foreground/40 hover:border-primary hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    [&lt; prev]
                  </button>
                  <span className="px-2">
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="px-3 py-1.5 border border-muted-foreground/40 hover:border-primary hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    [next &gt;]
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Detail panel backdrop (click to close) */}
          {selectedJob && (
            <div className="fixed inset-0 z-30" onClick={() => setSelectedJob(null)} />
          )}

          {/* Detail panel */}
          {selectedJob && (
            <div className="w-80 shrink-0 sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto border border-border bg-card space-y-4 p-4 z-40 relative">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-xs font-bold text-foreground leading-snug">{selectedJob.title}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">{selectedJob.company}</div>
                </div>
                <button onClick={() => setSelectedJob(null)} className="text-muted-foreground hover:text-foreground transition-colors shrink-0 mt-0.5">
                  <XCircle size={14} />
                </button>
              </div>

              {/* Score breakdown */}
              <div className="space-y-2">
                {[
                  { label: "Overall", value: selectedJob.final_score },
                  { label: "Resume match", value: selectedJob.semantic_score },
                  { label: "Skills", value: selectedJob.skills_score },
                  { label: "Company", value: selectedJob.company_score },
                ].map(({ label, value }) => {
                  if (value == null) return null;
                  const pct = value * 100;
                  const color = scoreColor(pct);
                  return (
                    <div key={label} className="flex items-center gap-2">
                      <span className="text-[10px] text-muted-foreground w-24 shrink-0">{label}</span>
                      <div className="flex-1 h-1 bg-muted overflow-hidden">
                        <div className="h-full" style={{ width: `${pct}%`, background: color }} />
                      </div>
                      <span className="text-[10px] tabular-nums w-7 text-right" style={{ color }}>{pct.toFixed(0)}%</span>
                    </div>
                  );
                })}
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {selectedJob.company_tier && (
                  <span
                    className="text-[10px] px-1.5 py-0.5 border"
                    style={{
                      color: TIER_COLORS[selectedJob.company_tier] ?? "var(--muted-foreground)",
                      borderColor: `${TIER_COLORS[selectedJob.company_tier] ?? "var(--muted-foreground)"}60`,
                    }}
                  >
                    {selectedJob.company_tier.replace("tier_", "").toUpperCase()}
                  </span>
                )}
                {selectedJob.is_contract && (
                  <span className="text-[10px] text-[var(--terminal-yellow)] border border-[var(--terminal-yellow)]/30 px-1.5 py-0.5">CONTRACT</span>
                )}
                <span className="text-[10px] text-muted-foreground">{selectedJob.location ?? "—"}</span>
                <span className="text-[10px] text-muted-foreground">{selectedJob.site}</span>
                {selectedJob.archived_by_llm && (
                  <span className="text-[10px] text-destructive border border-destructive/30 px-1.5 py-0.5">ARCHIVED</span>
                )}
              </div>

              {selectedJob.archival_reason && (
                <div className="text-[11px] text-muted-foreground bg-muted/30 border border-border px-2 py-1.5 italic">
                  {selectedJob.archival_reason}
                </div>
              )}

              <div className="flex items-center gap-2 pt-1">
                {selectedJob.job_url && (
                  <a
                    href={selectedJob.job_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1 text-[11px] text-muted-foreground border border-border px-2 py-1 hover:text-primary hover:border-primary/40 transition-colors"
                  >
                    Open <ExternalLink size={9} />
                  </a>
                )}
                {tracked.has(selectedJob.id) ? (
                  <span className="text-[11px] text-muted-foreground uppercase tracking-wider">tracked</span>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); trackJob(selectedJob); }}
                    className="flex items-center gap-1 text-[11px] text-primary border border-primary/30 px-2 py-1 hover:bg-primary/10 transition-colors uppercase tracking-wider"
                  >
                    <Plus size={8} />track
                  </button>
                )}
              </div>

              {selectedJobLoading && (
                <div className="pt-1 border-t border-border space-y-2">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Description</div>
                  <div className="space-y-2">
                    <div className="skeleton h-3 rounded w-full" />
                    <div className="skeleton h-3 rounded w-[92%]" />
                    <div className="skeleton h-3 rounded w-[88%]" />
                    <div className="skeleton h-3 rounded w-[76%]" />
                  </div>
                </div>
              )}

              {selectedJob.description && !selectedJobLoading && (
                <div className="pt-1 border-t border-border">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">Description</div>
                  <p className="text-[11px] text-secondary-foreground leading-relaxed whitespace-pre-wrap">
                    {selectedJob.description.slice(0, 2000)}{selectedJob.description.length > 2000 ? "…" : ""}
                  </p>
                </div>
              )}
            </div>
          )}
          </div>
        </div>
      </div>
    </div>
  );
}
