#!/usr/bin/env bash
# verify.sh [host ...] — check the manager on each host:
#   unit active · manager-state.json exists with nodes · CMS page published
set -uo pipefail
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc03 tony-omen tony-dell)
MDDB="${MDDB_BASE_URL:-http://100.102.134.91:11023/v1}"
PY='import json;d=json.load(open("/home/tony/.local/share/nest/manager-state.json"));n=d.get("nodes",{});a=sorted(k for k,v in n.items() if v.get("adopted"));print(f"   state: {len(n)} nodes, {len(a)} adopted {a}")'
rc_all=0

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname)" ] || [ "$host" = "localhost" ]; then
    systemctl --user is-active nest-mgr.service >/dev/null 2>&1 \
      && echo "   unit: active" || { echo "   unit: NOT ACTIVE"; rc_all=1; }
    python3 -c "$PY" 2>/dev/null \
      || { echo "   state: MISSING manager-state.json"; rc_all=1; }
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
      'systemctl --user is-active nest-mgr.service' >/dev/null 2>&1 \
      && echo "   unit: active" || { echo "   unit: NOT ACTIVE"; rc_all=1; }
    ssh -o BatchMode=yes "$host" "python3 -c '$PY'" 2>/dev/null \
      || { echo "   state: MISSING manager-state.json"; rc_all=1; }
  fi

  page=$(curl -sf -m 10 -X POST "$MDDB/get" -H 'Content-Type: application/json' \
    -d "{\"collection\":\"ada-cms-pages\",\"key\":\"nest-$host\",\"lang\":\"en\"}" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print("ok" if d.get("key") else "missing")' 2>/dev/null)
  [ "$page" = "ok" ] && echo "   cms: nest-$host published" \
    || { echo "   cms: nest-$host MISSING"; rc_all=1; }
done
exit $rc_all
