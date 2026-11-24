#!/usr/bin/env bash
# Nightly MDDB backup on idc03 — loops the local mddb quadlet instances
# (default: mddb leader :11023, mddb-ops :11026, mddb-cms :11027; mddb-embed
# moved to idc02 2026-11-12 and is covered by idc02's own copy of this script).
#
# Backup method (unchanged from the 2026-11-11 generalized script):
#   1. PRIMARY: native /v1/backup — consistent since mddb v2.15.4
#      (backupTo copies via a bbolt read-tx + self-verifies before rename,
#      upstream PR #281). The staged file appears in /app/backups only after
#      the server-side rename, so file-exists == complete+verified.
#   2. FALLBACK: file copy of the live mddb.db + open-verify in a throwaway
#      container, retried x3 — the copy races live bbolt writes.
#
# Disk-headroom guards added 2026-11-19 (card mddb-backup-disk-headroom-guard)
# after the ~02:55 ENOSPC: an 18G partial mddb-ops pull onto a 99%-full /
# tore kanban card writes and took board-api down.
#
#   a. PRE-FLIGHT df check — before each instance writes a byte, require
#      free >= max(MIN_FREE_GB, 2x expected uncompressed dump size).
#      Low headroom => skip that instance + board alert; never starts a
#      pull it cannot finish.
#   b. .tmp + rename — host-side artifacts land as *.tmp and are renamed to
#      *.db.gz only after gzip -t passes, so a partial can never masquerade
#      as a valid backup. The pull streams `podman exec cat | gzip` (podman
#      cp of the raw .db is the shell-less-image fallback) — only compressed
#      bytes hit the host fs; the 2x margin covers the in-container staging.
#   c. Retention sweep — stale .tmp/.UNVERIFIED first, then per-instance
#      KEEP_COPIES, then a whole-directory size cap that never deletes the
#      newest surviving copy of an instance.
#   d. Alert path — board-api /comment on the timer-alert card + /inbox
#      entry; failures also exit non-zero so timer-sentinel flags the run.
#
# NOTE: /v1/backup closes the connection with no HTTP response (curl exit 52)
# even on success — verify by the staged file appearing, not curl status.
set -euo pipefail
umask 077            # backup artifacts contain DB contents — never world-readable

INSTANCES="${MDDB_BACKUP_INSTANCES:-mddb:11023 mddb-ops:11026 mddb-cms:11027}"
HOST="${MDDB_BACKUP_HOST:-100.102.134.91}"
BK="${MDDB_BACKUP_DIR:-$HOME/mddb-backups}"
MIN_FREE_GB="${MDDB_BACKUP_MIN_FREE_GB:-15}"
KEEP_COPIES="${MDDB_BACKUP_KEEP_COPIES:-3}"
CAP_GB="${MDDB_BACKUP_CAP_GB:-80}"
NATIVE_WAIT_S="${MDDB_BACKUP_NATIVE_WAIT_S:-1800}"
VERIFY_IMAGE="${MDDB_BACKUP_VERIFY_IMAGE:-docker.io/tradik/mddb:2.15.4}"
# health-poll seconds per filecopy verify attempt (NoFreelistSync rescan can
# take ~20min on a big DB — hence the generous default)
VERIFY_WAIT_S="${MDDB_BACKUP_VERIFY_WAIT_S:-1200}"
BOARD_API="${MDDB_BACKUP_BOARD_API:-http://127.0.0.1:8787}"
ALERT_CARD="${MDDB_BACKUP_ALERT_CARD:-timer-alert-idc03-mddb-backup}"
STAMP="$(date +%Y%m%d-%H%M)"
FAILED=()

mkdir -p "$BK"

log() { echo "[$(date '+%F %T')] $*"; }

alert() {
  local msg="mddb-backup idc03 $(date '+%F %T'): $*"
  log "ALERT: $msg"
  BOARD_API="$BOARD_API" ALERT_CARD="$ALERT_CARD" ALERT_MSG="$msg" \
    python3 - <<'PY' || true
import json, os, urllib.request
api, card, msg = (os.environ["BOARD_API"], os.environ["ALERT_CARD"],
                  os.environ["ALERT_MSG"])
def post(path, body):
    try:
        req = urllib.request.Request(
            api + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"board-api {path} failed: {e}", file=__import__("sys").stderr)
post("/comment", {"id": card, "from": "chaba", "text": msg})
post("/inbox", {"text": msg, "label": "mddb-backup failure on idc03",
                "priority": "high", "tags": ["ops", "mddb", "backup"]})
PY
}

