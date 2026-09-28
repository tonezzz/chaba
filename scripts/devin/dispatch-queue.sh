#!/usr/bin/env bash
# dispatch-queue — drain a TSV of `repo<TAB>task` rows through
# devin-dispatch with a concurrency cap on devin-task-* units.
# tony-dell is RAM-tight: never more than CAP agent sessions at once.
#
#   dispatch-queue.sh <spec.tsv> [cap]    run the drain (foreground —
#                                        wrap in job-run to background it)
# TSV row:  chaba<TAB>Do the thing, referencing prior session <sid>.
#
# Typical:  job-run start drain-x "drain N specs" -- \
#             ssh tony-dell-lan 'bash ~/.local/bin/dispatch-queue /tmp/q.tsv 3'
set -u
TSV="${1:?spec tsv required}"; CAP="${2:-3}"
BIN="${DEVIN_DISPATCH:-$HOME/.local/bin/devin-dispatch}"
active() { systemctl --user list-units 'devin-task-*' --state=active \
    --no-legend 2>/dev/null | wc -l; }
while IFS=$'\t' read -r repo task; do
  [ -n "${repo:-}" ] || continue
  while [ "$(active)" -ge "$CAP" ]; do sleep 45; done
  id=$(DISPATCH_PERMISSION_MODE="${DISPATCH_PERMISSION_MODE:-dangerous}" \
       "$BIN" start "$repo" "$task") \
    && echo "dispatched $id ($repo)" \
    || echo "FAILED dispatch: $repo ${task:0:60}"
  sleep 5
done < "$TSV"
echo "queue drained: $(grep -c . "$TSV") task(s) dispatched"
