#!/usr/bin/env bash
# verify.sh [host ...] — check nest-io on each host:
#   unit active · /health ok · selftest passes (tiers+route+broker)
set -uo pipefail
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc03)
PORT="${NEST_IO_PORT:-8795}"
rc_all=0

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname)" ] || [ "$host" = "localhost" ]; then
    RUN=""
  else
    RUN="ssh -o BatchMode=yes -o ConnectTimeout=8 $host"
  fi
  $RUN systemctl --user is-active nest-io.service >/dev/null 2>&1 \
    && echo "   unit: active" || { echo "   unit: NOT ACTIVE"; rc_all=1; }
  # /health — loopback bind, probe from the host itself
  $RUN curl -sf -m 5 "http://127.0.0.1:$PORT/health" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"   health: ok surfaces={d.get(\"surfaces\")} sessions_open={d.get(\"sessions_open\")} offline={d.get(\"offline\")}")' 2>/dev/null \
    || { echo "   health: FAILED :$PORT"; rc_all=1; }
  $RUN NEST_IO_STATE=/tmp/nest-io-verify NEST_IO_OFFLINE=1 python3 \
    ~/.local/share/nest/io-fabric/nest-io.py --selftest >/dev/null 2>&1 \
    && echo "   selftest: pass" || { echo "   selftest: FAILED"; rc_all=1; }
done
exit $rc_all
