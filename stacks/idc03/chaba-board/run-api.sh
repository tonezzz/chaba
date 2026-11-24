#!/usr/bin/env bash
# chaba-board-api entrypoint (containerized chaba-board-api.service).
# Sources the optional edge-key env file exactly like the old unit's
# EnvironmentFile=-%h/.config/secrets/board-api.env did, then execs
# board-api.py from the served checkout.
set -euo pipefail

SERVED="$HOME/CascadeProjects/chaba-tony-dell"
ENV_FILE="$HOME/.config/secrets/board-api.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

exec /usr/local/bin/python3 "$SERVED/scripts/board/board-api.py"
