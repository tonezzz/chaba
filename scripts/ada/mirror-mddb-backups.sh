#!/usr/bin/env bash
# Push MDDB bank dumps to a warm copy on mn01.
#
# Sources (written nightly by backup-mddb-banks.py via
# ada-memory-backup.timer):
#   - shared banks:   ~/CascadeProjects/chaba/backups/ada-memory/   (in git too)
#   - personal banks: ~/.local/share/ada-backups/ada-memory/        (never git)
#
# Runs on tony-omen (tony-omen->mn01 ssh trust already exists; the reverse
# is not keyed). Restore with scripts/ada/restore-mddb-banks.py against a
# dump dir. Scheduled via ada-memory-backup-mirror.timer (weekly, after the
# nightly backup).
set -euo pipefail

REMOTE="mn01:.local/share/ada-mddb-mirror"
ssh mn01 'mkdir -p ~/.local/share/ada-mddb-mirror/shared ~/.local/share/ada-mddb-mirror/personal'

rsync -az --timeout=30 \
  "$HOME/CascadeProjects/chaba/backups/ada-memory/" "$REMOTE/shared/"
if [[ -d "$HOME/.local/share/ada-backups/ada-memory" ]]; then
  rsync -az --timeout=30 \
    "$HOME/.local/share/ada-backups/ada-memory/" "$REMOTE/personal/"
else
  echo "no personal dumps yet — skipping"
fi

echo "mirrored -> $REMOTE ($(ssh mn01 "find ~/.local/share/ada-mddb-mirror -name '*.json' | wc -l") dumps)"
