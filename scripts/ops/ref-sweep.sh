#!/usr/bin/env bash
# ref-sweep.sh PATTERN [host...] — dependent-reference sweep.
#
# Before declaring a service moved/retired/renamed, sweep for lingering
# references to its old identity (host:port, path, unit name, URL) across:
#   1. the repo: scripts/ + docs/ssot/ (deploy targets, SSOT entries)
#   2. fleet units: ~/.config/systemd/user ExecStarts + ~/.local/bin
#   3. container quadlets: ~/.config/containers/systemd
#
# A hit doesn't prove breakage — it proves "something still references the
# old address; decide whether that's intended". The 2026-10-12 misses
# (deploy-card.sh still targeting dell for michael-dev; kanban-brief
# pointing at a nonexistent ollama) would each have been one ref-sweep line.
#
# Hosts default to the audit fleet; pass hosts to limit scope.
set -uo pipefail

PAT="${1:?usage: ref-sweep.sh PATTERN [host...]}"
shift || true
HOSTS=("$@")
if [ "${#HOSTS[@]}" -eq 0 ]; then
    HOSTS=(tony-dell tony-omen mn01 idc02 idc03 tony-macbook)
fi
REPO="${CHABA_REPO:-$HOME/CascadeProjects/chaba}"

echo "== repo ($REPO) =="
if command -v rg >/dev/null; then
    rg -n --no-heading -S "$PAT" "$REPO/scripts" "$REPO/docs/ssot" \
        "$REPO/stacks" 2>/dev/null | grep -vF "ref-sweep.sh" || echo "  (clean)"
else
    grep -rn "$PAT" "$REPO/scripts" "$REPO/docs/ssot" 2>/dev/null \
        | grep -vF "ref-sweep.sh" || echo "  (clean)"
fi

for h in "${HOSTS[@]}"; do
    echo "== $h =="
    ssh -o ConnectTimeout=8 -o BatchMode=yes "$h" \
        "grep -rln $(printf '%q' "$PAT") \
            ~/.config/systemd/user ~/.local/bin \
            ~/.config/containers/systemd 2>/dev/null" \
        2>/dev/null | sed 's/^/  /' || echo "  (unreachable)"
done
