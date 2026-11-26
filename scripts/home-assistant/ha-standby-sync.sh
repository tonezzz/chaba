#!/usr/bin/env bash
# ha-standby-sync.sh — pull the live tony-ha config into the cold-standby
# mirror on THIS host. Run on the standby host, never on tony-omen.
#
# Usage:
#   ha-standby-sync.sh [--db] [--source HOST] [--dest DIR] [--force] [--dry-run]
#
#   --db        also snapshot the recorder DB (home-assistant_v2.db) via the
#               SQLite online backup API into the state dir — consistent on a
#               live DB, never touches the file HA is writing.
#   --source    live HA host (default: $HA_STANDBY_SOURCE or tony-omen —
#               ssot.home-assistant.instances.yml#tony-ha)
#   --dest      mirror target (default: $HA_STANDBY_DEST or
#               ~/.config/home-assistant — the canonical config path, so
#               promotion needs no copy step)
#   --force     allow mirroring into a non-empty dest that has no recorded
#               standby sync (guards a pre-existing real config)
#   --dry-run   print the rsync command and exit
#
# What syncs: the whole config tree — configuration.yaml, .storage/ (auth,
# registries, dashboards, ha_mcp_tools), secrets.yaml, household.yml,
# www/, patches/, custom_components/, and the config .git history —
# EXCEPT the live recorder DB and runtime noise (see EXCLUDES).
#
# Split-brain guard: refuses to run while a tony-ha/ada-ha container or
# quadlet is active on this host — two live tony-ha instances diverge
# state (precedent: stale michael-dev on omen held :8123, 2026-10-20).
#
# State/manifest: $HOME/.local/share/ha-standby-sync/ (last-sync.txt,
# home-assistant_v2.snapshot.db, sync.lock) — outside the mirrored tree so
# --delete can never touch it.
#
# Runbook: docs/runbooks/tony-ha-cold-standby.md
# Card:    tony-ha-cold-standby-config-sync-promote-d12293 (HOM-0855)
set -euo pipefail

SOURCE="${HA_STANDBY_SOURCE:-tony-omen}"
DEST="${HA_STANDBY_DEST:-$HOME/.config/home-assistant}"
SRC_CONFIG="/home/tony/.config/home-assistant"
STATE_DIR="${HA_STANDBY_STATE_DIR:-$HOME/.local/share/ha-standby-sync}"
WITH_DB=0
FORCE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) WITH_DB=1 ;;
    --source) SOURCE="$2"; shift ;;
    --dest) DEST="$2"; shift ;;
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

