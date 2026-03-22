# SignalRank

> AI-powered job discovery and ranking — surfaces roles that actually match your profile, not just keywords.

SignalRank scrapes job boards, embeds your resume, and ranks every listing against your skills, seniority, preferred companies, and location — so your job search feed looks like a curated shortlist, not a firehose.

---

## Architecture

```mermaid
flowchart TD
    subgraph Browser["Browser"]
        UI["Next.js 16 App Router\n(TypeScript + Tailwind + shadcn)"]
    end

    subgraph API["FastAPI Backend (Python 3.11)"]
        direction TB
        AUTH["Auth\n/api/auth"]
        PROFILE["Profile\n/api/profile"]
        JOBS["Jobs\n/api/jobs"]
        RUNS["Runs\n/api/runs"]
        TRACKER["Tracker\n/api/applications"]
        RESUME["Resume\n/api/resume"]
        ONBOARD["Onboarding\n/api/onboarding"]
    end

    subgraph Worker["Background Worker (asyncio)"]
        QUEUE["In-memory Queue"]
        SCRAPER["Scraper\nbatch/scraper.py"]
        RANKER["Ranker\nbatch/ranker.py"]

        subgraph Sources["Scraping Sources"]
            S1["JobSpy\n(Indeed + LinkedIn)"]
            S2["RapidAPI JSearch"]
            S3["Free APIs\n(Remotive, Himalayas, Jobicy)"]
            S4["Google Jobs"]
        end

        subgraph Scoring["Additive Scoring Engine"]
            SC1["Semantic Score\n(sentence-transformers)"]
            SC2["Skills Boost"]
            SC3["Company Tier\n(SS / S / A / B / C / D)"]
            SC4["Seniority Match"]
            SC5["Recency Score"]
            SC6["Location Score"]
        end
    end

    subgraph LLM["LLM Layer (OpenRouter)"]
        L1["Resume Parser"]
        L2["Onboarding Distill"]
        L3["Resume Tailor"]
    end

    subgraph DB["PostgreSQL + pgvector"]
        T1[("users\nprofiles")]
        T2[("jobs_raw")]
        T3[("job_results\nruns")]
        T4[("applications\nrecruiters")]
        T5[("embeddings\nllm_cache")]
    end

    UI -->|"JWT auth"| AUTH
    UI --> PROFILE
    UI --> JOBS
    UI --> RUNS
    UI --> TRACKER
    UI --> RESUME
    UI --> ONBOARD

    AUTH --> T1
    PROFILE --> T1
    JOBS --> T3
    RUNS --> QUEUE
    TRACKER --> T4
    RESUME --> L3
    ONBOARD --> L2

    QUEUE --> SCRAPER
    SCRAPER --> S1
    SCRAPER -->|"parallel"| S2
    SCRAPER -->|"parallel"| S3
    SCRAPER -->|"parallel"| S4
    S1 & S2 & S3 & S4 --> T2

    T2 --> RANKER
    RANKER --> SC1 & SC2 & SC3 & SC4 & SC5 & SC6
    SC1 --> T5
    RANKER --> T3

    L1 --> T1
    L2 --> T1
```

---

## Features

| Feature | Description |
|---|---|
| **Smart Ranking** | Additive 0-100 score: semantic similarity, skills, company tier, seniority, recency, location |
| **Company Tiers** | SS / S / A / B / C / D taxonomy across 80+ companies — score bonus for dream companies |
| **Job Tracker** | Track applications, add recruiter contacts, generate cold-email drafts |
| **Resume Tailoring** | LLM-powered resume tailoring per job via OpenRouter |
| **Onboarding** | Guided flow to distil resume → profile → preferences |
| **Dev Panel** | Hidden 5-click debug overlay: tweak roles, locations, scoring weights, trigger runs |
| **Multi-source Scraping** | Indeed + LinkedIn (JobSpy), RapidAPI JSearch, Remotive, Himalayas, Jobicy, Google Jobs |

---

## Tech Stack

### Backend
| Layer | Tech |
|---|---|
| API | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2 async + asyncpg |
| DB | PostgreSQL + pgvector |
| Migrations | Alembic |
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2) |
| LLM | OpenRouter (Claude / GPT-4o) |
| Scraping | python-jobspy, httpx, BeautifulSoup |
| Auth | JWT (python-jose + passlib) |
| Package manager | uv |

### Frontend
| Layer | Tech |
|---|---|
| Framework | Next.js 16 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS v4 |
| Components | shadcn/ui + Base UI |
| Auth | NextAuth.js |
| Tables | TanStack Table |

---

## Project Structure