free_kb() { df -kP "$BK" | awk 'NR==2 {print $4}'; }

db_bytes() { # $1=container -> live mddb.db size in bytes (empty on failure)
  podman exec "$1" sh -c \
    'stat -c %s /app/data/mddb.db 2>/dev/null || du -sb /app/data 2>/dev/null | cut -f1' \
    2>/dev/null | tail -1 | cut -f1
}

ce() { # container exec that tolerates shell-less images returning garbage
  podman exec "$@"
}

stale_sweep() { # drop debris from crashed runs BEFORE measuring headroom
  find "$BK" -name '*.tmp*' -mmin +120 -delete 2>/dev/null || true
  local pair c
  for pair in $INSTANCES; do
    c="${pair%%:*}"
    ce "$c" sh -c 'find /app/backups -type f -mmin +60 -delete' \
      >/dev/null 2>&1 || true
  done
}

headroom_ok() { # $1=container $2=expected_bytes -> 0 if safe to proceed
  local need_kb=$(( MIN_FREE_GB * 1024 * 1024 ))
  local two_x_kb=$(( 2 * ${2:-0} / 1024 ))
  [ "$two_x_kb" -gt "$need_kb" ] && need_kb=$two_x_kb
  local avail
  avail=$(free_kb)
  if [ "${avail:-0}" -lt "$need_kb" ]; then
    alert "SKIP $1 — low headroom: $((avail/1024/1024))G free < required" \
      "$((need_kb/1024/1024))G (2x expected $((${2:-0}/1024/1024/1024))G," \
      "floor ${MIN_FREE_GB}G)"
    return 1
  fi
  return 0
}

pull_staged() { # $1=container $2=staged-name -> writes $BK/$2.db.gz
  local c="$1" n="$2" tmp="$BK/$2.db.gz.tmp" raw="$BK/$2.db.tmp"
  rm -f "$tmp" "$raw"
  if ce "$c" cat "/app/backups/$n" 2>/dev/null | gzip -1 > "$tmp" \
     && [ -s "$tmp" ] && gzip -t "$tmp" 2>/dev/null; then
    mv "$tmp" "$BK/$n.db.gz"
    return 0
  fi
  rm -f "$tmp"
  # shell-less image fallback: uncompressed cp to .tmp, then gzip
  if podman cp "$c:/app/backups/$n" "$raw" 2>/dev/null && [ -s "$raw" ]; then
    gzip -1 "$raw" && mv "$raw.gz" "$BK/$n.db.gz" && return 0
  fi
  rm -f "$raw" "$raw.gz"
  return 1
}

native_backup() { # $1=container $2=port $3=name -> 0 on success
  local c="$1" port="$2" n="$3"
  curl -s --max-time 120 "http://$HOST:$port/v1/backup?to=$n" \
    >/dev/null 2>&1 || true
  local waited=0
  while [ "$waited" -lt "$NATIVE_WAIT_S" ]; do
    if ce "$c" test -s "/app/backups/$n" 2>/dev/null; then
      if pull_staged "$c" "$n"; then
        ce "$c" rm -f "/app/backups/$n" >/dev/null 2>&1 || true
        log "backup ok (native, server-verified): $BK/$n.db.gz" \
          "($(du -h "$BK/$n.db.gz" | cut -f1))"
        return 0
      fi
      ce "$c" rm -f "/app/backups/$n" >/dev/null 2>&1 || true
      log "WARNING: staged $n pull failed — staged copy removed" >&2
      return 1
    fi
    sleep 5; waited=$((waited + 5))
  done
  log "WARNING: native backup produced no staged file for $c" >&2
  return 1
}

