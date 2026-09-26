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

# Lesson (2026-09-12, tony-omen): a corrupt sessions.db fails mid-run with
# "database disk image is malformed" — after message_nodes are already deleted
# but before the sessions rows go. Check integrity BEFORE touching anything.
# A corrupt DB can also under-report row counts via damaged indexes, so time-based
# pruning may silently miss data. Rebuild instead:
#   sqlite3 "$DB" .recover | sqlite3 sessions-new.db
#   # prune sessions-new.db, verify: PRAGMA integrity_check;
#   # then swap sessions-new.db into place.
if [ "${SKIP_INTEGRITY_CHECK:-0}" != "1" ]; then
  echo "Running quick_check (can take a while on large DBs; SKIP_INTEGRITY_CHECK=1 to bypass) ..."
  if ! sqlite3 "$DB" "PRAGMA quick_check;" | head -20 | grep -qx 'ok'; then
    echo "Error: $DB failed integrity check — do NOT prune in place." >&2
    echo "Recover instead: sqlite3 \"$DB\" .recover | sqlite3 sessions-new.db" >&2
    echo "(set SKIP_INTEGRITY_CHECK=1 to force the in-place prune anyway)" >&2
    exit 1
  fi
fi

DB_BYTES=$(stat -c %s "$DB" 2>/dev/null || echo 0)
FREE_KB=$(df -k --output=avail "$(dirname "$DB")" | tail -1 | tr -d ' ')
# Auto-skip the pre-cleanup copy when the DB would not fit with 20% headroom
# (learned 2026-09-10: a 155G sessions.db filled /home mid-copy and left the
# timer permanently failing). Set FORCE_BACKUP=1 to override.
if [ "${FORCE_BACKUP:-}" = "1" ] || { [ "${NO_BACKUP:-}" != "1" ] && [ $((DB_BYTES / 1024 * 6 / 5)) -lt "$FREE_KB" ]; }; then
  mkdir -p "$BACKUP_DIR"
  BACKUP="$BACKUP_DIR/sessions-$TIMESTAMP.db"
  cp -a "$DB" "$BACKUP"
  echo "Backup created: $BACKUP"
  # keep only the newest 3 backups — the backup dir is what filled /home
  ls -t "$BACKUP_DIR"/sessions-*.db 2>/dev/null | tail -n +4 | xargs -r rm -f
else
  echo "Skipping pre-cleanup copy (db=$((DB_BYTES/1024/1024))G free=$((FREE_KB/1024/1024))G; FORCE_BACKUP=1 to override)"
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
