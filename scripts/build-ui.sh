#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_UI_DIR="$REPO_ROOT/sites/test-ui"
TARGET_DIR="$REPO_ROOT/sites/a1-idc1/test"

if [[ ! -f "$TEST_UI_DIR/package.json" ]]; then
  echo "[build-ui] test-ui project not found at $TEST_UI_DIR" >&2
  exit 1
fi

echo "[build-ui] Installing dependencies…"
cd "$TEST_UI_DIR"
npm install --no-audit --no-fund

echo "[build-ui] Building test-ui…"
npm run build

if [[ ! -d "$TEST_UI_DIR/dist" ]]; then
  echo "[build-ui] Build output missing at $TEST_UI_DIR/dist" >&2
  exit 1
fi

echo "[build-ui] Syncing dist/test -> $TARGET_DIR"
if [[ ! -d "$TEST_UI_DIR/dist/test" ]]; then
  echo "[build-ui] dist/test directory missing; check Vite build output" >&2
  exit 1
fi
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -R "$TEST_UI_DIR/dist/test/"* "$TARGET_DIR/"

echo "[build-ui] Completed."
