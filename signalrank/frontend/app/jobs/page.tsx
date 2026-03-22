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
import { ExternalLink, ChevronUp, ChevronDown, Search, X, Plus } from "lucide-react";

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

export default function JobsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [tracked, setTracked] = useState<Set<string>>(new Set());
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
    setPage(1);
  }, [debouncedSearch]);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    api.jobs.list(token, page, limit, debouncedSearch).then((r) => {
      setJobs(r.jobs);
      setTotal(r.total);
      setLoading(false);
    });
  }, [token, page, debouncedSearch]);

  async function trackJob(job: Job) {
    await api.applications.create(token, { job_id: job.id, company: job.company, title: job.title, status: "interested", system_score: job.final_score, resume_match_pct: job.semantic_score });
    setTracked((prev) => new Set(prev).add(job.id));
    toast("Added to tracker", "success");
  }

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
    data: jobs,
    columns: allColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-6xl mx-auto px-6 py-8 space-y-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <div className="section-label mb-1">job index</div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-bold text-[#d4d4d8]">All Jobs</h1>
              <span className="text-[#22c55e] text-sm tabular-nums text-glow-dim">{total}</span>
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
                  <TableRowSkeleton key={i} cols={8} />
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
            Showing {((page - 1) * limit) + 1}–{Math.min(page * limit, total)} of {total}
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
  );
}
