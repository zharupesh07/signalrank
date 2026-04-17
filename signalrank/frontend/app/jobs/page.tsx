"use client";

import { useMemo } from "react";
import { useSession } from "next-auth/react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
} from "@tanstack/react-table";
import { getColumns } from "./columns";
import { useToast } from "@/components/toast";
import { TableRowSkeleton } from "@/components/skeleton";
import { ChevronUp, ChevronDown, Search, X, Archive, Loader2 } from "lucide-react";
import {
  JOB_PRESETS,
  countActiveFilters,
} from "./jobs-config";
import {
  JobDetailPanel,
  JobsFiltersSidebar,
  JobsHeader,
  JobsPagination,
  JobsPresetBar,
  JobsRunSelector,
  JobsRefinementPanel,
} from "./jobs-ui";
import { useJobsPageData } from "./use-jobs-page-data";

export default function JobsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const isAdmin = Boolean((session as { isAdmin?: boolean })?.isAdmin);
  const { toast } = useToast();
  const {
    applyPreset,
    archiveStatus,
    archiving,
    availableSites,
    collapsed,
    feedbackInput,
    feedbackSubmitting,
    filters,
    jobs,
    loading,
    newGoodMatches,
    page,
    pageSize,
    preferenceResetting,
    preferences,
    runs,
    refreshing,
    resetView,
    resetPreferences,
    selectedRunId,
    setSelectedRunId,
    runTotal,
    search,
    selectedJob,
    selectedJobLoading,
    setFeedbackInput,
    setFilters,
    setPage,
    setPageSize,
    setSearch,
    setSelectedJob,
    setShowArchived,
    setSorting,
    showArchived,
    sorting,
    toggleCollapsed,
    toggleSelectedJob,
    total,
    totalPages,
    tracked,
    trackJob,
    triggerArchive,
    submitFeedback,
  } = useJobsPageData({ token, isAdmin, toast });
  const activeFilterCount = countActiveFilters(filters);

  const columns = useMemo(
    () => getColumns({ tracked, trackJob }),
    [tracked, trackJob]
  );

  const table = useReactTable({
    data: jobs,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    manualSorting: true,
    getCoreRowModel: getCoreRowModel(),
  });


  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-end justify-between gap-4 mb-5">
          <JobsHeader
            total={total}
            runTotal={runTotal}
            activeFilterCount={activeFilterCount}
            newGoodMatches={newGoodMatches}
          />
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

        <JobsPresetBar
          activeFilterCount={activeFilterCount}
          collapsed={collapsed}
          search={search}
          showArchived={showArchived}
          onToggleCollapsed={toggleCollapsed}
          onApplyPreset={applyPreset}
          onResetView={resetView}
          presets={JOB_PRESETS.map(({ key, label }) => ({ key, label }))}
        />

        <JobsRunSelector
          runs={runs}
          selectedRunId={selectedRunId}
          onSelectRun={(runId) => {
            setSelectedRunId(runId);
            setPage(1);
          }}
        />

        <div className="flex gap-4">
          {/* Sidebar — hidden on mobile */}
          <JobsFiltersSidebar
            collapsed={collapsed}
            activeFilterCount={activeFilterCount}
            filters={filters}
            availableSites={availableSites}
            showArchived={showArchived}
            onToggleCollapsed={toggleCollapsed}
            onSetFilters={setFilters}
            onSetShowArchived={setShowArchived}
          />

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
                  <col style={{ width: 120 }} />
                  <col style={{ width: 60 }} />
                  <col style={{ width: 80 }} />
                  <col style={{ width: 70 }} />
                  <col style={{ width: 50 }} />
                  <col style={{ width: 220 }} />
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
                      <TableRowSkeleton key={i} cols={11} />
                    ))
                  ) : table.getRowModel().rows.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="px-4 py-16 text-center">
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
                          className="job-row-item border-b border-border bg-card row-fade-in"
                          style={{
                            animationDelay: `${Math.min(row.index * 20, 200)}ms`,
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

            <JobsPagination
              total={total}
              page={page}
              pageSize={pageSize}
              totalPages={totalPages}
              onSetPageSize={setPageSize}
              onSetPage={setPage}
            />
          </div>

          {/* Detail panel backdrop (click to close) */}
          {selectedJob && (
            <div className="fixed inset-0 z-30" onClick={() => setSelectedJob(null)} />
          )}

          {/* Detail panel */}
          {selectedJob && (
            <JobDetailPanel
              selectedJob={selectedJob}
              tracked={tracked}
              selectedJobLoading={selectedJobLoading}
              feedbackSubmitting={feedbackSubmitting}
              onClose={() => setSelectedJob(null)}
              onFeedback={(action, job) => {
                void submitFeedback({
                  quickActions: [action],
                  jobIds: [job.id],
                  sessionIntent: "job_detail_quick_feedback",
                });
              }}
              onTrack={(job) => {
                void trackJob(job);
              }}
            />
          )}
          </div>

          <JobsRefinementPanel
            preferences={preferences}
            feedbackInput={feedbackInput}
            feedbackSubmitting={feedbackSubmitting}
            resetting={preferenceResetting}
            onFeedbackInputChange={setFeedbackInput}
            onSubmitFeedback={() => {
              void submitFeedback({
                feedbackText: feedbackInput,
                sessionIntent: "jobs_chat_refinement",
              });
            }}
            onResetPreferences={() => {
              void resetPreferences();
            }}
          />
        </div>
      </div>
    </div>
  );
}
