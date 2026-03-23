#!/usr/bin/env bash
# backup.sh — dump the SignalRank PostgreSQL database to a timestamped file
#
# Usage:
#   ./backup.sh                      # dump to ./backups/
#   ./backup.sh --dir /my/path       # dump to custom directory
#   ./backup.sh --restore file.sql   # restore from a previous dump
#   ./backup.sh --list               # list available backups
#   ./backup.sh --prune 7            # delete backups older than N days (default: 30)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/backups"
PG_CONTAINER="signalrank-pg"
PG_DB="signalrank"
PG_USER="postgres"
PRUNE_DAYS=30

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[backup]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }
die()  { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

MODE="backup"
RESTORE_FILE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --dir)     BACKUP_DIR="$2"; shift 2 ;;
    --restore) MODE="restore"; RESTORE_FILE="$2"; shift 2 ;;
    --list)    MODE="list"; shift ;;
    --prune)   MODE="prune"; PRUNE_DAYS="${2:-30}"; shift; [[ $# -gt 0 ]] && shift || true ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_container() {
  docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$" \
    || die "Container $PG_CONTAINER is not running. Start it with: docker start $PG_CONTAINER"
}

# ── List ──────────────────────────────────────────────────────────────────────

if [[ $MODE == "list" ]]; then
  if [[ ! -d "$BACKUP_DIR" ]] || [[ -z "$(ls -A "$BACKUP_DIR"/*.sql 2>/dev/null)" ]]; then
    info "No backups found in $BACKUP_DIR"
    exit 0
  fi
  info "Backups in $BACKUP_DIR:"
  ls -lh "$BACKUP_DIR"/*.sql | awk '{print "  " $5 "\t" $9}' | sort -r
  exit 0
fi

# ── Prune ─────────────────────────────────────────────────────────────────────

if [[ $MODE == "prune" ]]; then
  if [[ ! -d "$BACKUP_DIR" ]]; then
    info "No backup directory found, nothing to prune."
    exit 0
  fi
  count=$(find "$BACKUP_DIR" -name "*.sql" -mtime +"$PRUNE_DAYS" | wc -l | tr -d ' ')
  if [[ $count -eq 0 ]]; then
    info "No backups older than $PRUNE_DAYS days."
    exit 0
  fi
  info "Pruning $count backup(s) older than $PRUNE_DAYS days..."
  find "$BACKUP_DIR" -name "*.sql" -mtime +"$PRUNE_DAYS" -exec rm -v {} \;
  info "Done."
  exit 0
fi

# ── Restore ───────────────────────────────────────────────────────────────────

if [[ $MODE == "restore" ]]; then
  [[ -z "$RESTORE_FILE" ]] && die "Specify a file: ./backup.sh --restore backups/signalrank_20260101_120000.sql"
  [[ -f "$RESTORE_FILE" ]] || die "File not found: $RESTORE_FILE"
  require_container

  warn "This will DROP and recreate the '$PG_DB' database. All current data will be lost."
  read -r -p "Type 'yes' to confirm: " confirm
  [[ $confirm == "yes" ]] || { info "Aborted."; exit 0; }

  info "Dropping and recreating database $PG_DB..."
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -c "DROP DATABASE IF EXISTS $PG_DB;" postgres
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -c "CREATE DATABASE $PG_DB;" postgres

  info "Restoring from $RESTORE_FILE..."
  docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" "$PG_DB" < "$RESTORE_FILE"
  info "Restore complete."
  exit 0
fi

# ── Backup ────────────────────────────────────────────────────────────────────

require_container
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_FILE="$BACKUP_DIR/signalrank_${TIMESTAMP}.sql"

info "Dumping $PG_DB → $OUT_FILE ..."
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" "$PG_DB" > "$OUT_FILE"

SIZE=$(du -sh "$OUT_FILE" | cut -f1)
info "Backup complete: $OUT_FILE ($SIZE)"

# Auto-prune old backups
OLD=$(find "$BACKUP_DIR" -name "*.sql" -mtime +"$PRUNE_DAYS" | wc -l | tr -d ' ')
if [[ $OLD -gt 0 ]]; then
  info "Auto-pruning $OLD backup(s) older than $PRUNE_DAYS days..."
  find "$BACKUP_DIR" -name "*.sql" -mtime +"$PRUNE_DAYS" -delete
fi
