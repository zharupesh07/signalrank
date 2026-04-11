"use client";

import { ChevronLeft, ChevronRight, ExternalLink, Plus, SlidersHorizontal, XCircle } from "lucide-react";

import { scoreColor } from "@/lib/formatting";
import type { Job } from "@/types";

import {
  DEFAULT_FILTERS,
  TIERS,
  TIER_DESCRIPTIONS,
  toggleItem,
  type Filters,
} from "./jobs-config";
import { TIER_COLORS } from "./columns";

export function JobsHeader({
  total,
  runTotal,
  activeFilterCount,
  newGoodMatches,
}: {
  total: number;
  runTotal: number;
  activeFilterCount: number;
  newGoodMatches: number;
}) {
  return (
    <div>
      <div className="section-label mb-1">match explorer</div>
      <div className="flex items-baseline gap-3">
        <h1 className="text-xl font-bold text-foreground">All Matches</h1>
        <span className="text-primary text-sm tabular-nums text-glow-dim">{total}</span>
        {activeFilterCount > 0 && (
          <span className="text-[11px] text-muted-foreground">of {runTotal}</span>
        )}
      </div>
      {newGoodMatches > 0 && (
        <div className="mt-2 inline-flex items-center gap-2 border border-[var(--terminal-green-bright)]/25 bg-[var(--terminal-green-bright)]/8 px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] text-[var(--terminal-green-bright)]">
          <span className="tabular-nums font-bold">{newGoodMatches}</span>
          <span>new good matches ready to review</span>
        </div>
      )}
    </div>
  );
}

