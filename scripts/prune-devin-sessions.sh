#!/usr/bin/env bash
# Devin sessions DB prune + VACUUM
# Must be run while no Devin process is using the database.
# Usage: ./prune-devin-sessions.sh [retention-days]
# Default retention is 3 days.

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

if fuser "$DB" >/dev/null 2>&1; then
  echo "Error: $DB is currently in use by Devin. Close Devin first." >&2
  fuser -v "$DB" 2>&1 || true
  exit 1
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

mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/sessions-$TIMESTAMP.db"

cp -a "$DB" "$BACKUP"
echo "Backup created: $BACKUP"

BEFORE=$(du -sh "$DB" | awk '{print $1}')

echo "Pruning sessions with last_activity_at < $CUTOFF ($RETENTION_DAYS days ago) ..."

sqlite3 "$DB" <<EOF
PRAGMA journal_mode = DELETE;

-- Delete child data first to avoid foreign-key/cascade issues.
DELETE FROM message_nodes WHERE session_id IN (
  SELECT id FROM sessions WHERE last_activity_at < $CUTOFF
);

DELETE FROM tool_call_state WHERE session_id IN (
  SELECT id FROM sessions WHERE last_activity_at < $CUTOFF
);

DELETE FROM sessions WHERE last_activity_at < $CUTOFF;

VACUUM;

PRAGMA journal_mode = WAL;
PRAGMA wal_checkpoint(TRUNCATE);
EOF

AFTER=$(du -sh "$DB" | awk '{print $1}')

echo "Before: $BEFORE"
echo "After:  $AFTER"
echo "Done."
