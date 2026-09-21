#!/bin/bash
# vacuum-devin-db.sh — compact the Devin sessions database.
# Run this AFTER closing Devin / Windsurf (no 'devin acp' or 'devin-desktop' processes).
set -euo pipefail

DB_DIR="${HOME}/.local/share/devin/cli"
DB="${DB_DIR}/sessions.db"
BACKUP_DIR="${DB_DIR}/backups"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="${BACKUP_DIR}/sessions.db.${TS}"

# GDrive upload settings (override with env vars if needed)
GDRIVE_REMOTE="${GDRIVE_REMOTE:-gdrive}"
GDRIVE_DEST="${GDRIVE_DEST:-DevinBackups}"
UPLOAD_BACKUP="${DEVIN_UPLOAD_BACKUP:-0}"
EXTRACT_OLD_SESSIONS="${DEVIN_EXTRACT_OLD_SESSIONS:-0}"
KEEP_BACKUPS="${DEVIN_KEEP_BACKUPS:-2}"

if ! [ -f "$DB" ]; then
  echo "Error: $DB not found" >&2
  exit 1
fi

if pgrep -f 'devin-desktop|devin acp' >/dev/null 2>&1; then
  echo "Error: Devin is still running. Close all Devin / Windsurf windows first." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "1. Creating consistent backup: $BACKUP"
sqlite3 "$DB" ".backup '${BACKUP}'"

BEFORE=$(stat -c%s "$DB")
echo "2. Pre-VACUUM size: $BEFORE bytes ($(numfmt --to=iec "$BEFORE" 2>/dev/null || echo "$BEFORE"))"

# Before we vacuum, extract any old sessions to NotebookLM so the content is still
# queryable after the raw rows are later removed by devin-archive-sessions.sh.
if [[ "$EXTRACT_OLD_SESSIONS" == "1" ]]; then
  echo "3. Extracting old session content to NotebookLM (DEVIN_EXTRACT_OLD_SESSIONS=1)"
  bash "$HOME/.config/devin/scripts/devin-extract-sessions.sh" --older-than 3 ||
    echo "   Warning: session extraction failed or was incomplete; continuing." >&2
else
  echo "3. Skipping old-session extraction (DEVIN_EXTRACT_OLD_SESSIONS=0)"
fi

echo "4. Running VACUUM and enabling auto_vacuum"
sqlite3 "$DB" "PRAGMA auto_vacuum = FULL; VACUUM;"

echo "5. Clearing leftover WAL/shm files"
sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
rm -f "${DB}-wal" "${DB}-shm" 2>/dev/null || true

echo "6. Verifying integrity"
sqlite3 "$DB" "PRAGMA integrity_check;"

AFTER=$(stat -c%s "$DB")
echo "7. Post-VACUUM size: $AFTER bytes ($(numfmt --to=iec "$AFTER" 2>/dev/null || echo "$AFTER"))"
echo "   Saved: $((BEFORE - AFTER)) bytes"
echo "   Backup: $BACKUP"

if [[ "$UPLOAD_BACKUP" == "1" ]]; then
  echo "8. Uploading backup to GDrive (${GDRIVE_REMOTE}:${GDRIVE_DEST}/)"
  if command -v rclone >/dev/null 2>&1 && rclone listremotes 2>/dev/null | grep -q "^${GDRIVE_REMOTE}:"; then
    if rclone copyto --progress "$BACKUP" "${GDRIVE_REMOTE}:${GDRIVE_DEST}/$(basename "$BACKUP")"; then
      echo "   Uploaded: ${GDRIVE_REMOTE}:${GDRIVE_DEST}/$(basename "$BACKUP")"
      echo "   You can delete the local backup once the upload is verified."
    else
      echo "   Warning: GDrive upload failed; local backup kept at $BACKUP" >&2
    fi
  else
    echo "   Skipping GDrive upload: rclone or ${GDRIVE_REMOTE}: not configured."
  fi
else
  echo "8. Skipping GDrive upload (DEVIN_UPLOAD_BACKUP=0). Local backup kept: $BACKUP"
fi

echo "9. Pruning old backups (keeping latest $KEEP_BACKUPS)"
(
  cd "$BACKUP_DIR" || exit 0
  ls -1t sessions.db.2* 2>/dev/null | grep -v -- '-shm$\|-wal$' | tail -n "+$((KEEP_BACKUPS + 1))" | while read -r old; do
    rm -f "$old" "$old-shm" "$old-wal"
    echo "   Removed: $old"
  done
)

echo
echo "Backup: $BACKUP"
echo "If Devin starts normally, the local backup can be removed later:"
echo "  rm '$BACKUP'"