```
signalrank/
├── backend/
│   ├── api/
│   │   ├── main.py            # FastAPI app + background worker startup
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   └── routes/            # auth, jobs, profile, runs, tracker, resume
│   ├── batch/
│   │   ├── worker.py          # Async job queue processor
│   │   ├── scraper.py         # Orchestrates all scraping sources
│   │   ├── ranker.py          # Scores all jobs for a user
│   │   ├── query_builder.py   # Builds search queries from profile
│   │   └── sources/           # jobspy, rapidapi, free_apis, google_jobs
│   ├── domain/
│   │   ├── additive_scoring.py  # 0-100 composite score
│   │   ├── company.py           # Tier taxonomy + lookup
│   │   ├── embeddings.py        # Embedding cache + cosine sim
│   │   └── ...                  # skills, recency, seniority, gates
│   ├── llm/
│   │   ├── openrouter.py      # LLM client + retry
│   │   ├── resume_parser.py   # Extract structured profile from resume
│   │   └── resume_tailor.py   # Tailor resume to job description
│   └── config/
│       └── base.yaml          # Scoring weights, tier lists, blocklists
└── frontend/
    ├── app/
    │   ├── dashboard/         # Run history + score overview
    │   ├── jobs/              # Ranked job feed with filters
    │   ├── tracker/           # Application tracker + recruiter CRM
    │   ├── settings/          # Profile, roles, locations
    │   └── onboarding/        # First-run setup
    └── components/
        ├── dev-panel.tsx      # Hidden developer overlay
        ├── chip-select.tsx    # Fast toggleable multiselect chips
        └── tag-input.tsx      # Autocomplete tag input
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 15+ with pgvector extension
- [uv](https://github.com/astral-sh/uv)

### Backend

```bash
cd signalrank/backend

# Install dependencies
uv sync

# Set environment variables
cp .env.example .env
# Edit .env: DATABASE_URL, NEXTAUTH_SECRET, OPENROUTER_API_KEY, RAPIDAPI_KEY (optional)

# Run migrations
uv run alembic upgrade head

# Start the server
uv run uvicorn api.main:app --port 8000
```

### Frontend

```bash
cd signalrank/frontend

npm install
cp .env.local.example .env.local
# Edit .env.local: NEXTAUTH_URL, NEXTAUTH_SECRET, NEXT_PUBLIC_API_URL

npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Scoring Model

Each job receives a **0–100 composite score** from six additive dimensions:

```
final_score = semantic_score × w1
            + skills_score  × w2
            + company_score × w3    ← tier_ss=100, tier_s=95, tier_a=80 …
            + seniority_score × w4
            + recency_score  × w5
            + location_score × w6
```

Weights are configured in `backend/config/base.yaml`. Jobs below the semantic floor (0.65 cosine similarity) are penalized regardless of other scores.

### Company Tier Reference

| Tier | Examples |
|---|---|
| **SS** | Google, Atlassian, Salesforce, Adobe, Intuit, LinkedIn, GitLab, Spotify |
| **S** | Microsoft, Snowflake, Databricks, OpenAI, Anthropic, Netflix, ServiceNow |
| **A** | Amazon, Uber, Flipkart, CRED, Razorpay, Palo Alto Networks, Stripe |
| **B** | Optum, Thoughtworks, Zomato, Freshworks, Zoho, Swiggy |
| **C** | John Deere, Bosch, LTIMindtree, Mphasis |
| **D** | Wipro, Infosys, TCS, HCL, Fractal, Deloitte |

---

## Scraping Architecture

```mermaid
sequenceDiagram
    participant UI as Frontend
    participant API as FastAPI
    participant Q as Worker Queue
    participant IN as JobSpy (Indeed)
    participant LI as JobSpy (LinkedIn)
    participant PA as Parallel Sources
    participant R as Ranker
    participant DB as PostgreSQL

    UI->>API: POST /api/runs/trigger
    API->>DB: INSERT run (status=pending)
    API->>Q: enqueue(run_id, user_id)
    API-->>UI: { run_id, status: "pending" }

    Q->>DB: UPDATE run status=scraping
    Q->>IN: search(queries, sequential, 30-day lookback)
    IN-->>DB: INSERT jobs_raw (batched, on conflict ignore)

    opt LINKEDIN_MAX_QUERIES > 0
        Q->>LI: search(queries[:N], sequential, 7-day lookback)
        LI-->>DB: INSERT jobs_raw
    end

    Q->>PA: search(queries, parallel)
    Note over PA: rapidapi + free_apis + google_jobs run concurrently
    PA-->>DB: INSERT jobs_raw

    Q->>R: score_jobs_for_user(resume, profile)
    R->>DB: SELECT jobs_raw + embeddings
    R->>DB: INSERT job_results (scored)
    Q->>DB: UPDATE run status=success

    UI->>API: GET /api/jobs?run_id=latest
    API-->>UI: ranked job list (score, tier, title, company)
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://user:pass@host/db` |
| `NEXTAUTH_SECRET` | Yes | Random 32+ char string |
| `OPENROUTER_API_KEY` | Yes | For resume parsing and tailoring |
| `RAPIDAPI_KEY` | No | JSearch API for additional job sources |
| `SCRAPER_MAX_RESULTS` | No | Results per query (default: 1000) |
| `SCRAPER_HOURS_OLD` | No | Job recency window in hours (default: 720 = 30 days) |
| `SCRAPER_DEFAULT_COUNTRY` | No | Default country for searches (default: India) |
| `LINKEDIN_MAX_QUERIES` | No | LinkedIn queries to run (default: 0 = disabled, slow ~80s/query) |
