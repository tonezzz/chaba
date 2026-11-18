#!/usr/bin/env bash
# pull-report-metas.sh — collect producer meta*.yml files from every
# checkout that can hold them into this checkout's reports/ tree.
#
# reports/* is gitignored, so producer metas never travel via git — they
# stay on the host+checkout that produced them. The L3 renderer
# (report-system.py, job chaba-system-report on con01) reads only its
# local reports/, so without this pull every remote node resolved
# 'missing' (card report-graph-producer-metas-never-reach, 2026-11-18).
#
# Pull model (not push): producers keep writing to their own checkout;
# the single renderer harvests all of them. This is robust to stale
# push-back targets — several producers still scp metas to the OLD
# served checkout (tony-dell:chaba-tony-dell) or the idc02 exec
# checkout; both are in the source list below.
#
#   rsync -u: newest mtime wins — a frozen copy can never overwrite a
#   fresher local meta. All failures are soft (|| true): an unreachable
#   host must not block the render — the node just shows its last seen
#   state, which is the report's whole point.
#
# Renderer-owned metas are excluded (report-system.py writes them itself
# moments later; a foreign render must not shadow them).
#
# Sources: every reports/ dir known to receive producer metas. Add new
# producer checkouts here when jobs land on new hosts/roots.

set -uo pipefail

REPO="${CHABA_REPO:-$HOME/CascadeProjects/chaba}"
REPORTS="$REPO/reports"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=6"

# host:reports-dir — relative to the remote $HOME.
SOURCES=(
  # served checkout (writer since OPS-0725): nest/*, disk-trend,
  # overnight-assessment, kanban, model-bench push-backs land here
  "idc03:CascadeProjects/chaba-tony-dell/reports"
  # idc03 exec checkout: daily-brief.timer writes here
  "idc03:CascadeProjects/chaba/reports"
  # kanban-sync detached worktree: reports/kanban/meta.yml legacy writes
  "idc03:CascadeProjects/chaba-kanban-sync/reports"
  # idc02 exec checkout: host-loads sampler, audit suite local copies,
  # route-health + systemwide-assessment + model-bench scp targets
  "idc02:CascadeProjects/chaba/reports"
  "idc02:CascadeProjects/chaba-tony-dell/reports"
  # OLD served (frozen mirror): run-and-ship.sh audits, report-feed,
  # route-health, cms-reflect push-backs still land here
  "tony-dell:CascadeProjects/chaba-tony-dell/reports"
  # dell exec checkout: overnight/audit leftovers, ha-auth
  "tony-dell:CascadeProjects/chaba/reports"
  # omen exec checkout: model-bench local copy, gh-runs, ai-edge
  "tony-omen:CascadeProjects/chaba/reports"
  # mn01 — no known producers today; cheap to include
  "mn01:CascadeProjects/chaba/reports"
  "mn01:CascadeProjects/chaba-tony-dell/reports"
  # idc01 warm-DR (usually unreachable — bounded cost, self-heals)
  "idc01:CascadeProjects/chaba-vault/reports"
)

mkdir -p "$REPORTS"
updated=0
for src in "${SOURCES[@]}"; do
  host="${src%%:*}"; dir="${src#*:}"
  out=$(rsync -azu --timeout=20 -e "$SSH" \
        --include='*/' \
        --exclude='meta.system-report.yml' \
        --exclude='meta.focus-inbox.yml' \
        --include='meta*.yml' \
        --exclude='*' \
        --out-format='%n' \
        "$host:$dir/" "$REPORTS/" 2>/dev/null)
  rc=$?
  if [ $rc -eq 0 ] && [ -n "$out" ]; then
    n=$(printf '%s\n' "$out" | grep -c '\.yml$' || true)
    updated=$((updated + n))
    [ "$n" -gt 0 ] && echo "pull: $host:$dir -> +$n meta(s)"
  elif [ $rc -ne 0 ]; then
    echo "pull: $host unreachable/failed (rc=$rc) — skipped" >&2
  fi
done

# health-monitor writes OUTSIDE the repo (registry meta:
# ~/var/chaba/health/meta.yml — producer = tony-dell-monitor.timer on
# tony-dell). Mirror it to the same absolute path this checkout resolves.
mkdir -p "$HOME/var/chaba/health"
rsync -azu --timeout=20 -e "$SSH" \
  "tony-dell:var/chaba/health/meta.yml" \
  "$HOME/var/chaba/health/meta.yml" 2>/dev/null \
  || echo "pull: tony-dell health meta failed — skipped" >&2

echo "pull-report-metas: done ($updated meta file(s) updated)"
exit 0
