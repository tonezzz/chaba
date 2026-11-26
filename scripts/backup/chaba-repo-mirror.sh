#!/usr/bin/env bash
# Nightly bare-mirror refresh for the idc02 chaba-repo-mirror.timer unit.
#
# The unit's ExecStart points here; the script itself was never committed and
# went missing on 2026-11-26 (exit 127, timer-alert-idc02-chaba-repo-mirror).
# The target mirror already exists at ~/backups/chaba-mirror.git with two
# remotes: origin (github) and idc03-served (the idc03 served checkout).
# Ref layout is preserved: refs/heads/*, refs/tags/*, refs/pull/* from
# github, refs/remotes/idc03-served/* from the served checkout.
set -euo pipefail

MIRROR="${CHABA_MIRROR_DIR:-$HOME/backups/chaba-mirror.git}"

if [ ! -d "$MIRROR" ]; then
    echo "chaba-repo-mirror: $MIRROR missing — refusing to create (preserve config)" >&2
    exit 1
fi

git --git-dir="$MIRROR" fetch --prune origin \
    '+refs/heads/*:refs/heads/*' \
    '+refs/tags/*:refs/tags/*' \
    '+refs/pull/*:refs/pull/*'

git --git-dir="$MIRROR" fetch --prune idc03-served \
    '+refs/heads/*:refs/remotes/idc03-served/*'

echo "chaba-repo-mirror: origin + idc03-served fetched -> $MIRROR"
