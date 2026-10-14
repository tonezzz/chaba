#!/usr/bin/env bash
# rename-ada-voice.sh — per-host executor for the ada-pi -> ada-voice rename
# (kanban ada-pi-rename-ada-voice, Tony-approved 2026-10-14).
#
# Already done fleet-wide before this runs:
#   * GitHub repo tonezzz/ada-pi -> tonezzz/ada-voice (redirects live)
#   * origin remotes re-pointed to ada-voice.git on every checkout
#   * forward symlink ~/CascadeProjects/ada-voice -> ada-pi (gap bridge)
#   * repos.conf: canonical ada-voice + legacy ada-pi alias (dell, macbook)
#   * ada-voice self-sweep on origin branch dispatch/20261014-ada-voice-self-sweep
#   * chaba sweep commit (BUILTIN_REPOS + REPO_TESTS carry ada-pi aliases)
#
# This script performs the remaining step per host: swap the symlink for
# the real dir, drop a back-compat symlink ada-pi -> ada-voice so nothing
# in-flight or un-patched breaks, rewrite worktree .git pointers and
# systemd units to the canonical path.
#
#   rename-ada-voice.sh status                 # fleet state table
#   rename-ada-voice.sh run <host|all>         # per-host rename (quiet-gated)
#   rename-ada-voice.sh run <host|all> --force # skip the in-flight gate
#
# Quiet gate: refuses while a devin-task unit runs whose meta.json repo is
# ada-pi/ada-voice on that host. The mv+symlink pair is symlink-safe in
# principle (worktree gitdir pointers resolve through the compat symlink),
# but the card's sequencing gate stands unless --force is given.
set -euo pipefail

HOSTS="tony-dell idc02 idc03 tony-omen tony-macbook mn01"

remote_script() { cat <<'EOS'
set -u
cd "$HOME/CascadeProjects" || exit 9

is_real()    { [ -d "$1" ] && [ ! -L "$1" ]; }
is_real ada-pi    && have_old=1 || have_old=0
is_real ada-voice && have_new=1 || have_new=0
[ -L ada-voice ] && new_is_link=1 || new_is_link=0
[ -L ada-pi ]    && old_is_link=1 || old_is_link=0

inflight=""
for m in "$HOME"/.local/share/devin-dispatch/tasks/*/meta.json; do
  [ -f "$m" ] || continue
  d=$(dirname "$m")
  [ -f "$d/exit_code" ] && continue
  r=$(python3 -c "import json;print(json.load(open('$m')).get('repo',''))" 2>/dev/null)
  case "$r" in ada-pi|ada-voice) inflight="$inflight $(basename "$d")";; esac
done

if [ "$MODE" = check ]; then
  echo "old_dir=$have_old new_dir=$have_new new_link=$new_is_link old_link=$old_is_link inflight:${inflight:- none}"
  exit 0
fi

if [ "$have_new" = 1 ] && [ "$have_old" = 0 ]; then
  echo "already renamed"; exit 0
fi
if [ "$have_old" = 0 ]; then
  echo "ERROR: no ada-pi checkout present"; exit 3
fi
if [ -n "$inflight" ] && [ "$FORCE" != 1 ]; then
  echo "REFUSED: ada dispatches in flight:$inflight (re-run when quiet, or --force)"
  exit 4
fi

[ "$new_is_link" = 1 ] && rm ada-voice      # drop the forward bridge
mv ada-pi ada-voice
ln -s ada-voice ada-pi                      # back-compat: old paths resolve

# worktree .git gitdir pointers -> canonical path (dispatch-wt-*, ada-wt-*,
# any linked worktree living as a sibling dir)
fixed=0
for g in "$HOME"/CascadeProjects/*/.git; do
  [ -f "$g" ] || continue
  if grep -q "CascadeProjects/ada-pi" "$g"; then
    sed -i 's|CascadeProjects/ada-pi|CascadeProjects/ada-voice|g' "$g"
    fixed=$((fixed+1))
  fi
done
git -C ada-voice worktree list >/dev/null 2>&1 || true

git -C ada-voice remote set-url origin https://github.com/tonezzz/ada-voice.git 2>/dev/null || true

RC="$HOME/.local/share/devin-dispatch/repos.conf"
if [ -f "$RC" ]; then
python3 - "$RC" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]); out=[]
for ln in p.read_text().splitlines():
    s = ln.split("#",1)[0].split()
    if s and s[0] in ("ada-pi","ada-voice"):
        continue
    out.append(ln)
out.append("ada-voice     /home/tony/CascadeProjects/ada-voice                main")
out.append("ada-pi        /home/tony/CascadeProjects/ada-voice                main   # legacy alias — remove when no ada-pi cards remain")
p.write_text("\n".join(out)+"\n")
PY
fi

units=$(grep -rl "CascadeProjects/ada-pi" "$HOME/.config/systemd/user" /etc/systemd/system 2>/dev/null || true)
nu=0
for u in $units; do sed -i 's|CascadeProjects/ada-pi|CascadeProjects/ada-voice|g' "$u"; nu=$((nu+1)); done
[ "$nu" -gt 0 ] && systemctl --user daemon-reload 2>/dev/null || true

head=$(git -C ada-voice rev-parse --short HEAD 2>/dev/null || echo "?")
echo "OK ada-voice@$head wt-fixes=$fixed units-patched=$nu compat-link=ada-pi"
EOS
}

run_on() {  # <host> <MODE> <FORCE>
  local h="$1" mode="$2" force="$3"
  if [[ "$h" == "tony-dell" || "$h" == "$(hostname)" ]]; then
    MODE="$mode" FORCE="$force" bash -s < <(remote_script)
  else
    timeout 60 ssh -o BatchMode=yes -o ConnectTimeout=6 "$h" \
      "MODE='$mode' FORCE='$force' bash -s" < <(remote_script)
  fi
}

cmd="${1:-status}"; host="${2:-all}"; flag="${3:-}"
force=0; [ "$flag" = --force ] && force=1

case "$cmd" in
  status)
    for h in $HOSTS; do
      printf '%-14s ' "$h"
      run_on "$h" check 0 2>&1 | head -3 || echo "unreachable"
    done
    ;;
  run)
    hosts=$([ "$host" = all ] && echo "$HOSTS" || echo "$host")
    for h in $hosts; do
      echo "=== $h ==="
      run_on "$h" run "$force" || echo "$h: failed/unreachable"
    done
    cat <<'EOF'

next steps after a host renames:
  1. merge origin/dispatch/20261014-ada-voice-self-sweep into ada-voice main,
     then per host: git -C ~/CascadeProjects/ada-voice pull --ff-only
  2. re-install deploy-ada.sh from the renamed checkout:
       install -m0755 ~/CascadeProjects/ada-voice/scripts/deploy-ada.sh ~/.local/bin/
  3. verify (card): dispatch claim on ada-voice, deploy-ada.sh idc03 green,
     tool-lint + pytest on the prod checkout
  4. retire the ada-pi compat symlink + repos.conf alias once clean
EOF
    ;;
  *) echo "usage: $0 status | run <host|all> [--force]" >&2; exit 2 ;;
esac
