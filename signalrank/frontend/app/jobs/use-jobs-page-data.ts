"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { Job, JobFeedbackRequest, JobPreferencesResponse, Run } from "@/types";

import {
  DEFAULT_FILTERS,
  JOB_PRESETS,
  getApiSort,
  type Filters,
} from "./jobs-config";
function pickDefaultRunId(runs: Run[]) {
  return runs.length > 0 ? "all" : "";
}

export function useJobsPageData({
  token,
  isAdmin,
  toast,
}: {
  token: string;
  isAdmin: boolean;
  toast: (message: string, type?: "success" | "error" | "info") => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [runTotal, setRunTotal] = useState(0);
  const [newGoodMatches, setNewGoodMatches] = useState(0);
  const [availableSites, setAvailableSites] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState([{ id: "final_score", desc: true }]);
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
  const [preferences, setPreferences] = useState<JobPreferencesResponse | null>(null);
  const [feedbackInput, setFeedbackInput] = useState("");
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [preferenceResetting, setPreferenceResetting] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("signalrank-sidebar-collapsed");
    if (saved == null) {
      setCollapsed(true);
      localStorage.setItem("signalrank-sidebar-collapsed", "true");
      return;
    }
    if (saved === "true") setCollapsed(true);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!token) {
      setTracked(new Set());
      return;
    }
    api.applications.trackedJobIds(token).then((ids) => {
      setTracked(new Set(ids));
    }).catch(() => null);
  }, [token]);

  useEffect(() => {
    if (!token) {
      setJobs([]);
      setTotal(0);
      setRunTotal(0);
      setNewGoodMatches(0);
      setAvailableSites([]);
      setPreferences(null);
      setRuns([]);
      setSelectedRunId("");
      setRunsLoaded(false);
      setLoading(false);
      return;
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setRunsLoaded(false);
    api.runs
      .list(token)
      .then((items) => {
        if (cancelled) return;
        setRuns(items);
        setSelectedRunId((current) => {
          if (current === "all") return current;
          if (current && items.some((run) => run.id === current)) return current;
          return pickDefaultRunId(items);
        });
      })
      .catch(() => {
        if (cancelled) return;
        setRuns([]);
        setSelectedRunId("");
      })
      .finally(() => {
        if (!cancelled) setRunsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    setPage(1);
    setSelectedJob(null);
  }, [selectedRunId]);

  const applyJobsPayload = useCallback((response: { jobs: Job[]; total: number; run_total: number; new_good_matches: number; available_sites: string[] }) => {
    setJobs(response.jobs);
    setTotal(response.total);
    setRunTotal(response.run_total);
    setNewGoodMatches(response.new_good_matches);
    setAvailableSites(response.available_sites);
    setSelectedJob((current) => {
      if (!current) return null;
      const updated = response.jobs.find((job) => job.id === current.id);
      return updated ? { ...current, ...updated } : current;
    });
  }, []);

  const applyPreferences = useCallback((response: JobPreferencesResponse) => {
    setPreferences(response);
  }, []);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, filters, showArchived, pageSize, sorting]);

  const getFeedbackRequestBase = useCallback((): JobFeedbackRequest => {
    const { sort, sortDir } = getApiSort(sorting);
    return {
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
    };
  }, [debouncedSearch, filters, page, pageSize, showArchived, sorting]);

  const loadJobs = useCallback(async () => {
    if (!token) return;
    if (!runsLoaded) return;
    if (!selectedRunId) {
      setJobs([]);
      setTotal(0);
      setRunTotal(0);
      setNewGoodMatches(0);
      setAvailableSites([]);
      setLoading(false);
      setRefreshing(false);
      return;
    }
    const hasJobs = jobs.length > 0;
    if (hasJobs) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const { sort, sortDir } = getApiSort(sorting);
      const response = await api.jobs.list(token, {
        runId: selectedRunId || undefined,
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
      applyJobsPayload(response);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, page, pageSize, debouncedSearch, showArchived, filters, sorting, jobs.length, applyJobsPayload, selectedRunId, runsLoaded]);

  const loadPreferences = useCallback(async () => {
    if (!token) return;
    const response = await api.jobs.preferences(token);
    applyPreferences(response);
  }, [token, applyPreferences]);

  useEffect(() => {
    loadJobs().catch(() => {
      toast("Failed to load jobs", "error");
    });
  }, [loadJobs, toast]);

  useEffect(() => {
    loadPreferences().catch(() => null);
  }, [loadPreferences]);

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

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("signalrank-sidebar-collapsed", String(next));
      return next;
    });
  }, []);

  const applyPreset = useCallback((key: string) => {
    const preset = JOB_PRESETS.find((item) => item.key === key);
    if (!preset) return;
    const next = preset.apply();
    setFilters(next.filters);
    setSearch(next.search);
    setDebouncedSearch(next.search);
    setSorting(next.sorting);
    setShowArchived(next.showArchived);
    setPage(1);
  }, []);

  const resetView = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setSearch("");
    setDebouncedSearch("");
    setShowArchived(true);
    setSorting([{ id: "final_score", desc: true }]);
    setPage(1);
  }, []);

  const trackJob = useCallback(async (job: Job) => {
    try {
      await api.applications.create(token, {
        job_id: job.id,
        company: job.company,
        title: job.title,
        status: "interested",
        system_score: job.final_score,
        resume_match_pct: job.semantic_score,
      });
      setTracked((prev) => new Set(prev).add(job.id));
      if (job.is_new_find && (job.final_score ?? 0) >= 0.7) {
        setNewGoodMatches((prev) => Math.max(0, prev - 1));
      }
      toast("Added to tracker", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      if (message.startsWith("409")) {
        setTracked((prev) => new Set(prev).add(job.id));
        if (job.is_new_find && (job.final_score ?? 0) >= 0.7) {
          setNewGoodMatches((prev) => Math.max(0, prev - 1));
        }
        toast("Already tracked", "info");
      } else {
        toast(message || "Failed to track job", "error");
      }
    }
  }, [token, toast]);

  const pollArchiveStatus = useCallback(() => {
    if (!isAdmin) return;
    let delay = 5000;
    const maxDelay = 60000;
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
          delay = Math.min(delay * multiplier, maxDelay);
          schedule();
        } catch {
          clearTimeout(timeoutRef.current);
        }
      }, document.hidden ? Math.max(delay, 15000) : delay);
    }

    schedule();
  }, [isAdmin, token, loadJobs]);

  const triggerArchive = useCallback(async () => {
    if (!isAdmin) return;
    setArchiving(true);
    try {
      const response = await api.jobs.archiveUnsuitable(token);
      toast(`Queued ${response.queued} jobs for evaluation`, "success");
      pollArchiveStatus();
    } catch {
      toast("Failed to start archival", "error");
    } finally {
      setArchiving(false);
    }
  }, [isAdmin, pollArchiveStatus, toast, token]);

  const submitFeedback = useCallback(async ({
    feedbackText,
    quickActions = [],
    jobIds = [],
    sessionIntent,
  }: {
    feedbackText?: string;
    quickActions?: string[];
    jobIds?: string[];
    sessionIntent?: string;
  }) => {
    if (!token) return;
    const trimmed = feedbackText?.trim() ?? "";
    if (!trimmed && quickActions.length === 0) return;
    setFeedbackSubmitting(true);
    try {
      const response = await api.jobs.feedback(token, {
        runId: selectedRunId || undefined,
        ...getFeedbackRequestBase(),
        feedbackText: trimmed || undefined,
        quickActions,
        jobIds,
        sessionIntent,
      });
      applyPreferences(response.preferences);
      applyJobsPayload(response.jobs_payload);
      if (trimmed) setFeedbackInput("");
      toast("Preferences updated", "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to refine jobs";
      toast(message, "error");
    } finally {
      setFeedbackSubmitting(false);
    }
  }, [token, getFeedbackRequestBase, applyPreferences, applyJobsPayload, toast, selectedRunId]);

  const resetPreferences = useCallback(async (categories: string[] = []) => {
    if (!token) return;
    setPreferenceResetting(true);
    try {
      const response = await api.jobs.resetPreferences(token, {
        clearAll: categories.length === 0,
        categories,
      });
      applyPreferences(response);
      await loadJobs();
      toast(categories.length === 0 ? "Preference memory cleared" : "Preference filters reset", "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to reset preferences";
      toast(message, "error");
    } finally {
      setPreferenceResetting(false);
    }
  }, [token, applyPreferences, loadJobs, toast]);

  useEffect(() => {
    if (!token || !isAdmin) {
      setArchiveStatus(null);
      return;
    }
    api.jobs.archiveStatus(token).then((status) => {
      setArchiveStatus(status);
      if (status.pending > 0 || status.running > 0) pollArchiveStatus();
    }).catch(() => null);
  }, [token, isAdmin, pollArchiveStatus]);

  const totalPages = useMemo(() => Math.ceil(total / pageSize) || 1, [total, pageSize]);

  return {
    applyPreset,
    archiveStatus,
    archiving,
    availableSites,
    collapsed,
    debouncedSearch,
    filters,
    feedbackInput,
    feedbackSubmitting,
    jobs,
    loadJobs,
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
  };
}