export function JobsPresetBar({
  activeFilterCount,
  collapsed,
  search,
  showArchived,
  onToggleCollapsed,
  onApplyPreset,
  onResetView,
  presets,
}: {
  activeFilterCount: number;
  collapsed: boolean;
  search: string;
  showArchived: boolean;
  onToggleCollapsed: () => void;
  onApplyPreset: (key: string) => void;
  onResetView: () => void;
  presets: { key: string; label: string }[];
}) {
  return (
    <div className="border border-border bg-card p-4 mb-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Quick views</div>
          <div className="text-sm text-muted-foreground mt-1">Start with a preset, then open advanced filters only if you need to narrow further.</div>
        </div>
        <button
          onClick={onToggleCollapsed}
          className="inline-flex items-center gap-1.5 text-[11px] border border-border px-3 py-2 hover:border-primary hover:text-primary transition-colors uppercase tracking-wider"
        >
          <SlidersHorizontal size={11} />
          {collapsed ? "Show Advanced Filters" : "Hide Advanced Filters"}
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {presets.map((preset) => (
          <button
            key={preset.key}
            onClick={() => onApplyPreset(preset.key)}
            className="text-[11px] px-3 py-1.5 border border-border text-muted-foreground hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors uppercase tracking-wider"
          >
            {preset.label}
          </button>
        ))}
        {activeFilterCount > 0 || search || !showArchived ? (
          <button
            onClick={onResetView}
            className="text-[11px] px-3 py-1.5 border border-primary/30 text-primary hover:bg-primary hover:text-background transition-colors uppercase tracking-wider"
          >
            Reset View
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function JobsFiltersSidebar({
  collapsed,
  activeFilterCount,
  filters,
  availableSites,
  showArchived,
  onToggleCollapsed,
  onSetFilters,
  onSetShowArchived,
}: {
  collapsed: boolean;
  activeFilterCount: number;
  filters: Filters;
  availableSites: string[];
  showArchived: boolean;
  onToggleCollapsed: () => void;
  onSetFilters: React.Dispatch<React.SetStateAction<Filters>>;
  onSetShowArchived: React.Dispatch<React.SetStateAction<boolean>>;
}) {
  return (
    <aside
      className="hidden md:block shrink-0 sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto"
      style={{ width: collapsed ? 40 : 220 }}
    >
      {collapsed ? (
        <button
          onClick={onToggleCollapsed}
          className="flex flex-col items-center gap-1 w-full pt-3 text-muted-foreground hover:text-primary transition-colors"
          title={`Advanced filters${activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}`}
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
            <span className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide">Advanced Filters</span>
            <button
              onClick={onToggleCollapsed}
              className="text-muted-foreground hover:text-primary transition-colors"
              title="Collapse"
            >
              <ChevronLeft size={13} />
            </button>
          </div>

          {activeFilterCount > 0 && (
            <button
              onClick={() => onSetFilters(DEFAULT_FILTERS)}
              className="text-xs text-primary hover:underline"
            >
              Reset filters ({activeFilterCount})
            </button>
          )}

          <div>
            <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">
              Min Score <span className="tabular-nums text-secondary-foreground normal-case font-normal">{filters.minScore}</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={filters.minScore}
              onChange={(e) => onSetFilters((f) => ({ ...f, minScore: Number(e.target.value) }))}
              suppressHydrationWarning
              className="w-full accent-primary"
            />
          </div>

          <hr className="border-border" />

          <div>
            <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Job Type</div>
            <div className="flex gap-1">
              {(["all", "fte", "contract"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => onSetFilters((f) => ({ ...f, jobType: t }))}
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

          <div>
            <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Tier</div>
            <div className="space-y-1">
              {TIERS.map((tier) => (
                <label key={tier.value || "unknown"} className="flex items-center gap-2 cursor-pointer" title={TIER_DESCRIPTIONS[tier.value] ?? tier.label}>
                  <input
                    type="checkbox"
                    checked={filters.tiers.includes(tier.value)}
                    onChange={() => onSetFilters((f) => ({ ...f, tiers: toggleItem(f.tiers, tier.value) }))}
                    suppressHydrationWarning
                    className="accent-[#22c55e] w-3 h-3"
                  />
                  <span className="text-sm text-foreground">{tier.label}</span>
                </label>
              ))}
            </div>
          </div>

          <hr className="border-border" />

          <div>
            <div className="text-xs font-semibold text-[var(--fg-muted,#71717a)] uppercase tracking-wide mb-2">Date Posted</div>
            <select
              value={filters.dateRange}
              onChange={(e) => onSetFilters((f) => ({ ...f, dateRange: e.target.value as Filters["dateRange"] }))}
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
                        onChange={() => onSetFilters((f) => ({ ...f, sites: toggleItem(f.sites, site) }))}
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

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={() => onSetShowArchived((v) => !v)}
              suppressHydrationWarning
              className="accent-[#22c55e] w-3 h-3"
            />
            <span className="text-xs text-foreground">Show archived</span>
          </label>
        </div>
      )}
    </aside>
  );
}

export function JobsPagination({
  total,
  page,
  pageSize,
  totalPages,
  onSetPageSize,
  onSetPage,
}: {
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  onSetPageSize: (size: number) => void;
  onSetPage: React.Dispatch<React.SetStateAction<number>>;
}) {
  return (
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
              onClick={() => onSetPageSize(s)}
              className={`px-2 py-1 border transition-colors ${pageSize === s ? "border-primary text-primary font-semibold" : "border-muted-foreground/40 hover:border-primary hover:text-primary"}`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 font-mono">
          <button
            onClick={() => onSetPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 border border-muted-foreground/40 hover:border-primary hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            [&lt; prev]
          </button>
          <span className="px-2">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => onSetPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 border border-muted-foreground/40 hover:border-primary hover:text-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            [next &gt;]
          </button>
        </div>
      </div>
    </div>
  );
}

export function JobDetailPanel({
  selectedJob,
  tracked,
  selectedJobLoading,
  onClose,
  onTrack,
}: {
  selectedJob: Job;
  tracked: Set<string>;
  selectedJobLoading: boolean;
  onClose: () => void;
  onTrack: (job: Job) => void;
}) {
  return (
    <div className="w-80 shrink-0 sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto border border-border bg-card space-y-4 p-4 z-40 relative">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs font-bold text-foreground leading-snug">{selectedJob.title}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{selectedJob.company}</div>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors shrink-0 mt-0.5">
          <XCircle size={14} />
        </button>
      </div>

      <div className="space-y-2">
        {[
          { label: "Overall", value: selectedJob.final_score },
          { label: "Title match", value: selectedJob.title_relevance_score },
          { label: "Resume match", value: selectedJob.semantic_score },
          { label: "Skills", value: selectedJob.skills_score },
          { label: "Company", value: selectedJob.company_score },
          { label: "Recency", value: selectedJob.recency_score },
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
            className="text-[10px] px-1.5 py-0.5 border cursor-help"
            title={TIER_DESCRIPTIONS[selectedJob.company_tier] ?? "Company tier"}
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
        {selectedJob.is_new_find && (
          <span className="text-[10px] text-[var(--terminal-green-bright)] border border-[var(--terminal-green-bright)]/30 px-1.5 py-0.5 uppercase tracking-wider">NEW FIND</span>
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
          <>
            {selectedJob.is_new_find && (
              <span className="text-[10px] text-[var(--terminal-green-bright)] border border-[var(--terminal-green-bright)]/30 px-1.5 py-1 uppercase tracking-wider">
                new
              </span>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onTrack(selectedJob);
              }}
              className="flex items-center gap-1 text-[11px] text-primary border border-primary/30 px-2 py-1 hover:bg-primary/10 transition-colors uppercase tracking-wider"
            >
              <Plus size={8} />track
            </button>
          </>
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
            {selectedJob.description.slice(0, 2000)}
            {selectedJob.description.length > 2000 ? "…" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
