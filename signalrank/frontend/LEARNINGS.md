# Frontend Learnings & Mistakes

## L-001 · API client types must match actual response shapes

**Symptom:** `filteredApps.filter is not a function` / `applications.filter is not a function`
**Root cause (two-part):**
1. `api.applications.list()` was typed as `Application[]` but the backend returns `{ applications: [...], total, page, limit }` — a paginated wrapper. TypeScript didn't catch this because the type annotation was just wrong.
2. The initial "fix" used `Array.isArray(r) ? r : []` which silently swallowed the real data, causing the tracker to show 0 items despite 156 existing.

**Correct fix:** Unwrap at the API client layer — one place, not at every call site:
```ts
list: (token) =>
  request<{ applications: Application[]; total: number }>("/api/applications", { token })
    .then((r) => r.applications),
```
**Rule:** When adding/changing a backend endpoint response shape, update `lib/api.ts` immediately. Never type an endpoint as `T[]` without verifying the actual JSON shape. When a "fix" makes data disappear, it masked the real problem — investigate the actual response shape first.

**Files fixed:** `lib/api.ts`

---

## L-006 · State must be cleared on logout, not just skipped

**Symptom:** After logout, pages show the previous user's data (empty-looking but with stale counts/values).
**Root cause:** Every `useEffect` guarded with `if (!token) return` — which skips loading, but never *clears* the existing state. State from the previous session persists until the next login refills it.
**Fix:** Explicitly reset state in the `!token` branch:
```ts
useEffect(() => {
  if (!token) {
    setItems([]);
    setStats(null);
    setLoading(false);
    return;
  }
  // ...load data
}, [token]);
```
**Files fixed:** `dashboard/page.tsx`, `analytics/page.tsx`, `tracker/page.tsx`, `jobs/page.tsx`
**Rule:** Every `useEffect` that loads data keyed to `token` must also clear that data when `token` is falsy.

---

## L-005 · Defensive guards that hide data are worse than crashes

**Symptom:** Tracker showed 0 applications after the "fix" for the `.filter` crash.
**Root cause:** `Array.isArray(r) ? r : []` silently swallowed a valid paginated object `{ applications: [...] }` and set state to `[]`. No error, no warning — just missing data.
**Rule:** A guard that silently drops data (`? r : []`) is worse than a crash — the crash tells you where the problem is. Prefer fixing the root cause (wrong type / wrong unwrap) over defensive fallbacks that hide it. If you must guard, log a warning.

---

## L-002 · `isRunActive` must cover all live run statuses

**Symptom:** "Refresh Jobs" / "New Run" button re-enables mid-run during `scraping` or `ranking` phases, allowing a second run to be queued.
**Root cause:** `isRunActive` only checked `pending | running`, not the full set of live statuses (`scraping`, `ranking`) that the backend also emits.
**Fix:**
```ts
const LIVE = ["pending", "running", "scraping", "ranking"];
const isRunActive = LIVE.includes(run?.status ?? "");
```
**Rule:** Keep the live-status set in one place (ideally a shared constant) and reuse it across all components that gate on run activity.

---

## L-003 · `colSpan` must match actual column count

**Symptom:** Empty-state row in runs table renders too narrow — only spans 6 of 7 columns.
**Root cause:** `colSpan` was set when the table had 6 columns; an "Actions" column was added later without updating the empty-state row.
**Rule:** When adding or removing table columns, search for all `colSpan` values in that table and update them.

---

## L-004 · Modal `onAdded` callbacks must refresh dependent UI

**Symptom:** Manually adding a job via `AddJobModal` doesn't update the dashboard job list until navigation.
**Root cause:** `onAdded` was a no-op comment `/* dashboard refreshes on next navigation */`.
**Fix:** Pass the actual refresh function: `onAdded={loadJobs}`.
**Rule:** Every modal/form that mutates data must call a refresh callback. Never leave `onAdded`/`onSaved`/`onComplete` as stubs in production code.
