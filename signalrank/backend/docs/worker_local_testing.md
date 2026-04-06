# Worker Local Testing Guide

## Setup

All commands run from `signalrank/backend/`. Credentials are in `.env`.

The worker uses `DATABASE_URL_RAILWAY` (Railway public TCP proxy) which takes precedence over `DATABASE_URL`.

```bash
cd signalrank/backend
set -a && source .env && set +a
```

## Testing commands

### Verify worker imports and DB connectivity

```bash
uv run python -c "
from batch.worker_main import build_parser, resolve_db_url
import re, asyncio
from api.database import _build_engine

url = resolve_db_url()
print('DB URL:', re.sub(r':[^@]+@', ':***@', url))

async def ping():
    engine, _ = _build_engine(url)
    async with engine.connect() as conn:
        from sqlalchemy import text
        r = await conn.execute(text('SELECT COUNT(*) FROM runs'))
        print(f'runs table: {r.scalar()} rows')
    await engine.dispose()

asyncio.run(ping())
"
```

### Run worker (pick up any pending runs once, then exit)

```bash
uv run python -m batch.worker_main poll --once --scan-modes quick
```

For both quick and full:
```bash
uv run python -m batch.worker_main poll --once
```

### Continuous poll (like Railway deployment)

```bash
uv run python -m batch.worker_main poll
```

### Enqueue a cron run for all active profiles

```bash
uv run python -m batch.worker_main enqueue-cron
```

### Trigger a rank-only run (no scraping) via API

```bash
curl -X POST https://<api-url>/runs/trigger \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"disable_scraping": true}'
```

Then watch the worker pick it up:
```bash
uv run python -m batch.worker_main poll --once
```

## Findings (2026-04-06)

### Worker starts successfully

```
Worker loop started for mode=quick
[MEM] phase=worker_loop_started rss_mb=84.5
```

Memory at startup: ~85 MB RSS. The recent OOM (at 512MB Railway limit) was likely caused by the worker processing large embedding or ranking operations, not startup. Upgrading to 1GB should be sufficient.

### Root cause of recent deployment failure

**Missing DB migration** — `runs.lease_expires_at` did not exist in the Railway Postgres schema. The worker code (`batch/worker.py`) was querying this column in `_claim_pending_run` on every poll iteration, crashing immediately on startup.

**What happened:**
1. New code added worker lease columns to `api/models.py` (`claimed_by`, `claim_token`, `lease_expires_at`, `last_heartbeat_at`, `trigger_source`, `executor_type`)
2. No migration was generated or applied before deploying
3. Worker crashed with `UndefinedColumnError: column runs.lease_expires_at does not exist`

**Fix applied:**
- Discovered alembic version table was out of sync with actual DB state (DB had all tables applied but stamp was at `c1d2e3f4a5b6`)
- Stamped alembic at correct head (`4c9f1d2e3b4a`) 
- Generated and applied migration `4972000b8cc0_add_worker_lease_columns_to_runs`
- Migration adds: `claimed_by`, `claim_token`, `lease_expires_at`, `last_heartbeat_at`, `attempt_count`, `cancel_requested`, `trigger_source`, `executor_type` + composite index `ix_runs_claim`

### DB state (2026-04-06)

| Metric | Value |
|--------|-------|
| DB size | 432 MB |
| Total runs | 67 (42 failed, 22 success, 3 cancelled) |
| Worker RSS at startup | ~85 MB |
| Migration head | `4972000b8cc0` |

### Secondary issue: HNSW index disk failure

An earlier attempt to run `alembic upgrade head` failed when migration `d2e3f4a5b6c7` tried to `CREATE INDEX CONCURRENTLY ... USING hnsw` — Railway's shared memory limit (`No space left on device`). The index was skipped. The migration was later applied but the index creation was dropped in the subsequent `4972000b8cc0` migration's upgrade path.

If ANN vector search is needed in the future, the HNSW index will need to be created after freeing DB disk space.

## Running migrations

Always use `DATABASE_URL_RAILWAY` for migrations against production:

```bash
DATABASE_URL="$DATABASE_URL_RAILWAY" uv run alembic upgrade head
DATABASE_URL="$DATABASE_URL_RAILWAY" uv run alembic current
```

To generate a new migration after model changes:
```bash
# DB must be at head first
DATABASE_URL="$DATABASE_URL_RAILWAY" uv run alembic revision --autogenerate -m "describe_change"
# Review the generated file in alembic/versions/ before applying
DATABASE_URL="$DATABASE_URL_RAILWAY" uv run alembic upgrade head
```
