#!/usr/bin/env bash
# sync-runner-tools — converge the ~/.local/bin dispatch snapshots with
# the repo checkout that just pulled.
#
# The installed copies are verbatim single-file deploys:
#
#   scripts/board/runner-agent.py        -> ~/.local/bin/runner-agent
#   scripts/devin/devin-dispatch.sh      -> ~/.local/bin/devin-dispatch
#   scripts/devin/claude-dispatch.sh     -> ~/.local/bin/claude-dispatch
#   scripts/devin/devin-dispatch-prune.sh-> ~/.local/bin/devin-dispatch-prune
#   scripts/devin/dispatch-queue.sh      -> ~/.local/bin/dispatch-queue
#   scripts/board/dispatch_repos.py      -> ~/.local/bin/dispatch_repos.py
#                                          (update-only: when present it
#                                          shadows the checkout copy in
#                                          runner-agent.dr_module())
#
# Nothing converged them when master moved — they drifted until a manual
# scp (OPS-1026; card runner-tooling-drift-recurs-installed-ru-3aad1e:
# the 2026-11-18 wave of "installed runner-agent drifted" deferrals and
# kanban-sync's devin-dispatch e5b401a3-vs-71a2c265 warnings). git-safe-pull
# calls this at the end of every tick, so chaba-repo-sync.timer heals
# drift within one sync cycle on every host with a canonical checkout.
# runner-agent's _self_update() stays the faster path for its own file.
#
# Rules:
#   * src sha != pinned sha     -> warn + skip (a tool change must bump its
#                                  pin in runner-tooling.manifest.json in
#                                  the SAME commit — never hot-patch a pin
#                                  on a host to make a sync go through)
#   * dest identical            -> skip
#   * dest differs, src clean   -> syntax-check src, install -m 0755
#   * dest newer-mtime + differs-> warn + keep (never downgrade — a manual
#                                  hotfix snapshot beats a stale repo;
#                                  the same guard _self_update carries)
#   * dest missing              -> install only for runner-agent and
#                                  devin-dispatch, and only when the host
#                                  shows provisioning evidence (systemd
#                                  user unit / LaunchAgent / DISPATCH_DIR)
#                                  — never bootstrap a runner on a plain
#                                  checkout
#   * repos.conf                -> NEVER overwritten (per-host tables are
#                                  legitimate — kk-mac ships chaba-only);
#                                  a differing repo set is reported.
#
# Caller contract: best-effort — prints `sync-runner-tools:` lines and
# always exits 0 so a sync hiccup can never fail the pull. Run it
# directly with --verbose for the full decision log.
#
# Env: SYNC_RUNNER_TOOLS_FORCE=1  skip the canonical-checkout guard
#      SYNC_RUNNER_TOOLS=0        disable entirely (host opt-out)

set -uo pipefail

REPO="${1:-$PWD}"
VERBOSE=0
[ "${1:-}" = "--verbose" ] && { VERBOSE=1; REPO="${2:-$PWD}"; }

say()  { echo "sync-runner-tools: $*"; }
info() { [ "$VERBOSE" = 1 ] && say "ok: $*" || true; }
warn() { say "WARN: $*" >&2; }

[ "${SYNC_RUNNER_TOOLS:-1}" = "0" ] && { info "disabled via SYNC_RUNNER_TOOLS=0"; exit 0; }

# Canonical-checkout guard — only the real fleet checkouts may feed
# ~/.local/bin. A dispatch worktree (~/CascadeProjects/dispatch-wt-*)
# running git-safe-push from a feature branch must never install branch
# code over the host's tools.
TOP="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null || true)"
case "$TOP" in
    "$HOME/CascadeProjects/chaba"|"$HOME/CascadeProjects/chaba-tony-dell") ;;
    *)  if [ "${SYNC_RUNNER_TOOLS_FORCE:-0}" != "1" ]; then
            info "not a canonical checkout ($TOP) — skipped"
            exit 0
        fi ;;
esac

BIN="$HOME/.local/bin"
DISPATCH_DIR="${DISPATCH_DIR:-$HOME/.local/share/devin-dispatch}"

# Content pins — a tool can only be installed when the checkout copy is
# byte-identical to the hash committed alongside it. This is the gate that
# stops a half-purge (or a dirty local edit) from being propagated fleet-wide
# by this very script. Read once; a missing/unreadable manifest fails closed.
MANIFEST="$REPO/scripts/devin/runner-tooling.manifest.json"
PINS="$(python3 - "$MANIFEST" <<'PY' 2>/dev/null || true
import json, sys
try:
    for key, val in json.load(open(sys.argv[1])).get("tools", {}).items():
        print("%s\t%s\t%s" % (key, val.get("source", ""), val.get("sha256", "")))
except Exception:
    pass
PY
)"
[ -n "$PINS" ] || warn "no usable content pins in $MANIFEST — all tool syncs skipped until fixed"

