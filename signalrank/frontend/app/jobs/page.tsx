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
import { ExternalLink, ChevronUp, ChevronDown, Search, X, Plus, ChevronRight, ChevronLeft, SlidersHorizontal } from "lucide-react";

const col = createColumnHelper<Job>();

function ScoreCell({ value }: { value: number | null }) {
  if (value == null) return <span className="text-[#71717a]">—</span>;
  const pct = value * 100;
  const color = pct >= 80 ? "#22c55e" : pct >= 60 ? "#facc15" : "#ef4444";
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
    cell: (i) => (
      <span className="text-[#e4e4e7] text-xs">{i.getValue()}</span>
    ),
  }),
  col.accessor("company", {
    header: "Company",
    cell: (i) => (
      <span className="text-[#a1a1aa] text-xs">{i.getValue()}</span>
    ),
  }),
  col.accessor("location", {
    header: "Location",
    cell: (i) => (
      <span className="text-[#71717a] text-xs">{i.getValue() ?? "—"}</span>
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
      return v ? (
        <span className="text-[11px] text-[#71717a] border border-[#3f3f46] px-1.5 py-0.5">
          T{v}
        </span>
      ) : <span className="text-[#71717a]">—</span>;
    },
  }),
  col.accessor("is_contract", {
    header: "Type",
    cell: (i) => i.getValue() ? (
      <span className="text-[11px] text-[#facc15] border border-[#facc15]/30 px-1.5 py-0.5">
        CONTRACT
      </span>
    ) : null,
  }),
  col.accessor("site", {
    header: "Source",
    cell: (i) => (
      <span className="text-[#71717a] text-xs">{i.getValue() ?? "—"}</span>
    ),
  }),
  col.display({
    id: "link",
    header: "",
    cell: (i) => (
      <a
        href={i.row.original.job_url}
        target="_blank"
        rel="noreferrer"
        className="text-[#71717a] hover:text-[#22c55e] transition-colors"
      >
        <ExternalLink size={12} />
      </a>
    ),
  }),
];

