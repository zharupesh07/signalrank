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
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Pages

| Route | Description |
|---|---|
| `/` | Landing / redirect |
| `/onboarding` | First-run resume upload + preference setup |
| `/jobs` | Ranked job feed — filters, page-size picker (50/100/200/All), sidebar detail |
| `/tracker` | Application tracker + recruiter CRM |
| `/dashboard` | Run history + score overview |
| `/runs` | Scraper run management |
| `/settings` | Profile, roles, locations, scoring preferences |

## Key Env Vars

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL (e.g. `http://localhost:8000`) |
| `NEXTAUTH_URL` | Frontend URL (e.g. `http://localhost:3000`) |
| `NEXTAUTH_SECRET` | Must match backend `NEXTAUTH_SECRET` |
