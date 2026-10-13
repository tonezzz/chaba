#!/usr/bin/env bash
# run-and-ship.sh — run an audit command, then rsync report metas to the
# served checkout so report-system.py sees fresh node state.
#
# reports/* is gitignored, so metas written by producers on satellite hosts
# (idc02 audit suite) never propagate via git — without this ship step the
# system report reads them as permanently stale.
#
# Usage: run-and-ship.sh <cmd...>   (exit code = the audit command's rc)
set -uo pipefail

REPO="$HOME/CascadeProjects/chaba"
SERVED="tony-dell:CascadeProjects/chaba-tony-dell/reports"

"$@"
rc=$?

# audits/ tree (metas + summaries) + top-level meta.*.yml files.
rsync -a "$REPO/reports/audits/" "$SERVED/audits/" 2>/dev/null || true
rsync -a --include='meta.*.yml' --include='meta.yml' --exclude='*' \
  "$REPO/reports/" "$SERVED/" 2>/dev/null || true

exit "$rc"
