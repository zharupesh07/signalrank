# SignalRank Frontend

Next.js 16 (App Router) frontend for SignalRank.

## Stack

- **Framework**: Next.js 16 (App Router, Turbopack)
- **Language**: TypeScript
- **Styling**: Tailwind CSS v4
- **Components**: shadcn/ui + Base UI
- **Auth**: NextAuth.js
- **Tables**: TanStack Table

## Setup

```bash
npm install
cp .env.local.example .env.local
# Edit .env.local: NEXTAUTH_URL, NEXTAUTH_SECRET, NEXT_PUBLIC_API_URL
# Optional for server-side auth/API calls: API_URL_SERVER, API_REQUEST_TIMEOUT_MS
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Pages

| Route | Description |
|---|---|
| `/` | Landing / redirect |
| `/onboarding` | First-run resume upload + auto-inferred role/location/preferences review |
| `/jobs` | Ranked job feed — filters, page-size picker (50/100/200/All), sidebar detail |
| `/tracker` | Application tracker + recruiter CRM; "+ Add Job" button to ingest via URL or paste |
| `/dashboard` | Run history + score overview; "+ Add Job" button to ingest via URL or paste |
| `/runs` | Scraper run management |
| `/settings` | Profile, roles, locations, scoring preferences |

The onboarding UI loads role/location options from the backend taxonomy, polls `/api/onboarding/parsed` after resume upload, and lets the user accept or override the resume-derived prefill before the first run is triggered.

## Key Env Vars

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL (e.g. `http://localhost:8000`) |
| `API_URL_SERVER` | Optional server-side backend URL for NextAuth/server fetches. Use this when the browser and Next.js server should reach the backend differently. |
| `NEXTAUTH_URL` | Frontend URL (e.g. `http://localhost:3000`) |
| `NEXTAUTH_SECRET` | Must match backend `NEXTAUTH_SECRET` |
| `API_REQUEST_TIMEOUT_MS` | Optional server-side request timeout in ms. Defaults to `20000`. |
| `NEXT_PUBLIC_API_REQUEST_TIMEOUT_MS` | Optional browser request timeout in ms. Defaults to `15000`. |
