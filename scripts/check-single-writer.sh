#!/usr/bin/env bash
# check-single-writer — audit chaba checkouts against the single-writer rule
# (card kanban-commit-single-writer). Warn-only lint: prints a per-checkout
# report and always exits 0 unless --strict.
#
# Checks each checkout (default: ~/CascadeProjects/chaba* glob, override with
# CHABA_CHECKOUTS="dir dir ..."):
#   - uncommitted changes under docs/ssot/focus-inbox/  (only the SERVED
#     checkout is swept by kanban-commit.timer — elsewhere they stall)
#   - divergence vs upstream > CHABA_DIVERGENCE_N commits (default 10)
#   - pre-commit hook not armed (core.hooksPath unset)
#
# Uses last-fetched refs — no network. Run `git fetch` first for freshness.
#
# Usage: check-single-writer.sh [--strict] [--quiet]
set -uo pipefail

STRICT=0; QUIET=0
for a in "$@"; do
    case "$a" in
        --strict) STRICT=1 ;;
        --quiet|-q) QUIET=1 ;;
        *) echo "usage: check-single-writer.sh [--strict] [--quiet]" >&2; exit 2 ;;
    esac
done

SERVED="${CHABA_SERVED_CHECKOUT:-$HOME/CascadeProjects/chaba-tony-dell}"
N="${CHABA_DIVERGENCE_N:-10}"
CHECKOUTS="${CHABA_CHECKOUTS:-$HOME/CascadeProjects/chaba*}"
SERVED_REAL="$(realpath -m "$SERVED" 2>/dev/null || echo "$SERVED")"

warn=0
for d in $CHECKOUTS; do
    [ -e "$d" ] || continue
    git -C "$d" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
    top="$(git -C "$d" rev-parse --show-toplevel 2>/dev/null)"
    top_real="$(realpath -m "$top" 2>/dev/null || echo "$top")"
    branch="$(git -C "$d" branch --show-current 2>/dev/null || echo '?')"
    up="$(git -C "$d" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null \
         || echo origin/master)"
    counts="$(git -C "$d" rev-list --left-right --count "$up...HEAD" 2>/dev/null \
              || printf '0\t0')"
    behind="${counts%%[[:space:]]*}"; ahead="${counts##*[[:space:]]}"
    inbox_dirty="$(git -C "$d" status --porcelain -- docs/ssot/focus-inbox/ 2>/dev/null | wc -l)"
    hooks="$(git -C "$d" config core.hooksPath 2>/dev/null || echo '-')"
    tag=""; [ "$top_real" = "$SERVED_REAL" ] && tag=" [served]"

    msgs=()
    [ "$top_real" != "$SERVED_REAL" ] && [ "${inbox_dirty:-0}" -gt 0 ] \
        && msgs+=("$inbox_dirty uncommitted focus-inbox file(s) — not swept here")
    [ "${behind:-0}" -gt "$N" ] && msgs+=("$behind commits behind $up")
    { [ "$branch" = "master" ] && [ "${ahead:-0}" -gt "$N" ]; } \
        && msgs+=("$ahead unpushed commits on master")
    [ "$hooks" = "-" ] && msgs+=("no core.hooksPath (run scripts/install-hooks.sh)")

    if [ ${#msgs[@]} -gt 0 ]; then
        warn=1
        echo "WARN $top_real ($branch)$tag: ${msgs[*]}"
    elif [ $QUIET -eq 0 ]; then
        echo "ok   $top_real ($branch)$tag ahead=$ahead behind=$behind inbox_dirty=$inbox_dirty hooks=$hooks"
    fi
done
[ $STRICT -eq 1 ] && exit $warn
exit 0
