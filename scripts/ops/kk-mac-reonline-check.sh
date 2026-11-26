#!/bin/sh
# kk-mac-reonline-check.sh — one-pass health check for the KK-Mac lane, to
# run from any controller with this repo checked out and SSH access to the
# Mac. It only reads; it never restarts services, submits work or changes
# the heartbeat. Prints PASS / WARN / FAIL lines and a final verdict.
#
# Usage:
#   scripts/ops/kk-mac-reonline-check.sh [ssh-host] [mddb-url]
#
# Defaults: kk-mac, http://100.102.134.91:11026/v1
# Expected healthy state: fresh heartbeat with cpu_cores=14, eligible
# admission snapshot, worker not denying every pass, runner-agent in sync.
set -u

HOST="${1:-kk-mac}"
MDDB_URL="${2:-http://100.102.134.91:11026/v1}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAILNET_IP="${KK_MAC_TAILNET_IP:-100.108.217.17}"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new $HOST"
FAILED=0

pass() { echo "PASS  $*"; }
warn() { echo "WARN  $*"; }
fail() { echo "FAIL  $*"; FAILED=1; }
info() { echo "      $*"; }

echo "=== kk-mac re-online check ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="

# --- 1. tailnet path -------------------------------------------------------
if ping -c 2 -W 2 "$TAILNET_IP" >/dev/null 2>&1; then
    pass "tailnet ping $TAILNET_IP"
else
    fail "tailnet ping $TAILNET_IP"
fi

# --- 2. host facts over one SSH connection --------------------------------
REMOTE=$(cat <<'EOF'
echo "ssh_ok=true"
echo "uptime: $(uptime 2>/dev/null)"
echo "load: $(sysctl -n vm.loadavg 2>/dev/null | tr -d '{}')"
echo "cores: $(sysctl -n hw.ncpu 2>/dev/null)"
echo "temp_c: $(~/.local/bin/smctemp -c 2>/dev/null || echo unknown)"
echo "disk_free_gb: $(df -g / 2>/dev/null | tail -1 | awk '{print $4}')"
echo "tailscale: $(/Applications/Tailscale.app/Contents/MacOS/Tailscale status --self 2>/dev/null | head -1)"
echo "runner_agent_label: $(launchctl list 2>/dev/null | grep -c ai.chaba.runner-agent)"
echo "llm_worker_label: $(launchctl list 2>/dev/null | grep -c net.adanest.kk-llm-worker)"
echo "runner_agent_md5: $(md5 -q ~/.local/bin/runner-agent 2>/dev/null || echo unknown)"
echo "recent_gate_denials:"
tail -30 ~/.cache/kk-llm-worker/worker.log 2>/dev/null | grep 'gate deny' | tail -3
EOF
)
FACTS=$($SSH "$REMOTE" 2>&1)
case "$FACTS" in
    *ssh_ok=true*) pass "ssh to $HOST"; echo "$FACTS" | sed 's/^/      /' ;;
    *) fail "ssh to $HOST: $(echo "$FACTS" | head -1)" ;;
esac

