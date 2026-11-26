#!/usr/bin/env bash
# Compatibility shim for the legacy idc02 mddb-tier2-pull.timer unit.
# The real script lives in tony's home (~/mddb-tier2-pull.sh, see card
# mddb-backup-tier2-idc02); the rendered unit points at this repo path.
set -euo pipefail
exec "$HOME/mddb-tier2-pull.sh" "$@"
