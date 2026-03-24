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

## Environment Variables

```bash
# Required
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank
NEXTAUTH_SECRET=<generate with: openssl rand -base64 32>
OPENROUTER_API_KEY=sk-or-v1-...

# Optional
RAPIDAPI_KEY=                     # JSearch API — extra job sources
ALLOWED_ORIGINS=http://localhost:3000
SCRAPER_MAX_RESULTS=1000
SCRAPER_HOURS_OLD=720             # 30-day lookback
SCRAPER_DEFAULT_COUNTRY=India
LINKEDIN_MAX_QUERIES=0            # 0 = disabled (slow: ~80s/query)
```

`NEXTAUTH_SECRET` must match the frontend value exactly. Generate with `openssl rand -base64 32`.

## Project Structure

```
api/
  main.py              # FastAPI app + background worker startup
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
  resume_parser.py     # Extract structured profile from resume text
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

- `CONCURRENCY = 3` — 3 tasks per poll cycle, semaphore-throttled
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
