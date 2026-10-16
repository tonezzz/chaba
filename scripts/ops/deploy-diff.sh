#!/usr/bin/env bash
# deploy-diff.sh — "what version is deployed where, and what's the drift?"
#
# Answers the three questions that keep burning us:
#   1. checkout HEAD vs origin/main  (ahead/behind — stranded commits, stale deploys)
#   2. working tree dirty?           (uncommitted edits on a live checkout)
#   3. running service vs HEAD       (process started before the last deploy = stale runtime)
#
# Usage:
#   deploy-diff.sh              # all known deploy points (ssh matrix below)
#   deploy-diff.sh idc03        # one host only
#   deploy-diff.sh --local /path/to/repo [unit-name ...]   # local checkout
#
# Matrix rows: host | repo path | space-separated units running from it.
# Edit DEPLOY_POINTS when the fleet changes. Reads only — never mutates.

set -u

DEPLOY_POINTS="
idc03|~/CascadeProjects/ada-voice|ada-ha-tony.service ada-ai-kraut.service ada-pi-pwa.service ada-dev.service ada-kk.service ada-kk-dev.service ada-line-relay.service ada-tg-relay.service
idc03|~/CascadeProjects/chaba|
tony-dell|~/CascadeProjects/ada-voice|
tony-dell|~/CascadeProjects/chaba-tony-dell|chaba-board-api.service chaba-monitoring-dashboard.service
tony-dell|~/CascadeProjects/chaba|
idc02|~/CascadeProjects/ada-voice|
tony-macbook|~/CascadeProjects/chaba|
tony-macbook|~/CascadeProjects/ada-pi|
"

probe_host() { # host relpath units
  # ssh joins remote args on spaces — an empty $3 would vanish, so send "-" for none
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$1" bash -s -- "$2" "${3:--}" <<'EOF' 2>&1
set -u
RP="$1"; shift; UNITS="$*"; [ "$UNITS" = "-" ] && UNITS=""
D=$(eval echo "$RP")
if [ ! -d "$D/.git" ] && ! git -C "$D" rev-parse --git-dir >/dev/null 2>&1; then
  echo "MISSING|$RP (no git repo)"; exit 0
fi
cd "$D" || { echo "ERR|cd $RP"; exit 0; }
git fetch origin --quiet 2>/dev/null
HEAD=$(git rev-parse --short HEAD 2>/dev/null)
BR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
DEF=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|.*/||'); DEF=${DEF:-main}
AB=$(git rev-list --left-right --count origin/$DEF...HEAD 2>/dev/null | awk '{print "behind="$1" ahead="$2}')
DIRTY=$(git status --porcelain 2>/dev/null | wc -l)
echo "REPO|$D|$BR|$HEAD|origin/$DEF $AB|dirty=$DIRTY"
# batched start timestamps FIRST (fmt_host needs the map before UNIT rows)
if [ -n "$UNITS" ]; then
  last_id=""; last_ts=""
  timeout 15 systemctl --user show $UNITS -p Id -p ExecMainStartTimestamp </dev/null 2>/dev/null | while IFS='=' read -r k v; do
    case "$k" in
      Id) last_id=$v; [ -n "$last_ts" ] && { echo "UTS|$last_id|$last_ts"; last_ts=""; last_id=""; };;
      ExecMainStartTimestamp) last_ts=$v; [ -n "$last_id" ] && { echo "UTS|$last_id|$last_ts"; last_ts=""; last_id=""; };;
    esac
  done
fi
for u in $UNITS; do
  st=$(timeout 8 systemctl --user is-active "$u" </dev/null 2>/dev/null)
  echo "UNIT|$u|${st:-missing}"
done
EOF
}

fmt_host() { # host
  local host=$1
  echo "### $host"
  declare -A ts=()
  while IFS='|' read -r kind a b c d e; do
    case "$kind" in
      UTS) [ -n "$a" ] && ts[$a]=$b;;
      REPO) printf "  %-52s on %s @ %s  (%s, %s)\n" "$a" "$b" "$c" "$d" "$e";;
      UNIT) printf "    └─ %-32s %-10s since %s\n" "$a" "$b" "${ts[$a]:-?}";;
      MISSING|ERR) echo "  !! $a $b";;
      *) [ -n "$kind" ] && echo "  ? $kind $a";;
    esac
  done
}

if [ "${1:-}" = "--local" ]; then
  D="$2"; shift 2
  probe_host localhost "$D" "$*"; exit $?
fi

ONLY="${1:-}"
echo "$DEPLOY_POINTS" | while IFS='|' read -r host repo units; do
  [ -z "$host" ] && continue
  [ -n "$ONLY" ] && [ "$host" != "$ONLY" ] && continue
  probe_host "$host" "$repo" "$units" | fmt_host "$host"
done
