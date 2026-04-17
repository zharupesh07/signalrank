# SignalRank Canonical Spec

## Summary

SignalRank is a focused multi-user beta product for job discovery and application tracking.

Canonical flow:

1. Upload a resume and complete onboarding
2. Refresh jobs for that user profile
3. Review ranked matches
4. Move strong jobs into the tracker
5. Use the tracker to manage application follow-through

The core product stays narrow at the surface. The system is hardened for authenticated multi-user isolation, DB-owned background execution, and small-beta operational reliability.

## Canonical Product Surfaces

- `/onboarding`
  - Upload resume
  - Review inferred profile inputs
  - Confirm profile and unlock refresh
- `/dashboard`
  - Lightweight command center
  - Show latest run, top matches, and next action
- `/jobs`
  - Primary decision workspace
  - Filter, sort, inspect, track, archive
- `/tracker`
  - Durable application workflow state
  - Canonical states: `interested`, `applied`, `interviewing`, `offer`, `rejected`, `archived`
- `/settings`
  - Profile, resume, roles, locations, and core search preferences

## Non-Core Features

These remain supported only as secondary capabilities and are not part of the canonical product promise:

- Recruiter enrichment
- Resume generation and tailoring
- Cold-email generation
- Internal profile-fresh and benchmarking tools
- Admin and debug controls

## Domain Boundaries

SignalRank has four primary domains:

- Identity and profile
- Run orchestration
- Job discovery and ranking
- Application tracking

Everything else is adjunct and must not block or distort the refresh-to-track path.

## Public API Contract

Canonical API families:

- `/api/auth`
- `/api/onboarding`
- `/api/profile`
- `/api/runs`
- `/api/jobs`
- `/api/applications`

Canonical run response fields:

- `id`
- `status`
- `started_at`
- `finished_at`
- `scrape_count`
- `ranked_count`
- `visible_count`
- `error`

Compatibility aliases may remain in responses while clients migrate, but new product code should treat the canonical fields as the source of truth.

## Multi-User Constraints

- Every user-owned query or mutation must be scoped by authenticated `user_id`
- Shared job corpus rows may remain global, but user workflow state must stay per-user
- The database is the source of truth for run claiming, recovery, and status
- A user may have at most one active refresh at a time by default
- Worker claim order must avoid one user monopolizing execution
- Expensive actions must have explicit per-user rate limits
- Admin behavior must stay explicitly role-gated and separate from ordinary user flows

## Operational Rules

- Refresh correctness must not depend on an in-memory API queue
- Workers claim runs from the database and recover stale leases
- LLM-backed features are optional enhancements, not core-path requirements
- Default deployment target is a small multi-user beta on API + worker + Postgres

## Acceptance Criteria

- A user cannot read or mutate another user’s runs, jobs, profile, or tracker entries
- A user with incomplete onboarding cannot trigger refresh
- A user sees only completed runs in jobs-history selection
- A refresh run always resolves to a terminal visible state
- The jobs page uses a typed run contract instead of route-specific payload assumptions
- Tracker state remains the durable workflow boundary after discovery
