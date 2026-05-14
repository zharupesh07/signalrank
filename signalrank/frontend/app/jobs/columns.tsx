"use client";

import { createColumnHelper } from "@tanstack/react-table";
import { AlertTriangle, ExternalLink, Plus } from "lucide-react";
import type { Job } from "@/types";
import { formatJobAge, formatSourceLabel } from "@/lib/formatting";

const col = createColumnHelper<Job>();

export const TIER_COLORS: Record<string, string> = {
  tier_ss: "var(--primary)",
  tier_s:  "var(--terminal-green-bright)",
  tier_a:  "#4ade80",
  tier_b:  "var(--terminal-yellow)",
  tier_c:  "#f97316",
  tier_d:  "var(--muted-foreground)",
};

const BUCKET_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  top_fit: { color: "var(--primary)", bg: "color-mix(in srgb, var(--primary) 9%, transparent)", label: "Top fit" },
  strong_fit: { color: "var(--terminal-green-bright)", bg: "color-mix(in srgb, var(--terminal-green-bright) 8%, transparent)", label: "Strong" },
  possible_fit: { color: "#4ade80", bg: "color-mix(in srgb, #4ade80 8%, transparent)", label: "Possible" },
  stretch: { color: "var(--terminal-yellow)", bg: "color-mix(in srgb, var(--terminal-yellow) 9%, transparent)", label: "Stretch" },
  hide: { color: "var(--muted-foreground)", bg: "color-mix(in srgb, var(--muted-foreground) 7%, transparent)", label: "Hide" },
};

export function FitBucketCell({ job }: { job: Job }) {
  const bucketKey = job.preference_bucket_key ?? "possible_fit";
  const style = BUCKET_STYLES[bucketKey] ?? BUCKET_STYLES.possible_fit;
  const bucketLabel = style.label ?? job.preference_bucket ?? "Possible";
  const reason = job.rank_reason_down || job.rank_reason_up;

  return (
    <div
      className="group/fit grid max-w-[180px] grid-cols-[3px_minmax(0,1fr)] overflow-hidden border border-border/80 bg-background/40"
      title={reason || job.preference_bucket || undefined}
    >
      <span style={{ background: style.color }} />
      <div className="min-w-0 px-2.5 py-2" style={{ background: style.bg }}>
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[11px] font-medium uppercase tracking-[0.12em]" style={{ color: style.color }}>
            {bucketLabel}
          </span>
          {job.rank_reason_down ? (
            <AlertTriangle
              aria-hidden="true"
              className="size-3 shrink-0 text-[var(--terminal-yellow)]"
            />
          ) : null}
        </div>
        {reason ? (
          <div className="mt-1 truncate text-[10px] leading-4 text-muted-foreground">
            {reason}
          </div>
        ) : (
          <div className="mt-1 text-[10px] leading-4 text-muted-foreground/70">No major caveats</div>
        )}
      </div>
    </div>
  );
}

export function SignalsCell({ job }: { job: Job }) {
  const tags = job.preference_tags ?? [];
  if (tags.length === 0) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {tags.slice(0, 3).map((tag) => (
        <span
          key={tag}
          className="text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground uppercase tracking-[0.14em]"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}

function sourceTone(site: string | null | undefined, direct: boolean | undefined) {
  const value = String(site || "").trim();
  if (direct || ["greenhouse", "ashby", "lever", "workday", "company_portal", "smartrecruiters"].includes(value)) {
    return {
      label: value === "company_portal" ? "Company" : "Direct",
      color: "var(--primary)",
    };
  }
  if (["li_jobsearch", "li_7d", "li_bulk", "jobs_scanner", "linkedin", "linkedin_page"].includes(value)) {
    return {
      label: "LinkedIn",
      color: "var(--terminal-green-bright)",
    };
  }
  if (value === "jsearch" || value === "google") {
    return {
      label: "Search",
      color: "var(--terminal-yellow)",
    };
  }
  return {
    label: "Other",
    color: "var(--muted-foreground)",
  };
}

type ColumnHandlers = {
  tracked: Set<string>;
  trackJob: (job: Job) => Promise<void>;
};

export function getColumns({ tracked, trackJob }: ColumnHandlers) {
  return [
    col.accessor("title", {
      header: "Title",
      size: 300,
      cell: (i) => (
        <div className="space-y-1">
          <span className="text-secondary-foreground text-xs font-medium leading-snug block">
            {i.getValue() ?? "—"}
          </span>
          {i.row.original.is_contract ? (
            <span className="inline-flex text-[10px] text-[var(--terminal-yellow)] border border-[var(--terminal-yellow)]/30 px-1.5 py-0.5">
              CONTRACT
            </span>
          ) : null}
        </div>
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
      size: 160,
      cell: (i) => (
        <span className="text-muted-foreground text-xs line-clamp-2">{i.getValue() ?? "—"}</span>
      ),
    }),
    col.accessor("final_score", {
      header: "Fit",
      size: 180,
      cell: (i) => <FitBucketCell job={i.row.original} />,
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
    col.accessor("site", {
      header: "Source",
      size: 110,
      cell: (i) => {
        const job = i.row.original;
        const tone = sourceTone(i.getValue(), job.is_direct_source);
        return (
          <div className="space-y-1">
            <span
              className="inline-flex border px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em]"
              style={{ color: tone.color, borderColor: `${tone.color}55` }}
            >
              {tone.label}
            </span>
            <div className="text-[10px] text-muted-foreground truncate">
              {formatSourceLabel(i.getValue())}
            </div>
          </div>
        );
      },
    }),
    col.accessor("date_posted", {
      header: "Age",
      size: 50,
      cell: (i) => {
        const job = i.row.original;
        const age = formatJobAge(i.getValue());
        if (age) return <span className="text-xs" style={{ color: age.color }}>{age.label}</span>;
        if (!job.freshness_bucket || job.freshness_bucket === "unknown") {
          return <span className="text-muted-foreground text-xs">—</span>;
        }
        const label = job.freshness_bucket === "fresh" ? "fresh" : job.freshness_bucket === "recent" ? "recent" : job.freshness_bucket;
        const color = job.freshness_bucket === "fresh"
          ? "var(--terminal-green-bright)"
          : job.freshness_bucket === "recent"
            ? "var(--terminal-yellow)"
            : "var(--muted-foreground)";
        return <span className="text-[11px]" style={{ color }}>{label}</span>;
      },
    }),
    col.display({
      id: "signals",
      header: "Signals",
      size: 220,
      cell: (i) => <SignalsCell job={i.row.original} />,
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
          <div className="flex items-center justify-end gap-1.5">
            {job.is_new_find ? (
              <span className="text-[10px] text-[var(--terminal-green-bright)] border border-[var(--terminal-green-bright)]/30 px-1.5 py-0.5 uppercase tracking-wider">
                new
              </span>
            ) : null}
            <button
              onClick={(e) => { e.stopPropagation(); trackJob(job); }}
              className="flex items-center gap-0.5 text-[11px] text-primary/60 border border-primary/20 px-1.5 py-0.5 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider"
            >
              <Plus size={8} />track
            </button>
          </div>
        );
      },
    }),
  ];
}