_pinned_sha() {
    local rel="$1" key src sha
    while IFS=$'\t' read -r key src sha; do
        [ "$src" = "$rel" ] && { printf '%s' "$sha"; return 0; }
    done <<< "$PINS"
    return 1
}

# src is safe to install: exists, not dirty in the checkout, parses.
_src_ok() {
    local src="$1" rel="$2"
    [ -f "$src" ] || return 1
    # uncommitted local edits must not leak into ~/.local/bin
    [ -n "$(git -C "$REPO" status --porcelain -- "$rel" 2>/dev/null)" ] \
        && { warn "$rel dirty in checkout — skipped"; return 1; }
    case "$src" in
        *.py) python3 -c 'import sys;compile(open(sys.argv[1]).read(),sys.argv[1],"exec")' "$src" 2>/dev/null ;;
        *)    bash -n "$src" 2>/dev/null ;;
    esac || { warn "$rel fails syntax check — skipped"; return 1; }
    return 0
}

# provisioning evidence for a missing-dest install
_provisioned() {
    local name="$1"
    case "$name" in
        runner-agent)
            [ -e "$HOME/.config/systemd/user/runner-agent.service" ] \
            || [ -e "$HOME/.config/systemd/user/runner-agent.timer" ] \
            || [ -e "$HOME/Library/LaunchAgents/ai.chaba.runner-agent.plist" ] \
            || [ -d "$HOME/.local/share/runner-agent" ] ;;
        devin-dispatch)
            [ -d "$DISPATCH_DIR" ] && return 0
            local f
            for f in "$HOME"/.config/systemd/user/devin-dispatch-*; do
                [ -e "$f" ] && return 0
            done
            return 1 ;;
        *) return 1 ;;   # leaf tools: update-only, never auto-bootstrap
    esac
}

_sync_one() {
    local rel="$1" dest="$2"
    local src="$REPO/$rel" name
    name="$(basename "$dest")"
    _src_ok "$src" "$rel" || return 0
    local want got
    want="$(_pinned_sha "$rel")" || { warn "$rel has no content pin — skipped"; return 0; }
    got="$(sha256sum "$src" 2>/dev/null | awk '{print $1}')"
    if [ "$got" != "$want" ]; then
        warn "$rel sha $got != pinned $want — source/manifest mismatch, skipped (bump the pin in the same commit; never hand-edit the manifest on a host)"
        return 0
    fi
    if [ ! -e "$dest" ]; then
        if _provisioned "$name"; then
            install -m 0755 "$src" "$dest" \
                && say "installed $dest (was missing)" \
                || warn "install $dest failed"
        else
            info "$dest absent, no provisioning evidence — skipped"
        fi
        return 0
    fi
    cmp -s "$src" "$dest" && { info "$name current"; return 0; }
    if [ "$dest" -nt "$src" ]; then
        warn "$dest differs AND is newer than the repo copy — keeping installed (manual hotfix? never-downgrade guard)"
        return 0
    fi
    install -m 0755 "$src" "$dest" \
        && say "refreshed $dest (drifted from repo)" \
        || warn "install $dest failed"
}

_sync_one "scripts/board/runner-agent.py"         "$BIN/runner-agent"
_sync_one "scripts/devin/devin-dispatch.sh"       "$BIN/devin-dispatch"
_sync_one "scripts/devin/claude-dispatch.sh"      "$BIN/claude-dispatch"
_sync_one "scripts/devin/devin-dispatch-prune.sh" "$BIN/devin-dispatch-prune"
_sync_one "scripts/devin/dispatch-queue.sh"       "$BIN/dispatch-queue"
_sync_one "scripts/board/dispatch_repos.py"       "$BIN/dispatch_repos.py"

# --- repos.conf audit (card: audit dispatch_repos.conf drift in the same
# pass). The table is per-host — reported, never rewritten.
_repos_names() {  # -> sorted "name branch" rows, comments/blank stripped
    grep -v '^[[:space:]]*#' "$1" 2>/dev/null | grep -v '^[[:space:]]*$' \
        | awk '{print $1, $3}' | sort -u
}

CONF_SRC="$REPO/scripts/devin/dispatch-repos.conf"
CONF_DEST="$DISPATCH_DIR/repos.conf"
if [ -f "$CONF_SRC" ]; then
    if [ ! -e "$CONF_DEST" ]; then
        [ -d "$DISPATCH_DIR" ] \
            && say "repos.conf absent under $DISPATCH_DIR — devin-dispatch builtin table in use (sync scripts/devin/dispatch-repos.conf if this host dispatches the full set)" \
            || info "no dispatch dir — repos.conf audit skipped"
    else
        _diff="$(diff <(_repos_names "$CONF_SRC") <(_repos_names "$CONF_DEST") 2>/dev/null || true)"
        if [ -n "$_diff" ]; then
            say "repos.conf repo set differs from canonical (per-host tables are legal — review only):"$'\n'"$_diff"
        else
            info "repos.conf matches canonical repo set"
        fi
    fi
fi

exit 0
