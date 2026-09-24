#!/usr/bin/env bash
# Deploy ada-pi to a runtime host. Runtime checkouts are read-only consumers
# of origin/main — this fails fast instead of merging or hiding divergence.
#
#   - branch must be main, tracking origin/main, tree clean
#   - pull is --ff-only; a diverged checkout stops with instructions
#   - services restart only when Python code or requirements changed
#     (pwa/ + frontend/ are served from disk; no restart needed)
#   - inactive services are reported, never started silently
#   - flock prevents concurrent deploys to the same host
#
# Usage: deploy-ada.sh <mn01|tony-dell|idc01|all> [--restart]
set -euo pipefail

target="${1:-}"; force_restart="${2:-}"

case "$target" in
  mn01)      hosts=(mn01) ;;
  tony-dell) hosts=(tony-dell) ;;
  idc01)     hosts=(idc01) ;;
  all)       hosts=(mn01 tony-dell idc01) ;;
  *) echo "usage: $0 <mn01|tony-dell|idc01|all> [--restart]" >&2; exit 2 ;;
esac

host_config() {
  # Comma-separated — ssh joins remote args with spaces, so space-separated
  # lists would arrive as multiple args and silently drop every service but
  # the first (the ada-ha-michael-never-restarts bug).
  case "$1" in
    mn01)      echo "ada-ha-tony.service,ada-ha-michael.service|8002,8003" ;;
    tony-dell) echo "chaba-guest.service|8014" ;;
    idc01)     echo "ada-pi-pwa.service,ada-ha-tony.service,ada-ha-michael.service|8001,8002,8003" ;;
  esac
}

EVENT_LOG=/home/tony/.config/home-assistant/scripts/chaba-event-log.py

emit_event() {  # best-effort chaba-admin Events feed entry; never fails the deploy
  local host="$1" out="$2" status="${3:-ok}"
  local line title payload
  line=$(grep -m1 -E '^(updated|already at)' <<< "$out" || true)
  if [[ "$status" == ok ]]; then
    title="ada deploy $host: ${line:-done}"
  else
    title="ada deploy $host FAILED"
  fi
  payload=$(OUT="${out: -2000}" TITLE="$title" STATUS="$status" python3 -c '
import json, os
print(json.dumps({"title": os.environ["TITLE"], "category": "deploy",
                  "source": "deploy-ada.sh",
                  "severity": "info" if os.environ["STATUS"] == "ok" else "fail",
                  "requires_response": os.environ["STATUS"] != "ok",
                  "body": os.environ["OUT"]}))')
  printf '%s' "$payload" | ssh -o ConnectTimeout=8 -o BatchMode=yes tony-dell "python3 $EVENT_LOG add -" >/dev/null 2>&1 || true
}

# Render the memory-bank registry once; per-host we compare and ship it.
# Services read it at startup, so a drifted file forces a restart.
script_dir="$(cd "$(dirname "$0")" && pwd)"
python3 "$script_dir/ada/render-memory-banks.py" >/dev/null
local_banks_sum=$(md5sum ~/.config/ada/memory-banks.json | cut -d' ' -f1)

for host in "${hosts[@]}"; do
  cfg="$(host_config "$host")"
  services="${cfg%%|*}"; ports="${cfg##*|}"
  echo "=== $host ==="
  remote_banks_sum=$(ssh "$host" 'md5sum ~/.config/ada/memory-banks.json 2>/dev/null | cut -d" " -f1' || true)
  if [[ "$remote_banks_sum" != "$local_banks_sum" ]]; then
    python3 "$script_dir/ada/render-memory-banks.py" --host "$host"
    force_restart="--restart"   # banks file changed — restart regardless of code drift
  fi
  (
    flock -n 9 || { echo "FAIL: another deploy to $host holds the lock"; exit 1; }
    if out="$(ssh "$host" bash -s -- "$services" "$ports" "$force_restart" <<'REMOTE'
set -euo pipefail
# Args arrive comma-joined (ssh arg joining makes space-separated lists unsafe).
IFS=',' read -ra svcs <<< "$1"; IFS=',' read -ra prts <<< "$2"; force="${3:-}"
cd "$HOME/CascadeProjects/ada-pi"

branch=$(git branch --show-current)
[[ "$branch" == main ]] || { echo "FAIL: on branch $branch (expected main)"; exit 1; }
upstream=$(git rev-parse --abbrev-ref '@{u}' 2>/dev/null || true)
[[ "$upstream" == "origin/main" ]] || {
  echo "FAIL: main tracks ${upstream:-nothing} (expected origin/main)."
  echo "  fix: git branch --set-upstream-to=origin/main main"
  exit 1
}
[[ -z "$(git status --porcelain)" ]] || { echo "FAIL: dirty tree:"; git status --short; exit 1; }

before=$(git rev-parse HEAD)
git fetch -q origin
git pull --ff-only -q || {
  echo "FAIL: cannot fast-forward — local commits diverged from origin/main."
  echo "  inspect: ssh <host> 'cd ~/CascadeProjects/ada-pi && git log --oneline origin/main..HEAD'"
  exit 1
}
after=$(git rev-parse HEAD)

if [[ "$before" == "$after" && "$force" != "--restart" ]]; then
  echo "already at ${after:0:7} — nothing to pull"
else
  echo "updated ${before:0:7} -> ${after:0:7}"
fi

changed=""
[[ "$before" != "$after" ]] && changed=$(git diff --name-only "$before" "$after")
[[ -n "$changed" ]] && { echo "changed files:"; echo "$changed" | sed 's/^/  /'; }

needs_restart=0
[[ "$force" == "--restart" ]] && needs_restart=1
grep -qE '\.py$|requirements\.txt' <<< "$changed" && needs_restart=1

i=0
for svc in "${svcs[@]}"; do
  i=$((i+1)); port="${prts[$((i-1))]:-}"
  if [[ $needs_restart == 1 ]]; then
    if systemctl --user is-active --quiet "$svc"; then
      systemctl --user restart "$svc"
      echo "  $svc: restarted"
    else
      echo "  $svc: inactive — left stopped"
      continue
    fi
  fi
  sleep 1
  state=$(systemctl --user is-active "$svc" 2>/dev/null || true)
  http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$port/api/auth/status" 2>/dev/null || echo 000)
  echo "  $svc: $state (auth/status http $http)"
done
REMOTE
    )"; then rc=0; else rc=$?; fi
    echo "$out"
    emit_event "$host" "$out" "$( [[ $rc == 0 ]] && echo ok || echo fail)"
    [[ $rc == 0 ]] || exit "$rc"
  ) 9>"/tmp/ada-deploy-$host.lock"
done
