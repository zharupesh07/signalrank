---
name: railway-postgres
description: Use when working with Railway-hosted PostgreSQL — connecting, running queries, migrations, dumping/restoring data, or configuring DATABASE_URL for local vs production use in this project (FastAPI + asyncpg + SQLAlchemy + Alembic stack).
---

# Railway PostgreSQL

Railway provisions a managed Postgres instance per service. This project uses it as the production DB.

## Connection Variables

Railway exposes two URL variants as environment variables:

| Variable | Use |
|---|---|
| `DATABASE_URL` | Internal — for Railway services talking to each other (fast, no SSL cert issues) |
| `DATABASE_PUBLIC_URL` | External — use from your laptop or CI |

Both are `postgresql://postgres:<password>@<host>:<port>/railway` format.

## Connecting from Local

```bash
# Get the public URL
railway variables | grep DATABASE_PUBLIC_URL

# Or run psql directly via Railway CLI
railway connect postgres

# Or use Docker psql with the public URL
DATABASE_PUBLIC_URL=$(railway variables --json | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")
docker run --rm -it postgres:16 psql "$DATABASE_PUBLIC_URL"
```

## asyncpg / SQLAlchemy URL Conversion

Railway gives `postgresql://...` but asyncpg needs `postgresql+asyncpg://`. Strip `?sslmode=...` if present and re-add explicitly:

```python
import os

raw = os.environ["DATABASE_URL"]  # or DATABASE_PUBLIC_URL locally
url = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
# Remove any trailing query params Railway may add
url = url.split("?")[0] + "?ssl=require"
```

In `sqlalchemy.ext.asyncio`:
```python
engine = create_async_engine(url, pool_size=5, max_overflow=10)
```

## SSL

Railway Postgres requires SSL. Use `sslmode=require` (not `verify-full` — Railway uses self-signed certs).

- asyncpg: add `ssl="require"` to connect args OR `?ssl=require` in URL
- psql: `psql "$DATABASE_PUBLIC_URL?sslmode=require"`

## pgvector

pgvector is NOT pre-installed on Railway Postgres. Enable it once:

```bash
railway connect postgres
# Then in psql:
CREATE EXTENSION IF NOT EXISTS vector;
```

## Alembic Migrations

Set `DATABASE_URL` to the public URL when running migrations locally:

```bash
export DATABASE_URL=$(railway variables --json | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")
uv run alembic upgrade head
```

Or run inside Railway's environment (uses internal URL):
```bash
railway run uv run alembic upgrade head
```

## Dump & Restore

```bash
# Dump from Railway (external URL)
RAILWAY_URL=$(railway variables --json | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")

docker run --rm postgres:16 pg_dump "$RAILWAY_URL" \
  --no-owner --no-acl \
  --exclude-table=embeddings \
  --exclude-table=llm_cache \
  > /tmp/signalrank_dump.sql

# Restore to Railway
docker run --rm -i postgres:16 psql "$RAILWAY_URL" < /tmp/signalrank_dump.sql
```

## Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `SSL connection required` | Missing SSL param | Add `?sslmode=require` or `ssl="require"` |
| `certificate verify failed` | Using `verify-full` | Switch to `sslmode=require` |
| `Extension "vector" not found` | pgvector not installed | `CREATE EXTENSION IF NOT EXISTS vector;` |
| `\dt` shows no tables | `search_path` cleared by pg_dump | Use `SET search_path=public;` or `\dt *.*` |
| asyncpg rejects URL | `postgresql://` prefix | Replace with `postgresql+asyncpg://` |
| Internal URL fails locally | `DATABASE_URL` is private | Use `DATABASE_PUBLIC_URL` from local |

## Railway CLI Quick Reference

```bash
railway status          # Current project/env
railway variables       # List all env vars
railway connect postgres # Interactive psql session
railway run <cmd>       # Run command with Railway env injected
railway logs            # Tail service logs
```
