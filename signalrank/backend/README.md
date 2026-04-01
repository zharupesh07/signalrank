# SignalRank Backend

FastAPI + PostgreSQL backend for SignalRank.

## Stack

- **API**: FastAPI + Uvicorn
- **ORM**: SQLAlchemy 2 async + asyncpg
- **DB**: PostgreSQL 16 + pgvector
- **Migrations**: Alembic
- **Embeddings**: `sentence-transformers` (all-MiniLM-L6-v2, dim=384)
- **LLM**: OpenRouter (free-tier models with fallback)
- **PDF**: Typst + Jinja2 templates
- **Package manager**: uv

## Setup

```bash
uv sync
cp .env.example .env
# Edit .env — see Environment Variables section below
uv run alembic upgrade head
uv run uvicorn api.main:app --port 8000 --reload
```

`api.main` now reads runtime worker flags directly from the environment. In practice that means the API process can run "API-only" with background workers disabled, while `api.worker_main` can run queue/resume/archival workers as a separate process.

## Low-Memory Railway Profile

For a small deployment, start from:

```bash
cp .env.railway-low-memory.example .env
```

Recommended split:

- API service:
  - `RUN_API_WORKER=false`
  - `RUN_RESUME_WORKER=false`
  - `RUN_ARCHIVAL_WORKER=false`
- Worker service:
  - `RUN_API_WORKER=true`
  - `RUN_RESUME_WORKER=true`
  - `RUN_ARCHIVAL_WORKER=true`
  - `RESUME_WORKER_CONCURRENCY=1`
  - `ARCHIVAL_WORKER_CONCURRENCY=1`

### Railway Service Config Files

Use separate config-as-code files per Railway service:

- API service config path: `/signalrank/backend/railway.api.toml`
- Worker service config path: `/signalrank/backend/railway.worker.toml`

Commands defined there:

- API service: `uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}`
- Worker service: `python -m api.worker_main`

The older [railway.toml](/Users/examplecandidate/Projects/job_ranker/signalrank/backend/railway.toml) is kept as a legacy default. For a split API/worker deployment, point each Railway service at its dedicated config file instead of sharing the same one.

This matches the runtime defaults in code:

- `uvicorn api.main:app ...` defaults worker flags to `false` unless you explicitly set `RUN_*`.
- `uv run python -m api.worker_main` defaults queue/resume/archival workers to `true`.

Measured locally after the memory pass:

- API import, workers disabled: about `105 MB`
- Worker-like process after ranker import: about `108 MB`
- Worker-like process during embedding inference: about `385 MB`

The older `DB_POOL_SIZE=2` / `DB_MAX_OVERFLOW=1` profile is too small for normal authenticated page loads. The frontend routinely issues several requests in parallel, and an active scrape can briefly need extra checkouts for progress updates and batch writes. Use a `5/5` pool as the baseline unless you have a stricter database connection cap.

For Railway, prefer a private database endpoint for backend runtime traffic. The backend now honors `DATABASE_PRIVATE_URL` first and falls back to `DATABASE_URL`. Keep any public DB URL in `DATABASE_PUBLIC_URL` only for local tools or external clients, not service-to-database runtime traffic.

## Environment Variables

```bash
# Required
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank
NEXTAUTH_SECRET=<generate with: openssl rand -base64 32>
OPENROUTER_API_KEY=sk-or-v1-...

# Optional
DATABASE_PRIVATE_URL=             # Preferred runtime DB URL on Railway/private networking
DATABASE_PUBLIC_URL=              # Public DB URL for manual/external access only
DATABASE_URL_RAILWAY=             # Optional alternate DB used by the dev-only DB switcher
RAPIDAPI_KEY=                     # JSearch API — extra job sources
HUNTER_API_KEY=                   # Optional recruiter/contact enrichment integrations
ALLOWED_ORIGINS=http://localhost:3000
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=30
SCRAPER_MAX_RESULTS=1500
SCRAPER_HOURS_OLD=720             # 30-day lookback
SCRAPER_DEFAULT_COUNTRY=India
LINKEDIN_MAX_QUERIES=0            # 0 = disabled (slow: ~80s/query)
RANKER_MAX_CANDIDATES=2000
RANKER_MAX_DESCRIPTION_CHARS=1200
RUN_API_WORKER=false              # API entrypoint default
RUN_RESUME_WORKER=false           # API entrypoint default
RUN_ARCHIVAL_WORKER=false         # API entrypoint default
RUN_BOOT_SCAN=false
RUN_BOOT_EMBED=false
RESUME_WORKER_CONCURRENCY=1
ARCHIVAL_WORKER_CONCURRENCY=1
```

