#!/usr/bin/env bash
# Devin sessions DB prune + optional VACUUM
# Deletes sessions older than N days. VACUUM is only run when no Devin
# process is using the database, because VACUUM needs an exclusive lock.
# Usage: ./prune-devin-sessions.sh [retention-days]
# Default retention is 3 days.
# Set NO_BACKUP=1 to skip the pre-cleanup copy (useful for very large DBs).

set -euo pipefail

DB="/home/tony/.local/share/devin/cli/sessions.db"
BACKUP_DIR="/home/tony/.local/share/devin/cli/backups"
RETENTION_DAYS="${1:-3}"
NOW=$(date +%s)
CUTOFF=$(( NOW - RETENTION_DAYS * 86400 ))
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Error: sqlite3 is not installed" >&2
  exit 1
fi

IN_USE=false
if fuser "$DB" >/dev/null 2>&1; then
  IN_USE=true
  echo "Warning: $DB is currently in use by Devin. DELETE will still run, VACUUM will be skipped." >&2
fi

if [ "${NO_BACKUP:-}" != "1" ]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP="$BACKUP_DIR/sessions-$TIMESTAMP.db"
  cp -a "$DB" "$BACKUP"
  echo "Backup created: $BACKUP"
else
  echo "NO_BACKUP=1; skipping pre-cleanup copy"
fi

BEFORE=$(du -sh "$DB" | awk '{print $1}')
echo "Before: $BEFORE"
echo "Pruning sessions with last_activity_at < $CUTOFF ($RETENTION_DAYS days ago) ..."

# Keep WAL mode; changing journal_mode can fail while Devin is connected.
sqlite3 "$DB" <<SQL
-- Delete child data first to avoid foreign-key/cascade issues.
DELETE FROM message_nodes WHERE session_id IN (
  SELECT id FROM sessions WHERE last_activity_at < $CUTOFF
);

DELETE FROM tool_call_state WHERE session_id IN (
  SELECT id FROM sessions WHERE last_activity_at < $CUTOFF
);

DELETE FROM sessions WHERE last_activity_at < $CUTOFF;
SQL

if [ "$IN_USE" = false ]; then
  echo "Running VACUUM ..."
  sqlite3 "$DB" "VACUUM;"
else
  echo "Skipping VACUUM because $DB is in use."
fi

AFTER=$(du -sh "$DB" | awk '{print $1}')
echo "After:  $AFTER"
echo "Done."
