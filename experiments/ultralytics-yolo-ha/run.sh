#!/bin/bash
set -e
cd "$(dirname "$0")"

VENV="$HOME/.cache/ultralytics-yolo-venv"
if [ ! -d "$VENV" ]; then
    python3 -m venv --system-site-packages "$VENV"
fi

"$VENV/bin/pip" install --upgrade pip

# CPU-only torch/torchvision from the fast PyTorch wheel index
"$VENV/bin/pip" install --extra-index-url https://download.pytorch.org/whl/cpu torch==2.14.0+cpu torchvision

# Install ultralytics without pulling opencv-python/matplotlib from slow PyPI;
# those come from the system apt packages.
"$VENV/bin/pip" install --no-deps ultralytics
# tiny profiling helper used by ultralytics utils
"$VENV/bin/pip" install --no-deps ultralytics-thop

exec "$VENV/bin/python" -u server.py
