#!/usr/bin/env bash
# retry-train.sh — restart a training command after earlyoom SIGTERM with
# --resume appended (train_generator supports it). Usage:
#   ./retry-train.sh <max_retries> -- <cmd...>
set -u
max="$1"; shift; [ "$1" = "--" ] && shift
i=0
while [ $i -le "$max" ]; do
  "$@" --resume
  rc=$?
  [ $rc -eq 0 ] && exit 0
  i=$((i + 1))
  echo "[retry] exit=$rc restart $i/$max" >&2
  sleep 15
done
exit 1
