#!/usr/bin/env bash
# host-capability-bootstrap.sh — bring one host to a declared capability.
#
#   host-capability-bootstrap.sh <host> <capability>
#
# Recipes match ssot.host-software.yml bootstrap keys. User-level only —
# anything needing sudo prints instructions instead of failing halfway.
set -euo pipefail
HOST="${1:?usage: $0 <host> <capability>}"
CAP="${2:?usage: $0 <host> <capability>}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8)

case "$CAP" in
  venv)
    "${SSH[@]}" "$HOST" 'python3 -m ensurepip --upgrade --user && python3 -m venv /tmp/.r7-venv-check && rm -rf /tmp/.r7-venv-check && echo VENV-OK'
    ;;
  python_ml)
    # durable ML venv — NOT /tmp. CPU torch index keeps the wheel small;
    # add a cuda lane here when a host gets a working driver.
    "${SSH[@]}" "$HOST" 'set -e
      python3 -m venv "$HOME/.local/share/chaba-ml-venv"
      "$HOME/.local/share/chaba-ml-venv/bin/pip" install --quiet --index-url https://download.pytorch.org/whl/cpu torch
      "$HOME/.local/share/chaba-ml-venv/bin/pip" install --quiet transformers
      "$HOME/.local/share/chaba-ml-venv/bin/python" -c "import torch, transformers; print(\"ML-OK\", torch.__version__)"'
    ;;
  ollama_pull_bge_m3)
    "${SSH[@]}" "$HOST" 'ollama pull bge-m3 && echo OLLAMA-OK'
    ;;
  node)
    echo "node: install per docs/kb/new-host-onboarding.md §3 (user-space tarball to ~/.local/node)" >&2
    exit 1
    ;;
  manual|*)
    echo "no recipe for '$CAP' — fix by hand or add a recipe here" >&2
    exit 1
    ;;
esac