const TIERS = ["S", "A", "B", "C", "D", ""];

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
    api.jobs.list(token, 1, 200, "").then((r) => {
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
          <span className="text-[11px] text-[#52525b] uppercase tracking-wider">tracked</span>
        ) : (
          <button
            onClick={() => trackJob(job)}
            className="flex items-center gap-0.5 text-[11px] text-[#22c55e]/60 border border-[#22c55e]/20 px-1.5 py-0.5 hover:border-[#22c55e] hover:text-[#22c55e] transition-colors uppercase tracking-wider"
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
              <h1 className="text-xl font-bold text-[#d4d4d8]">All Jobs</h1>
              <span className="text-[#22c55e] text-sm tabular-nums text-glow-dim">{total}</span>
              {activeFilterCount > 0 && (
                <span className="text-[11px] text-[#71717a]">of {allJobs.length}</span>
              )}
            </div>
          </div>
          <div className="flex items-center border border-[#2a2a2e] bg-[#0d0d0f] focus-within:border-[#22c55e] transition-colors w-64">
            <Search size={11} className="text-[#52525b] ml-3 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="search title, company..."
              className="flex-1 bg-transparent px-2 py-2 text-xs text-[#e4e4e7] outline-none placeholder:text-[#52525b]"
            />
            {search && (
              <button onClick={() => setSearch("")} className="pr-2 text-[#71717a] hover:text-[#a1a1aa] transition-colors">
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
                className="flex flex-col items-center gap-1 w-full pt-3 text-[#52525b] hover:text-[#22c55e] transition-colors"
                title={`Filters${activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}`}
              >
                <SlidersHorizontal size={14} />
                <ChevronRight size={12} />
                {activeFilterCount > 0 && (
                  <span className="text-[10px] font-bold text-[#22c55e] tabular-nums">{activeFilterCount}</span>
                )}
              </button>
            ) : (
              <div className="border border-[#2a2a2e] bg-[#111113] p-3 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide">Filters</span>
                  <button
                    onClick={toggleCollapsed}
                    className="text-[#52525b] hover:text-[#22c55e] transition-colors"
                    title="Collapse"
                  >
                    <ChevronLeft size={13} />
                  </button>
                </div>

                {activeFilterCount > 0 && (
                  <button
                    onClick={() => setFilters(DEFAULT_FILTERS)}
                    className="text-xs text-[#22c55e] hover:underline"
                  >
                    Reset filters ({activeFilterCount})
                  </button>
                )}

                {/* Min Score */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">
                    Min Score <span className="tabular-nums text-[#a1a1aa] normal-case font-normal">{filters.minScore}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={filters.minScore}
                    onChange={(e) => setFilters((f) => ({ ...f, minScore: Number(e.target.value) }))}
                    className="w-full accent-[#22c55e]"
                  />
                </div>

                <hr className="border-[#2a2a2e]" />

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
                          background: filters.jobType === t ? "var(--accent, #22c55e)" : "transparent",
                          borderColor: filters.jobType === t ? "var(--accent, #22c55e)" : "#3f3f46",
                          color: filters.jobType === t ? "#fff" : "#71717a",
                        }}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>

                <hr className="border-[#2a2a2e]" />

                {/* Company Tier */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Tier</div>
                  <div className="space-y-1">
                    {TIERS.map((tier) => (
                      <label key={tier || "unknown"} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={filters.tiers.includes(tier)}
                          onChange={() => setFilters((f) => ({ ...f, tiers: toggleItem(f.tiers, tier) }))}
                          className="accent-[#22c55e] w-3 h-3"
                        />
                        <span className="text-sm text-[var(--fg,#e4e4e7)]">
                          {tier === "" ? "Unknown" : `Tier ${tier}`}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <hr className="border-[#2a2a2e]" />

                {/* Date Posted */}
                <div>
                  <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Date Posted</div>
                  <select
                    value={filters.dateRange}
                    onChange={(e) => setFilters((f) => ({ ...f, dateRange: e.target.value as Filters["dateRange"] }))}
                    className="w-full bg-[#0d0d0f] border border-[#3f3f46] text-xs text-[#e4e4e7] px-2 py-1.5 outline-none focus:border-[#22c55e] transition-colors"
                  >
                    <option value="any">Any time</option>
                    <option value="24h">Last 24h</option>
                    <option value="week">Last week</option>
                    <option value="month">Last month</option>
                  </select>
                </div>

                {availableSites.length > 0 && (
                  <>
                    <hr className="border-[#2a2a2e]" />
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
                            <span className="text-sm text-[var(--fg,#e4e4e7)]">{site}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </aside>

          {/* Main content */}
          <div className="flex-1 min-w-0 space-y-5">
            <div className="border border-[#2a2a2e] overflow-hidden">
              <table className="w-full text-xs border-collapse">
                <thead>
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id} className="border-b border-[#2a2a2e] bg-[#0d0d0f]">
                      {hg.headers.map((h) => (
                        <th
                          key={h.id}
                          onClick={h.column.getToggleSortingHandler()}
                          className="px-3 py-3 text-left text-xs text-[#52525b] uppercase tracking-[0.15em] cursor-pointer select-none hover:text-[#22c55e] transition-colors"
                        >
                          <div className="flex items-center gap-1">
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            {h.column.getIsSorted() === "asc" ? (
                              <ChevronUp size={10} className="text-[#22c55e]" />
                            ) : h.column.getIsSorted() === "desc" ? (
                              <ChevronDown size={10} className="text-[#22c55e]" />
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
                      <TableRowSkeleton key={i} cols={9} />
                    ))
                  ) : (
                    table.getRowModel().rows.map((row) => (
                      <tr
                        key={row.id}
                        className="job-row border-b border-[#2a2a2e] bg-[#111113]"
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="px-3 py-2.5">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between text-xs text-[#71717a]">
              <span>
                Showing {total === 0 ? 0 : ((page - 1) * limit) + 1}–{Math.min(page * limit, total)} of {total}
              </span>
              <div className="flex items-center gap-2 font-mono">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1.5 border border-[#3f3f46] hover:border-[#22c55e] hover:text-[#22c55e] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  [&lt; prev]
                </button>
                <span className="px-2">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 border border-[#3f3f46] hover:border-[#22c55e] hover:text-[#22c55e] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  [next &gt;]
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
