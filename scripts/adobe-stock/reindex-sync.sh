#!/usr/bin/env bash
# Rebuild Adobe Stock reuse indexes from gdrive campaigns and sync them to
# the idc02 ada-opencode workspace (OPS-1131 follow-up).
# Runs on tony-dell: needs rclone gdrive: remote + ssh idc02 + the vendored
# builder next to publish-previews.py. Idempotent; safe to run on a timer.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

python3 "$HERE/publish-previews.py" --reindex-only \
  --remote "${ADA_ADOBE_STOCK_REMOTE:-gdrive:ada-nest-adobe-stock}" \
  | tee "$WORK/reindex.json"

# publish-previews writes indexes inside its own tempdir; re-fetch from
# the remote so this script stays decoupled from its internals.
for f in assets campaigns prompt-patterns rejection-patterns; do
  rclone copyto "${ADA_ADOBE_STOCK_REMOTE:-gdrive:ada-nest-adobe-stock}/indexes/$f.json" "$WORK/$f.json"
  scp -q -o BatchMode=yes "$WORK/$f.json" \
    "idc02:.local/share/ada-opencode/workspace/.adobe-stock/indexes/$f.json"
done
echo "reindex-sync: indexes published to gdrive + synced to idc02 workspace"
