# SignalRank

SignalRank is an AI-assisted job search command center. It ingests job listings
from public job boards and ATS pages, ranks them against a candidate profile,
tracks applications, and generates tailored resume PDFs for roles worth pursuing.

The project is designed to run locally first: your resume, preferences, job
tracker, and generated artifacts stay in your own Postgres database. Optional LLM
features use provider API keys that you supply at runtime.

## What It Does

- Builds a candidate profile from onboarding inputs and resume text
- Searches multiple sources: JobSpy, free job APIs, Google Jobs, and direct ATS
  pages for Greenhouse, Ashby, Lever, and Workday
- Scores jobs across semantic match, skills, seniority, company tier, recency,
  and location fit
- Tracks applications and recruiter contacts
- Generates Typst-based tailored resume PDFs from cached structured content
- Provides a Next.js frontend, FastAPI backend, and optional desktop wrapper

## Quick Start

Prerequisites:

- Python 3.11+
- Node.js 20+
- Docker
- uv
- Typst, if you want PDF generation

```bash
git clone https://github.com/<your-org>/signalrank.git
cd signalrank

./signalrank/setup.sh
```

Open the frontend at [http://localhost:3000](http://localhost:3000). The backend
runs on [http://localhost:8000](http://localhost:8000).

For manual setup and architecture details, see [signalrank/README.md](signalrank/README.md).

## Configuration

Copy the example env files and fill in local values:

```bash
cp signalrank/backend/.env.example signalrank/backend/.env
cp signalrank/frontend/.env.local.example signalrank/frontend/.env.local
```

Required backend values:

- `DATABASE_URL`
- `NEXTAUTH_SECRET`
- `OPENROUTER_API_KEY` for LLM-powered resume parsing and tailoring

Optional integrations:

- `RAPIDAPI_KEY` for JSearch
- `HUNTER_API_KEY` for recruiter/contact enrichment

Never commit real `.env` files, API keys, resumes, or generated benchmark data.

## Repository Layout

```text
signalrank/
  backend/    FastAPI, workers, ranking, scraping, resume generation
  frontend/   Next.js app
  desktop/    Tauri desktop wrapper
  docs/       Product specs and design notes
```

## Open Source Notes

This public tree intentionally excludes private resumes, generated ranking
snapshots, local `.env` files, and personal job-search outputs. Use the example
fixtures under `signalrank/backend/data/` as templates for your own private data.

## License

MIT. See [LICENSE](LICENSE).