`NEXTAUTH_SECRET` must match the frontend value exactly. Generate with `openssl rand -base64 32`.

## Project Structure

```
api/
  main.py              # FastAPI app + background worker startup
  worker_main.py       # Dedicated worker entrypoint for queue/resume/archival tasks
  models.py            # SQLAlchemy ORM models
  database.py          # Async engine + session factory
  deps.py              # Auth dependencies
  routes/              # auth, jobs, profile, runs, tracker, resume, onboarding, ingest
batch/
  worker.py            # Scrape + rank queue processor
  resume_worker.py     # Background resume/email generation worker
  scraper.py           # Orchestrates all scraping sources
  ranker.py            # Scores all jobs for a user
  query_builder.py     # Builds search queries from profile
  sources/             # jobspy, rapidapi, free_apis, google_jobs
domain/
  additive_scoring.py  # 0-100 composite score
  company.py           # Tier taxonomy + lookup
  embeddings.py        # Embedding cache + cosine sim
  skills.py            # Skills matching
llm/
  openrouter.py        # LLM client: semaphore, retry, model fallback
  resume_parser.py     # Extract structured profile from resume text and normalize supported roles/locations
  resume_tailor.py     # Tailor resume JSON + compile Typst PDF
  email_generator.py   # Cold outreach email generation
templates/resume/      # Jinja2+Typst templates (classic, modern, minimal)
data/fonts/            # Roboto + FontAwesome for Typst PDF rendering
config/base.yaml       # Scoring weights, tier lists, blocklists
alembic/versions/      # DB migrations
```

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login, get JWT |
| GET | `/api/jobs` | Ranked job feed (filterable) |
| POST | `/api/runs/trigger` | Start scrape + rank run |
| GET | `/api/applications` | Application tracker |
| POST | `/api/resume/tailor` | Tailor resume for a job (LLM) |
| GET | `/api/resume/tailor/{job_id}` | Download tailored PDF |
| POST | `/api/resume/email` | Generate cold email |
| POST | `/api/resume/regenerate-all` | Re-generate all cached resumes |
| POST | `/api/jobs/ingest` | Extract job metadata from URL or raw text (no DB write) |
| POST | `/api/jobs/ingest/confirm` | Save extracted job to tracker as "interested" |

## Rate Limiting & Retry

### LLM (OpenRouter)

- `asyncio.Semaphore(3)` — max 3 concurrent LLM calls
- Per-model retry: `MAX_RETRIES_PER_MODEL = 3`
- 429 backoff: respects `Retry-After` header; fallback `min(2^(n+2), 60) + jitter(0.5–3.0s)`
- Model health probe on startup (TTL 1h); unhealthy models auto-skipped
- Default models: `arcee-ai/trinity-mini:free` (14s) → `arcee-ai/trinity-large-preview:free` (72s)

### Resume Worker

- `CONCURRENCY = 1` by default for low-memory deployment
- Failed tasks retry up to `MAX_TASK_RETRIES = 3` with exponential backoff via `next_retry_at`
- After max retries: status → `failed`
- Existing rows updated in-place (never duplicate INSERT)

### Scraping

- Free APIs (Remotive, Himalayas, Jobicy): 1s inter-request delay per fetcher call
- LinkedIn: sequential with `LINKEDIN_MAX_QUERIES=0` default

## Running Tests

```bash
# Requires a running signalrank_test database:
# docker exec signalrank-pg psql -U postgres -c "CREATE DATABASE signalrank_test;"

uv run pytest
```
