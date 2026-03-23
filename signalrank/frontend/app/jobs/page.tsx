"use client";

import { useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import { api } from "@/lib/api";
import type { Job } from "@/types";
import { useToast } from "@/components/toast";
import { TableRowSkeleton } from "@/components/skeleton";
import { ExternalLink, ChevronUp, ChevronDown, Search, X, Plus, ChevronRight, ChevronLeft, SlidersHorizontal, XCircle } from "lucide-react";

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
    cell: (i) => {
      const url = i.row.original.job_url;
      return url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="text-foreground text-xs hover:text-primary hover:underline transition-colors"
        >
          {i.getValue()}
        </a>
      ) : (
        <span className="text-foreground text-xs">{i.getValue()}</span>
      );
    },
  }),
  col.accessor("company", {
    header: "Company",
    cell: (i) => {
      const v = i.getValue();
      return v ? (
        <span className="text-secondary-foreground text-xs">{v}</span>
      ) : (
        <span className="text-muted-foreground text-xs italic">Unknown</span>
      );
    },
  }),
  col.accessor("location", {
    header: "Location",
    cell: (i) => (
      <span className="text-muted-foreground text-xs">{i.getValue() ?? "—"}</span>
    ),
  }),
  col.accessor("final_score", {
    header: "Score",
    cell: (i) => <ScoreCell value={i.getValue()} />,
  }),
  col.accessor("company_tier", {
    header: "Tier",
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
    cell: (i) => i.getValue() ? (
      <span className="text-[11px] text-[var(--terminal-yellow)] border border-[var(--terminal-yellow)]/30 px-1.5 py-0.5">
        CONTRACT
      </span>
    ) : null,
  }),
  col.accessor("site", {
    header: "Source",
    cell: (i) => (
      <span className="text-muted-foreground text-xs">{i.getValue() ?? "—"}</span>
    ),
  }),
  col.accessor("date_posted", {
    header: "Age",
    cell: (i) => {
      const v = i.getValue();
      if (!v) return <span className="text-muted-foreground text-xs">—</span>;
      const days = Math.floor((Date.now() - new Date(v).getTime()) / 86400000);
      if (days === 0) return <span className="text-xs text-[var(--terminal-green-bright)]">today</span>;
      if (days < 7) return <span className="text-xs text-[var(--terminal-green-bright)]">{days}d</span>;
      if (days < 30) return <span className="text-xs text-[var(--terminal-yellow)]">{Math.floor(days / 7)}w</span>;
      return <span className="text-xs text-muted-foreground">{Math.floor(days / 30)}mo</span>;
    },
  }),
  col.display({
    id: "link",
    header: "",
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

const TIERS = [
  { value: "tier_ss", label: "Tier SS" },
  { value: "tier_s", label: "Tier S" },
  { value: "tier_a", label: "Tier A" },
  { value: "tier_b", label: "Tier B" },
  { value: "tier_c", label: "Tier C" },
  { value: "tier_d", label: "Tier D" },
  { value: "", label: "Unknown" },
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

function filterJobs(jobs: Job[], filters: Filters): Job[] {
  return jobs.filter((job) => {
    if (filters.minScore > 0 && (job.final_score ?? 0) * 100 < filters.minScore) return false;
    if (filters.tiers.length > 0 && !filters.tiers.includes(job.company_tier ?? "")) return false;
    if (filters.jobType === "fte" && job.is_contract) return false;
    if (filters.jobType === "contract" && !job.is_contract) return false;
    if (filters.sites.length > 0 && !filters.sites.includes(job.site ?? "")) return false;
    if (filters.dateRange !== "any") {
      if (!job.date_posted) return false;
      const posted = new Date(job.date_posted);
      const now = new Date();
      const hours = filters.dateRange === "24h" ? 24 : filters.dateRange === "week" ? 168 : 720;
      if ((now.getTime() - posted.getTime()) > hours * 3600000) return false;
    }
    return true;
  });
}

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
  const { toast } = useToast();

  const [allJobs, setAllJobs] = useState<Job[]>([]);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("signalrank-sidebar-collapsed") === "true";
  });
  const limit = 50;

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!token) return;
    api.applications.list(token).then((apps) =>
      setTracked(new Set(apps.filter((a) => a.job_id).map((a) => a.job_id!)))
    ).catch(() => null);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    api.jobs.list(token, 1, 500, "").then((r) => {
      setAllJobs(r.jobs);
      setLoading(false);
    });
  }, [token]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, filters]);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("signalrank-sidebar-collapsed", String(next));
      return next;
    });
  }

  async function trackJob(job: Job) {
    await api.applications.create(token, { job_id: job.id, company: job.company, title: job.title, status: "interested", system_score: job.final_score, resume_match_pct: job.semantic_score });
    setTracked((prev) => new Set(prev).add(job.id));
    toast("Added to tracker", "success");
  }

  const availableSites = useMemo(() => {
    const sites = new Set(allJobs.map((j) => j.site ?? "").filter(Boolean));
    return Array.from(sites).sort();
  }, [allJobs]);

  const searchFiltered = useMemo(() => {
    if (!debouncedSearch) return allJobs;
    const q = debouncedSearch.toLowerCase();
    return allJobs.filter(
      (j) => j.title?.toLowerCase().includes(q) || j.company?.toLowerCase().includes(q)
    );
  }, [allJobs, debouncedSearch]);

  const filteredJobs = useMemo(() => filterJobs(searchFiltered, filters), [searchFiltered, filters]);

  const pageJobs = useMemo(() => {
    const start = (page - 1) * limit;
    return filteredJobs.slice(start, start + limit);
  }, [filteredJobs, page]);

  const total = filteredJobs.length;
  const totalPages = Math.ceil(total / limit) || 1;
  const activeFilterCount = countActiveFilters(filters);

  const allColumns = useMemo(() => [
    ...columns,
    col.display({
      id: "track",
      header: "",
      cell: (i) => {
        const job = i.row.original;
        return tracked.has(job.id) ? (
          <span className="text-[11px] text-muted-foreground uppercase tracking-wider">tracked</span>
        ) : (
          <button
            onClick={() => trackJob(job)}
            className="flex items-center gap-0.5 text-[11px] text-primary/60 border border-primary/20 px-1.5 py-0.5 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider"
          >
            <Plus size={8} />track
          </button>
        );
      },
    }),
  ], [tracked]);

  const table = useReactTable({
    data: pageJobs,
    columns: allColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
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
                <span className="text-[11px] text-muted-foreground">of {allJobs.length}</span>
              )}
            </div>
          </div>
          <div className="flex items-center border border-border bg-input focus-within:border-primary transition-colors w-64">
            <Search size={11} className="text-muted-foreground ml-3 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="search title, company..."
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
                              className="accent-[#22c55e] w-3 h-3"
                            />
                            <span className="text-sm text-foreground">{site}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </aside>

          {/* Main content + detail panel */}
          <div className="flex-1 min-w-0 flex gap-4">
          <div className={`space-y-5 ${selectedJob ? "flex-1 min-w-0" : "w-full"}`}>
            <div className="border border-border overflow-x-auto">
              <table className="w-full text-xs border-collapse min-w-[900px]">
                <thead>
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id} className="border-b border-border bg-input">
                      {hg.headers.map((h) => (
                        <th
                          key={h.id}
                          onClick={h.column.getToggleSortingHandler()}
                          className="px-3 py-3 text-left text-xs text-muted-foreground uppercase tracking-[0.15em] cursor-pointer select-none hover:text-primary transition-colors"
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
                  ))}
                </thead>
                <tbody>
                  {loading ? (
                    Array.from({ length: 10 }).map((_, i) => (
                      <TableRowSkeleton key={i} cols={10} />
                    ))
                  ) : (
                    table.getRowModel().rows.map((row) => {
                      const isSelected = selectedJob?.id === row.original.id;
                      return (
                        <tr
                          key={row.id}
                          onClick={() => setSelectedJob(isSelected ? null : row.original)}
                          className="job-row border-b border-border bg-card cursor-pointer"
                          style={isSelected ? { background: "var(--primary)/5", borderLeft: "2px solid var(--primary)" } : {}}
                        >
                          {row.getVisibleCells().map((cell) => (
                            <td key={cell.id} className="px-3 py-2.5">
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
                Showing {total === 0 ? 0 : ((page - 1) * limit) + 1}–{Math.min(page * limit, total)} of {total}
              </span>
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
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 border border-muted-foreground/40 hover:border-primary hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  [next &gt;]
                </button>
              </div>
            </div>
          </div>

          {/* Detail panel */}
          {selectedJob && (
            <div className="w-80 shrink-0 sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto border border-border bg-card space-y-4 p-4">
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
              </div>

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

              {selectedJob.description && (
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
