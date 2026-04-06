#!/usr/bin/env bash
# setup.sh — one-shot setup and start for SignalRank
# Usage: ./setup.sh [--no-docker] [--skip-deps]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

NO_DOCKER=0
SKIP_DEPS=0
_START_WORKER=0
for arg in "$@"; do
  case $arg in
    --no-docker)    NO_DOCKER=1 ;;
    --skip-deps)    SKIP_DEPS=1 ;;
    --local-worker) _START_WORKER=1 ;;
  esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
die()   { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ── Prerequisites ────────────────────────────────────────────────────────────

command -v uv   >/dev/null 2>&1 || die "uv not found. Install: curl -Ls https://astral.sh/uv/install.sh | sh"
command -v node >/dev/null 2>&1 || die "node not found. Install Node 20+ from https://nodejs.org"
command -v npm  >/dev/null 2>&1 || die "npm not found."

if [[ $NO_DOCKER -eq 0 ]]; then
  command -v docker >/dev/null 2>&1 || die "docker not found. Install Docker Desktop or pass --no-docker."
fi

# ── PostgreSQL via Docker ────────────────────────────────────────────────────

PG_CONTAINER="signalrank-pg"
PG_PASSWORD="postgres"
PG_DB="signalrank"
PG_PORT="5432"

if [[ $NO_DOCKER -eq 0 ]]; then
  if docker ps -a --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
      info "Starting existing $PG_CONTAINER container..."
      docker start "$PG_CONTAINER"
    else
      info "PostgreSQL container $PG_CONTAINER already running."
    fi
  else
    info "Pulling and starting pgvector/pgvector:pg16..."
    docker run -d \
      --name "$PG_CONTAINER" \
      -e POSTGRES_DB="$PG_DB" \
      -e POSTGRES_PASSWORD="$PG_PASSWORD" \
      -p "${PG_PORT}:5432" \
      pgvector/pgvector:pg16
  fi

  info "Waiting for PostgreSQL to be ready..."
  for i in $(seq 1 20); do
    if docker exec "$PG_CONTAINER" pg_isready -U postgres -q 2>/dev/null; then
      info "PostgreSQL is ready."
      break
    fi
    [[ $i -eq 20 ]] && die "PostgreSQL did not become ready after 20s."
    sleep 1
  done
fi

# ── Backend .env ─────────────────────────────────────────────────────────────

BACKEND_ENV="$BACKEND_DIR/.env"

if [[ ! -f "$BACKEND_ENV" ]]; then
  info "Creating $BACKEND_ENV from template..."
  cat > "$BACKEND_ENV" <<EOF
DATABASE_URL=postgresql+asyncpg://postgres:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}
NEXTAUTH_SECRET=$(LC_ALL=C tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 40 || true)

# Add your API keys:
# OPENROUTER_API_KEY=sk-or-...
# RAPIDAPI_KEY=...
EOF
  warn "Created $BACKEND_ENV — add OPENROUTER_API_KEY for LLM features."
else
  info "Backend .env already exists, skipping."
fi

# ── Frontend .env.local ───────────────────────────────────────────────────────

FRONTEND_ENV="$FRONTEND_DIR/.env.local"

if [[ ! -f "$FRONTEND_ENV" ]]; then
  info "Creating $FRONTEND_ENV..."
  # Read NEXTAUTH_SECRET from backend env
  NEXTAUTH_SECRET=$(grep -E '^NEXTAUTH_SECRET=' "$BACKEND_ENV" | cut -d= -f2-)
  cat > "$FRONTEND_ENV" <<EOF
AUTH_SECRET=${NEXTAUTH_SECRET}
NEXTAUTH_URL=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
  info "Created $FRONTEND_ENV."
else
  info "Frontend .env.local already exists, skipping."
fi

# ── Install dependencies ──────────────────────────────────────────────────────

if [[ $SKIP_DEPS -eq 0 ]]; then
  info "Installing backend dependencies (uv sync)..."
  (cd "$BACKEND_DIR" && uv sync --quiet)

  info "Installing frontend dependencies (npm install)..."
  (cd "$FRONTEND_DIR" && npm install --silent)
else
  info "Skipping dependency install (--skip-deps)."
fi

# ── Pre-migration backup ──────────────────────────────────────────────────────

if [[ $NO_DOCKER -eq 0 ]] && docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
  info "Taking pre-migration backup..."
  bash "$SCRIPT_DIR/backup.sh" || warn "Backup failed — continuing anyway."
fi

# ── Load backend env into shell ──────────────────────────────────────────────

info "Loading $BACKEND_ENV into shell environment..."
set -a
# shellcheck source=/dev/null
source "$BACKEND_ENV"
set +a

# ── Alembic preflight ─────────────────────────────────────────────────────────

info "Checking Alembic revision graph..."
ALEMBIC_HEADS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && ALEMBIC_HEADS+=("$line")
done < <(cd "$BACKEND_DIR" && uv run alembic heads)
if [[ ${#ALEMBIC_HEADS[@]} -eq 0 ]]; then
  die "No Alembic heads found. Check the migration scripts."
fi
if [[ ${#ALEMBIC_HEADS[@]} -gt 1 ]]; then
  printf '%s\n' "${ALEMBIC_HEADS[@]}" | sed 's/^/[setup] alembic head: /'
  die "Multiple Alembic heads are present. Merge them before running setup."
fi
info "Alembic head: ${ALEMBIC_HEADS[0]}"

# ── Alembic migrations ────────────────────────────────────────────────────────

info "Running database migrations..."
(cd "$BACKEND_DIR" && uv run alembic upgrade head)

# ── Start services ────────────────────────────────────────────────────────────

info "Starting backend on http://localhost:8000 ..."
(cd "$BACKEND_DIR" && uv run uvicorn api.main:app --port 8000 --reload) &
BACKEND_PID=$!

info "Starting frontend on http://localhost:3000 ..."
(cd "$FRONTEND_DIR" && npm run dev) &
FRONTEND_PID=$!

WORKER_PID=""
if [[ $_START_WORKER -eq 1 ]]; then
  # Run a plain poll worker against the local postgres (DATABASE_URL).
  # LOCAL_WORKER=true is for Railway-triggered runs only; local dev uses a regular worker.
  info "Starting worker (SCORER_VERSION=v4) against local DB..."
  (cd "$BACKEND_DIR" && LOCAL_WORKER=false CLAIM_ALL_EXECUTOR_TYPES=true SCORER_VERSION=v4 RUN_API_WORKER=false uv run python -m batch.worker_main poll) &
  WORKER_PID=$!
fi

# ── Cleanup on exit ───────────────────────────────────────────────────────────

cleanup() {
  info "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" ${WORKER_PID:-} 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" ${WORKER_PID:-} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

info "SignalRank running."
info "  Frontend: http://localhost:3000"
info "  Backend:  http://localhost:8000"
info "  API docs: http://localhost:8000/docs"
[[ -n "$WORKER_PID" ]] && info "  Worker:   local (SCORER_VERSION=v4)"
info "Press Ctrl+C to stop."

if [[ -n "$WORKER_PID" ]]; then
  wait "$BACKEND_PID" "$FRONTEND_PID" "$WORKER_PID"
else
  wait "$BACKEND_PID" "$FRONTEND_PID"
fi