filecopy_backup() { # $1=container $2=name -> 0 if a verified copy landed
  local c="$1" n="$2" fc="$BK/$2-filecopy.db.tmp" ok=0 attempt
  rm -f "$fc"
  for attempt in 1 2 3; do
    # stream the live db out (cat races bbolt writes — verify catches tears)
    if ! ce "$c" cat /app/data/mddb.db > "$fc" 2>/dev/null; then
      podman cp "$c:/app/data/mddb.db" "$fc" 2>/dev/null || true
    fi
    [ -s "$fc" ] || { sleep 30; continue; }
    chmod 666 "$fc" 2>/dev/null || true
    if podman run -d --name mddb-backup-verify --rm --replace \
        -p 127.0.0.1:12223:12223 \
        -v "$BK:/backup:rw" --env MDDB_ADDR=0.0.0.0:12223 \
        --env MDDB_HTTP_ENABLED=true --env MDDB_GRPC_ENABLED=false \
        --env MDDB_MCP_ENABLED=false \
        --env MDDB_PATH=/backup/$(basename "$fc") \
        --env MDDB_AUTH_ENABLED=false \
        "$VERIFY_IMAGE" >/dev/null 2>&1; then
      for _ in $(seq 1 $((VERIFY_WAIT_S / 6))); do
        sleep 6
        if curl -s -m3 http://127.0.0.1:12223/v1/health 2>/dev/null \
           | grep -q healthy; then
          ok=1; break
        fi
      done
    fi
    podman rm -f mddb-backup-verify >/dev/null 2>&1 || true
    [ "$ok" = 1 ] && break
    log "WARNING: filecopy attempt $attempt failed open-verify" >&2
    [ "$attempt" -lt 3 ] && sleep 30
  done
  if [ "$ok" = 1 ]; then
    gzip -1 "$fc" && mv "$fc.gz" "$BK/$n.db.gz"
    log "backup ok (filecopy, attempt $attempt, open-verified):" \
      "$BK/$n.db.gz ($(du -h "$BK/$n.db.gz" | cut -f1))"
  else
    gzip -1 "$fc" 2>/dev/null && mv "$fc.gz" "$BK/$n.db.gz.UNVERIFIED" || rm -f "$fc"
    log "WARNING: filecopy failed open-verify x3 -> $n.db.gz.UNVERIFIED" >&2
  fi
  return "$((1 - ok))"
}

retention() {
  local pair c
  for pair in $INSTANCES; do
    c="${pair%%:*}"
    # "-2*" pins the glob to the YYYYMMDD stamp — a bare "$c"-* glob for
    # instance "mddb" would also match "mddb-ops-*" backups
    ls -t "$BK/$c"-2*.db.gz 2>/dev/null | tail -n "+$((KEEP_COPIES + 1))" \
      | xargs -r rm -f || true
  done
  ls -t "$BK"/*.UNVERIFIED 2>/dev/null | tail -n +3 | xargs -r rm -f || true
  # whole-directory cap: delete oldest .db.gz but never the newest of an
  # instance — a cap must not leave an instance with zero backups
  local cap_kb=$(( CAP_GB * 1024 * 1024 )) protected oldest
  while [ "$(du -sk "$BK" 2>/dev/null | cut -f1)" -gt "$cap_kb" ]; do
    protected=$(for pair in $INSTANCES; do
        c="${pair%%:*}"
        ls -t "$BK/$c"-2*.db.gz 2>/dev/null | head -1
      done)
    oldest=$(ls -tr "$BK"/*.db.gz 2>/dev/null \
      | grep -vxF -f <(printf '%s\n' $protected) | head -1)
    [ -n "$oldest" ] || break
    log "retention: dir over ${CAP_GB}G cap — removing $(basename "$oldest")"
    rm -f "$oldest"
  done
}

stale_sweep

for pair in $INSTANCES; do
  c="${pair%%:*}"; port="${pair##*:}"; name="${c}-${STAMP}"
  expected="$(db_bytes "$c")"
  if ! [[ "$expected" =~ ^[0-9]+$ ]] || [ "$expected" -eq 0 ]; then
    alert "SKIP $c — cannot read live db size (container down or no shell?)"
    FAILED+=("$c:probe")
    continue
  fi
  if ! headroom_ok "$c" "$expected"; then
    FAILED+=("$c:headroom")
    continue
  fi
  if native_backup "$c" "$port" "$name"; then
    continue
  fi
  if ! headroom_ok "$c" "$expected"; then
    FAILED+=("$c:headroom-fallback")
    continue
  fi
  filecopy_backup "$c" "$name" || FAILED+=("$c:unverified")
done

retention

if [ "${#FAILED[@]}" -gt 0 ]; then
  alert "run finished with failures: ${FAILED[*]} (timer $STAMP)"
  exit 1
fi
log "backup run complete — $(du -sh "$BK" | cut -f1) in $BK"