# Interpret the host facts we actually got.
if echo "$FACTS" | grep -q '^ssh_ok=true'; then
  if echo "$FACTS" | grep -q '^cores: '; then
      CORES=$(echo "$FACTS" | sed -n 's/^cores: //p')
      [ "${CORES:-0}" -gt 0 ] 2>/dev/null \
          && pass "core count visible ($CORES)" \
          || fail "core count unknown ($CORES)"
  else
      warn "core count not read"
  fi
  if echo "$FACTS" | grep -q '^temp_c: '; then
      TEMP=$(echo "$FACTS" | sed -n 's/^temp_c: //p')
      case "$TEMP" in
          unknown) warn "CPU temperature unavailable" ;;
          *) awk -v t="$TEMP" 'BEGIN{exit !(t<=60)}' \
              && pass "CPU temp ${TEMP}C <= 60C" \
              || warn "CPU temp ${TEMP}C above 60C gate" ;;
      esac
  fi
  if echo "$FACTS" | grep -q '^disk_free_gb: '; then
      DISK=$(echo "$FACTS" | sed -n 's/^disk_free_gb: //p')
      [ "${DISK:-0}" -ge 20 ] 2>/dev/null \
          && pass "disk free ${DISK}GB >= 20GB" \
          || warn "disk free ${DISK}GB below 20GB gate"
  fi
  echo "$FACTS" | grep -q '^runner_agent_label: 1' \
      && pass "runner-agent launchd label loaded" \
      || warn "runner-agent launchd label not loaded"
  echo "$FACTS" | grep -q '^llm_worker_label: 1' \
      && pass "kk-llm-worker launchd label loaded" \
      || warn "kk-llm-worker launchd label not loaded"
  if echo "$FACTS" | grep -q '^recent_gate_denials:'; then
      DENIALS=$(echo "$FACTS" | sed -n '/^recent_gate_denials:/,$p' | grep -c 'gate deny')
      [ "$DENIALS" -eq 0 ] \
          && pass "no recent worker gate denials" \
          || warn "$DENIALS gate denials in last 30 worker passes"
  fi

  # --- 3. runner-agent drift (compare installed hash with this checkout) ----
  LOCAL_MD5=$(md5sum "$REPO/scripts/board/runner-agent.py" 2>/dev/null | cut -d' ' -f1)
  REMOTE_MD5=$(echo "$FACTS" | sed -n 's/^runner_agent_md5: //p')
  if [ -n "$LOCAL_MD5" ] && [ "$REMOTE_MD5" != "unknown" ] && [ -n "$REMOTE_MD5" ]; then
      [ "$LOCAL_MD5" = "$REMOTE_MD5" ] \
          && pass "runner-agent in sync ($LOCAL_MD5)" \
          || {
            warn "runner-agent drift: repo=$LOCAL_MD5 host=$REMOTE_MD5"
            info 'staged fix, run ON kk-mac: git -C ~/CascadeProjects/chaba pull && bash ~/CascadeProjects/chaba/scripts/devin/sync-runner-tools.sh --verbose ~/CascadeProjects/chaba && launchctl kickstart -k gui/$(id -u)/ai.chaba.runner-agent'
            info 'ansible deploy-runner-agent.yml excludes group macos — do not use it here; if the installed copy is newer than the repo copy the never-downgrade guard keeps it, so diff by hand first'
          }
  else
      warn "runner-agent hash comparison unavailable"
  fi
else
    info "host facts skipped (SSH unreachable)"
fi

# --- 4. heartbeat freshness and admission verdict -------------------------
BEAT=$(python3 - "$MDDB_URL" <<'PY' 2>&1
import json, sys, time, urllib.request
from datetime import datetime
url = sys.argv[1].rstrip('/') + '/search'
req = urllib.request.Request(url, data=json.dumps({
    'collection': 'ada-nest-heartbeats', 'query': '', 'limit': 100,
}).encode(), headers={'content-type': 'application/json'}, method='POST')
try:
    docs = json.load(urllib.request.urlopen(req, timeout=15))
except Exception as exc:
    print('BEAT_ERROR', type(exc).__name__, exc)
    raise SystemExit(0)
for d in docs if isinstance(docs, list) else []:
    try:
        b = json.loads(d.get('contentMd', '{}'))
    except (TypeError, ValueError):
        continue
    if b.get('host') in ('KKs-Mac-Studio', 'kk-mac', '192') or \
       b.get('tailnet_ip') == '100.108.217.17':
        if b.get('cpu_cores') in (None, 0):
            continue  # skip legacy alias docs without core counts
        try:
            age = round(time.time() - datetime.fromisoformat(
                str(b.get('ts', '')).replace('Z', '+00:00')).timestamp(), 1)
        except ValueError:
            age = -1
        print('BEAT', b.get('host'), age, b.get('ts'),
              b.get('load_1m'), b.get('cpu_cores'))
        break
else:
    print('BEAT_MISSING')
PY
)
case "$BEAT" in
    BEAT_ERROR*) fail "heartbeat query: $BEAT" ;;
    BEAT_MISSING) fail "no current kk-mac heartbeat with cpu_cores" ;;
    BEAT*) info "heartbeat: $BEAT";
           AGE=$(echo "$BEAT" | awk '{print $3}')
           awk -v a="$AGE" 'BEGIN{exit !(a<=900)}' \
               && pass "heartbeat age ${AGE}s <= 900s" \
               || fail "heartbeat age ${AGE}s stale" ;;
esac

SNAP=$(python3 "$REPO/scripts/devnest/kk_mac_admission.py" --url "$MDDB_URL" 2>&1)
echo "$SNAP" | sed 's/^/      /'
echo "$SNAP" | grep -q '"eligible": true' \
    && pass "admission snapshot eligible" \
    || fail "admission snapshot ineligible (see JSON reasons)"

if [ "$FAILED" -eq 0 ]; then
    echo "RESULT: OK — kk-mac lane ready for dispatch"
else
    echo "RESULT: NEEDS ATTENTION — see FAIL lines above"
fi
exit "$FAILED"