log() { printf '%s %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

command -v rsync >/dev/null || die "rsync not installed"
command -v ssh >/dev/null || die "ssh not installed"
if [[ $WITH_DB -eq 1 ]]; then
  command -v scp >/dev/null || die "scp not installed (needed for --db snapshot)"
fi

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/sync.lock"
flock -n 9 || { log "another ha-standby-sync is running — exiting"; exit 0; }

# --- source-host guard ------------------------------------------------------
LOCAL_HOST="$(hostname -s 2>/dev/null || hostname)"
SRC_HOST="$(printf '%s' "$SOURCE" | cut -d. -f1)"
[[ "$LOCAL_HOST" == "$SRC_HOST" ]] && die "refusing to run on the source host ($SOURCE) — this script mirrors prod -> standby only"

# --- split-brain guard -----------------------------------------------------
for unit in tony-ha.service tony-ha.container ada-ha.service ada-ha.container; do
  if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
    die "$unit is ACTIVE on $(hostname) — a live HA instance here would split-brain against $SOURCE. Stop it first (see runbook rollback section)."
  fi
done
if podman ps --format '{{.Names}}' 2>/dev/null | grep -qxE 'tony-ha|ada-ha'; then
  die "a tony-ha/ada-ha container is running on $(hostname) — split-brain guard. Stop it first."
fi

# --- first-run guard --------------------------------------------------------
ESTABLISHED="$STATE_DIR/.established-$(printf '%s' "$DEST" | sha1sum | cut -c1-8)"
if [[ -d "$DEST" ]] && [[ -n "$(ls -A "$DEST" 2>/dev/null)" ]] && [[ ! -f "$ESTABLISHED" && $FORCE -eq 0 ]]; then
  die "$DEST exists and is non-empty but no standby sync was recorded for it.
       If this is a disposable/pre-existing config, re-run with --force.
       If it is a REAL HA config, pick a different --dest or promote it first."
fi

# --- reachability -----------------------------------------------------------
ssh -o ConnectTimeout=10 -o BatchMode=yes "$SOURCE" "test -d '$SRC_CONFIG'" \
  || die "cannot reach $SOURCE:$SRC_CONFIG over ssh (tailscale up? key auth?)"

mkdir -p "$DEST"

# --- image identity (best effort — the promote step pins by this) -----------
# Captures the quadlet ref, local image ID, and repo digest so a promote
# never has to guess which HA build the patch mounts were written for.
IMAGE_INFO=""
IMAGE_INFO=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$SOURCE" 'sh -c '"'"'
  ref=$(podman inspect tony-ha --format "{{.Config.Image}}" 2>/dev/null) || exit 0
  id=$(podman inspect tony-ha --format "{{.Image}}" 2>/dev/null)
  dig=$(podman image inspect "$id" --format "{{.Digest}}" 2>/dev/null)
  printf "%s id=%s digest=%s" "$ref" "$id" "$dig"
'"'"'' 2>/dev/null | tr -d '\r' || true)

# --- rsync ------------------------------------------------------------------
# Anchored excludes: live recorder DB (see --db), runtime noise, python
# deps (reinstalled at boot, image-pinned). Everything else mirrors,
# including .storage/ and the config .git history.
RSYNC_ARGS=(
  -a --delete --info=stats2 --human-readable
  -e "ssh -o ConnectTimeout=10 -o BatchMode=yes"
  --exclude='/home-assistant_v2.db'
  --exclude='/home-assistant_v2.db-wal'
  --exclude='/home-assistant_v2.db-shm'
  --exclude='/home-assistant_v2.db-journal'
  --exclude='/home-assistant.log*'
  --exclude='/deps/'
  --exclude='/tts/'
  --exclude='/__pycache__/'
  --exclude='*.pyc'
  --exclude='/.ha_run.lock'
)

if [[ $DRY_RUN -eq 1 ]]; then
  printf '%q ' rsync "${RSYNC_ARGS[@]}" "$SOURCE:$SRC_CONFIG/" "$DEST/"
  printf '\n'
  exit 0
fi

log "syncing $SOURCE:$SRC_CONFIG/ -> $DEST/"
rsync "${RSYNC_ARGS[@]}" "$SOURCE:$SRC_CONFIG/" "$DEST/"

# --- optional recorder-DB snapshot ------------------------------------------
# The DB lives on the SOURCE host, so the SQLite online backup API runs
# there over ssh (consistent on a live WAL database), then the snapshot is
# pulled back. Temp file on the source is removed on exit.
SNAP_DB=""
if [[ $WITH_DB -eq 1 ]]; then
  SNAP_DB="$STATE_DIR/home-assistant_v2.snapshot.db"
  REMOTE_TMP="/tmp/ha-standby-snap-$$.db"
  cleanup_remote() { ssh -o ConnectTimeout=10 -o BatchMode=yes "$SOURCE" "rm -f '$REMOTE_TMP'" 2>/dev/null || true; }
  trap cleanup_remote EXIT
  log "snapshotting recorder DB on $SOURCE -> $SNAP_DB"
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$SOURCE" python3 -c '
import sqlite3, sys
s = sqlite3.connect(sys.argv[1])
d = sqlite3.connect(sys.argv[2])
try:
    s.backup(d)
finally:
    d.close(); s.close()
' "$SRC_CONFIG/home-assistant_v2.db" "$REMOTE_TMP"
  scp -q -o ConnectTimeout=10 -o BatchMode=yes "$SOURCE:$REMOTE_TMP" "$SNAP_DB"
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$SOURCE" "rm -f '$REMOTE_TMP'"
  trap - EXIT
  log "db snapshot: $(du -h "$SNAP_DB" | cut -f1) -> $SNAP_DB"
fi

# --- manifest ---------------------------------------------------------------
cat > "$STATE_DIR/last-sync.txt" <<EOF
synced_at: $(date -Is)
source: $SOURCE:$SRC_CONFIG/
dest: $DEST/
image: ${IMAGE_INFO:-unknown}
with_db: $WITH_DB
EOF
touch "$ESTABLISHED"
log "done — manifest: $STATE_DIR/last-sync.txt"
