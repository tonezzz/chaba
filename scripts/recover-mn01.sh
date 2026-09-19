#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${1:-tony-dell}"
BACKUP_HOST="${2:-tony-dell}"

LATEST="$(ssh -o ConnectTimeout=10 "$BACKUP_HOST" 'readlink -f "$HOME/.local/share/backups/mn01/latest"' 2>/dev/null || true)"
if [[ -z "$LATEST" ]]; then
    echo "ERROR: no latest backup found on $BACKUP_HOST" >&2
    exit 1
fi

echo "Restoring from $BACKUP_HOST:$LATEST to $TARGET_HOST"

ssh -o ConnectTimeout=10 "$TARGET_HOST" 'mkdir -p "$HOME/.config/secrets" && chmod 700 "$HOME/.config/secrets"'

# Restore secrets from backup
scp -3 "$BACKUP_HOST:$LATEST/secrets/"* "$TARGET_HOST:$HOME/.config/secrets/"
ssh -o ConnectTimeout=10 "$TARGET_HOST" 'chmod 600 "$HOME/.config/secrets/"*.env 2>/dev/null || true'

# Ensure the chaba repo (with the versioned stack) is present
ssh -o ConnectTimeout=10 "$TARGET_HOST" 'if [[ ! -d "$HOME/CascadeProjects/chaba/stacks/mn01/install.sh" ]]; then
    git clone https://github.com/tonezzz/chaba.git "$HOME/CascadeProjects/chaba" || true
fi'

# Run the versioned install
ssh -o ConnectTimeout=10 "$TARGET_HOST" 'bash "$HOME/CascadeProjects/chaba/stacks/mn01/install.sh"'

echo "mn01 Ada HA recovered on $TARGET_HOST"
echo "Next: update Tailscale Funnel / DNS if the public URL changed."
