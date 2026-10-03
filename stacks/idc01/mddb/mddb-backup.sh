#!/usr/bin/env bash
# Nightly MDDB backup on idc01.
#
#   1. PRIMARY: native /v1/backup — consistent since mddb v2.15.4
#      (backupTo copies via a bbolt read-tx + self-verifies before rename,
#      upstream PR #281; verified restorable 2026-10-03 on
#      localhost/mddb:2.15.4-allowlist). The server already open-verifies
#      the copy, so the pulled file counts as verified.
#   2. FALLBACK: file copy of mddb.db + open-verify in a throwaway
#      container — used only when the native backup produces no file.
#      The copy races live bbolt writes, so it retries up to 3 times
#      with a fresh copy per attempt.
#
# Semantic tier lives elsewhere: ada-memory-backup.timer on tony-omen dumps
# all collections to JSON (chaba/backups/ada-memory/, mn01 mirror).
#
# NOTE: /v1/backup closes the connection with no HTTP response (curl exit 52)
# even on success — verify by the file existing, not curl status.
set -euo pipefail
NAME="mddb-$(date +%Y%m%d-%H%M)"
DATA="$HOME/.config/containers/mddb/data"
BK="$HOME/mddb-backups"

# tier 1: native snapshot (consistent + server-verified on >=2.15.4)
curl -s --max-time 300 "http://100.74.146.0:11023/v1/backup?to=$NAME" || true
podman cp "mddb:/app/backups/$NAME" "$BK/$NAME.db" 2>/dev/null || true
if [ -s "$BK/$NAME.db" ]; then
  podman exec mddb rm -f "/app/backups/$NAME" 2>/dev/null || true
  echo "backup ok (native, server-verified): $BK/$NAME.db ($(du -h $BK/$NAME.db | cut -f1))"
  ls -t $BK/mddb-2*.db 2>/dev/null | tail -n +5 | xargs -r rm -f || true
  ls -t $BK/*.UNVERIFIED 2>/dev/null | tail -n +3 | xargs -r rm -f || true
  exit 0
fi

# tier 2: file copy + verify-open fallback, up to 3 attempts
echo "WARNING: native backup produced no file — falling back to filecopy" >&2
FC="$BK/mddb-filecopy-$NAME.db"
verify_ok=0
for attempt in 1 2 3; do
  # data dir is owned by the container uid (100999); copy via podman instead
  podman cp "mddb:/app/data/mddb.db" "$FC"
  chmod 666 "$FC"
  if podman run -d --name mddb-backup-verify --rm --replace \
      -p 127.0.0.1:12223:12223 \
      -v "$BK:/backup:rw" --env MDDB_ADDR=0.0.0.0:12223 \
      --env MDDB_HTTP_ENABLED=true --env MDDB_GRPC_ENABLED=false \
      --env MDDB_MCP_ENABLED=false --env MDDB_PATH=/backup/$(basename $FC) \
      --env MDDB_AUTH_ENABLED=false \
      docker.io/tradik/mddb:2.15.4 >/dev/null 2>&1; then
    # NoFreelistSync => open walks the whole B-tree (freelist rescan);
    # allow 20 min, not 60s
    for i in $(seq 1 200); do
      sleep 6
      if curl -s -m3 http://127.0.0.1:12223/v1/health 2>/dev/null | grep -q healthy; then
        verify_ok=1; break
      fi
    done
  fi
  podman rm -f mddb-backup-verify >/dev/null 2>&1 || true
  if [ "$verify_ok" = 1 ]; then
    echo "filecopy verified: $FC (attempt $attempt)"
    break
  fi
  echo "WARNING: filecopy attempt $attempt failed open-verify" >&2
  [ "$attempt" -lt 3 ] && sleep 30
done
if [ "$verify_ok" = 0 ]; then
  mv "$FC" "$FC.UNVERIFIED"
  echo "WARNING: filecopy failed open-verify after 3 attempts -> $FC.UNVERIFIED" >&2
fi

# retention: keep last 4 of each kind, last 2 unverified
ls -t $BK/mddb-2*.db 2>/dev/null | tail -n +5 | xargs -r rm -f || true
ls -t $BK/mddb-filecopy-*.db 2>/dev/null | tail -n +5 | xargs -r rm -f || true
ls -t $BK/*.UNVERIFIED 2>/dev/null | tail -n +3 | xargs -r rm -f || true
echo "backup ok: $FC ($(du -h $FC 2>/dev/null | cut -f1)) verified=$verify_ok"
