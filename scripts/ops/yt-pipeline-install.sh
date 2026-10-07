#!/usr/bin/env bash
# yt-pipeline-install.sh — install the yt-live/yt-dub pipeline scripts
# from chaba scripts/ops/ into ~/.local/bin.
#
# Default copies the files: installed copies work standalone because the
# scripts resolve siblings (yt-vtt-translate.py, yt-live.sh, yt-vtt-dub.py)
# from their own directory first.
#   --link [repo_dir]  creates symlinks into a checkout instead — a single
#   live source for iterating. Only link to a checkout that persists
#   (~/CascadeProjects/chaba); NEVER a dispatch worktree — it gets cleaned.
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin"
FILES="yt-live.sh yt-live-api.py yt-vtt-dub.py yt-vtt-translate.py yt-cast-detect.py yt-whisper-vtt.py yt-diarize.py yt-diarize-remote.sh"
LINK=0; SRC="$HERE"
if [ "${1:-}" = "--link" ]; then LINK=1; SRC="${2:-$HERE}"; fi
mkdir -p "$BIN"
for f in $FILES; do
  [ -f "$SRC/$f" ] || { echo "missing $SRC/$f"; exit 1; }
done
for f in $FILES; do
  if [ "$LINK" = 1 ]; then
    ln -sfn "$SRC/$f" "$BIN/$f"
    echo "linked    $BIN/$f -> $SRC/$f"
  else
    install -m 755 "$SRC/$f" "$BIN/$f"
    echo "installed $BIN/$f"
  fi
done
