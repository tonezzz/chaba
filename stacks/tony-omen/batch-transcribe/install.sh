#!/usr/bin/env bash
# Install/refresh batch-transcribe on THIS host (tony-omen).
# Creates ~/.local/share/batch-transcribe/venv (moondream + soundfile) and a
# ~/.local/bin/batch-transcribe launcher. CPU-only; GPU untouched.
# Usage: bash install.sh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$HOME/.local/share/batch-transcribe"
VENV="$STATE_DIR/venv"

mkdir -p "$STATE_DIR" "$HOME/.local/bin"

if [[ ! -x "$VENV/bin/python" ]]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv "$VENV"
        uv pip install --python "$VENV/bin/python" 'moondream>=2.4.1' soundfile
    else
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install 'moondream>=2.4.1' soundfile
    fi
fi

install -m 0755 "$SCRIPT_DIR/batch-transcribe.py" "$STATE_DIR/batch-transcribe.py"

cat > "$HOME/.local/bin/batch-transcribe" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$STATE_DIR/batch-transcribe.py" "\$@"
EOF
chmod 0755 "$HOME/.local/bin/batch-transcribe"

echo "installed: ~/.local/bin/batch-transcribe (venv: $VENV)"
echo "first run downloads moondream/parakeet-redux weights (~178MB) to HF cache"
