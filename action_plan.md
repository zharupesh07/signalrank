# Action Plan: Improve Job Visibility Across Runs

## Goal: Increase visibility of all historical jobs, not just the most recent run, in the SignalRank dashboard.

## Problem: Users perceive job loss when filtering by tier because the latest run lacks tier labels, creating a gap in filtered views.

## Solution: Modify the job retrieval logic to include all runs when filters are applied, not just the latest run.

## Steps:

1. **Identify the current logic** in `/signalrank/backend/api/routes/jobs.py` (or equivalent) that fetjobs for the `/jobs` endpoint.
2. **Locate the run selection logic** – likely a call to `_get_latest_success_run(user_id)`.
3. **Modify the function** to accept an optional parameter `include_all_runs=False`.
4. **When `tiers` filter is active**, call a new helper `_get_runs_with_tier_data(user_id)` that returns runs where at least one job has non-null tier.
5. **Modify the job query** to fetch results from all runs returned by the helper, not just the latest.
6. **Update the frontend