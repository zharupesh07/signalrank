"use client";

import { useEffect, useState } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { ExternalLink, Plus } from "lucide-react";
import type { Job } from "@/types";
import { scoreColor, formatJobAge } from "@/lib/formatting";

const col = createColumnHelper<Job>();

export const TIER_COLORS: Record<string, string> = {
  tier_ss: "var(--primary)",
  tier_s:  "var(--terminal-green-bright)",
  tier_a:  "#4ade80",
  tier_b:  "var(--terminal-yellow)",
  tier_c:  "#f97316",
  tier_d:  "var(--muted-foreground)",
};

export function ScoreCell({ value }: { value: number | null }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  if (value == null) return <span className="text-muted-foreground">—</span>;
  const pct = value * 100;
  const color = scoreColor(pct);
  return (
    <div className="flex items-center gap-2">
      <span className="tabular-nums text-xs font-bold" style={{ color }}>
        {pct.toFixed(0)}
      </span>
      <div className="score-bar w-12">
        <div
          className="score-bar-fill"
          style={{ width: mounted ? `${pct}%` : "0%", background: color }}
        />
      </div>
    </div>
  );
}

type ColumnHandlers = {
  tracked: Set<string>;
  trackJob: (job: Job) => Promise<void>;
};

export function getColumns({ tracked, trackJob }: ColumnHandlers) {
  return [
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
  ];
}
