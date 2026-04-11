"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { getCached, setCache } from "@/lib/cache";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import type { Job, Run } from "@/types";

export type Analytics = {
  score_distribution: { range: string; count: number }[];
  top_companies: { company: string; count: number }[];
  sites: { site: string; count: number }[];
  total: number;
};

const DASHBOARD_CACHE_KEYS = {
  jobs: "dash:jobs_response",
  analytics: "dash:analytics",
  tracked: "dash:tracked",
  onboarding: "dash:onboarding",
  run: "dash:run",
};

export function useDashboardData({
  token,
  toast,
}: {
  token: string;
  toast: (message: string, type?: "success" | "error" | "info") => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [newGoodMatches, setNewGoodMatches] = useState(0);
  const [onboardingComplete, setOnboardingComplete] = useState<boolean | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const cachedJobsResponse = getCached<{ jobs: Job[]; new_good_matches: number }>(
      DASHBOARD_CACHE_KEYS.jobs,
      600_000
    );
    if (cachedJobsResponse) {
      setJobs(cachedJobsResponse.jobs);
      setNewGoodMatches(cachedJobsResponse.new_good_matches);
    }
    const cachedRun = getCached<Run | null>(DASHBOARD_CACHE_KEYS.run, 600_000);
    if (cachedRun) setRun(cachedRun);
    const cachedAnalytics = getCached<Analytics>(DASHBOARD_CACHE_KEYS.analytics, 600_000);
    if (cachedAnalytics) setAnalytics(cachedAnalytics);
    const cachedTracked = getCached<string[]>(DASHBOARD_CACHE_KEYS.tracked, 600_000);
    if (cachedTracked) setTracked(new Set(cachedTracked));
    const cachedOnboarding = getCached<boolean>(DASHBOARD_CACHE_KEYS.onboarding, 600_000);
    if (cachedOnboarding != null) setOnboardingComplete(cachedOnboarding);
  }, [mounted]);

  const loadJobs = useCallback(async () => {
    if (!token) return;
    const response = await api.jobs.list(token, { page: 1, limit: 10 });
    setJobs(response.jobs);
    setNewGoodMatches(response.new_good_matches);
    setCache(DASHBOARD_CACHE_KEYS.jobs, {
      jobs: response.jobs,
      new_good_matches: response.new_good_matches,
    });
  }, [token]);

  const loadAnalytics = useCallback(async () => {
    if (!token) return;
    api.jobs.analytics(token).then((payload) => {
      setAnalytics(payload);
      setCache(DASHBOARD_CACHE_KEYS.analytics, payload);
    }).catch(() => null);
  }, [token]);

  const loadTracked = useCallback(async () => {
    if (!token) return;
    api.applications.trackedJobIds(token).then((ids) => {
      setTracked(new Set(ids));
      setCache(DASHBOARD_CACHE_KEYS.tracked, ids);
    }).catch(() => null);
  }, [token]);

  useEffect(() => {
    if (!token) {
      setJobs([]);
      setRun(null);
      setAnalytics(null);
      setTracked(new Set());
      setNewGoodMatches(0);
      setLoading(false);
      return;
    }
    setLoading(false);
    void api.runs.latest(token).then((latest) => {
      setRun(latest);
      setCache(DASHBOARD_CACHE_KEYS.run, latest);
      if (latest.jobs_snapshot) {
        setJobs(latest.jobs_snapshot.jobs);
        setNewGoodMatches(latest.jobs_snapshot.new_good_matches);
        setCache(DASHBOARD_CACHE_KEYS.jobs, {
          jobs: latest.jobs_snapshot.jobs,
          new_good_matches: latest.jobs_snapshot.new_good_matches,
        });
      }
    }).catch(() => {
      toast("Failed to load latest run", "error");
    });
    void loadJobs().catch(() => {
      toast("Failed to load jobs", "error");
    });
    void loadAnalytics();
    void loadTracked();
    void api.profile.get(token).then((profile) => {
      setOnboardingComplete(profile.onboarding_complete);
      setCache(DASHBOARD_CACHE_KEYS.onboarding, profile.onboarding_complete);
    }).catch(() => null);
  }, [token, loadAnalytics, loadJobs, loadTracked, toast]);

  const triggerRun = useCallback(async () => {
    setTriggering(true);
    const optimisticRun = makeQueuedRun(`local-${Date.now()}`);
    setRun(optimisticRun);
    try {
      const response = await api.runs.trigger(token);
      const queuedRun = makeQueuedRun(response.run_id);
      setRun(queuedRun);
      upsertRunCaches(queuedRun);
      toast("Job refresh queued", "info");
    } catch (err) {
      setRun((current) => (current?.id === optimisticRun.id ? null : current));
      toast(err instanceof Error ? err.message : "Failed to trigger run", "error");
    } finally {
      setTriggering(false);
    }
  }, [token, toast]);

  const trackJob = useCallback(async (job: Job) => {
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
  }, [token, toast]);

  const handleRunComplete = useCallback(async (completed: Run) => {
    setRun(completed);
    upsertRunCaches(completed);
    setTracked((prev) => new Set(prev));
    const jobsResponse = token ? await api.jobs.list(token, { page: 1, limit: 10 }) : null;
    if (jobsResponse) {
      setJobs(jobsResponse.jobs);
      setNewGoodMatches(jobsResponse.new_good_matches);
      setCache(DASHBOARD_CACHE_KEYS.jobs, {
        jobs: jobsResponse.jobs,
        new_good_matches: jobsResponse.new_good_matches,
      });
    }
    if (token) {
      await loadTracked();
    }
    await loadAnalytics();
    if (completed.status === "done" && jobsResponse?.new_good_matches) {
      toast(`${jobsResponse.new_good_matches} new good matches are ready to review`, "success");
    }
  }, [loadAnalytics, loadTracked, token, toast]);

  return {
    analytics,
    handleRunComplete,
    jobs,
    loadJobs,
    loading,
    mounted,
    newGoodMatches,
    onboardingComplete,
    run,
    setRun,
    tracked,
    trackJob,
    triggering,
    triggerRun,
  };
}
