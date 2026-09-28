#!/bin/bash
# devin-git-checkpoint.sh — Create an automatic git checkpoint from a hook.
#
# Defaults to committing only modified/deleted tracked files. Set
# DEVIN_AUTO_COMMIT_INCLUDE_UNTRACKED=1 to also add new untracked files.
# Set DEVIN_AUTO_COMMIT=0 to stage without committing.
# Protected branches (main, master by default) are skipped unless
# DEVIN_AUTO_COMMIT_MAIN=1 is set.

set -uo pipefail

SUMMARY_FILE="${1:-}"
SESSION_ID="${2:-${DEVIN_SESSION_ID:-unknown}}"
PROJECT_DIR="${DEVIN_PROJECT_DIR:-$(pwd)}"
AUTO_COMMIT="${DEVIN_AUTO_COMMIT:-1}"
ALLOW_MAIN="${DEVIN_AUTO_COMMIT_MAIN:-0}"
INCLUDE_UNTRACKED="${DEVIN_AUTO_COMMIT_INCLUDE_UNTRACKED:-0}"
PROTECTED_BRANCHES="${DEVIN_AUTO_COMMIT_PROTECTED_BRANCHES:-main}"

if ! cd "$PROJECT_DIR" 2>/dev/null; then
    echo "Cannot access project directory $PROJECT_DIR" >&2
    exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository"
    exit 0
fi

BRANCH=$(git branch --show-current 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

for pb in $PROTECTED_BRANCHES; do
    if [[ "$BRANCH" == "$pb" ]]; then
        if [[ "$ALLOW_MAIN" != "1" ]]; then
            echo "On protected branch $BRANCH; no auto-commit"
            exit 0
        fi
    fi
done

MSG_FILE=$(mktemp)
trap 'rm -f "$MSG_FILE"' EXIT

if [[ -n "$SUMMARY_FILE" && -f "$SUMMARY_FILE" ]]; then
    SUBJECT=$(head -n 1 "$SUMMARY_FILE" | sed -e 's/^[[:space:]]*//' -e 's/^#*[[:space:]]*//' | cut -c1-72)
    BODY=$(tail -n +2 "$SUMMARY_FILE" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | awk 'NF' | head -c 4000)
    {
        echo "$SUBJECT"
        echo ""
        echo "$BODY"
    } > "$MSG_FILE"
else
    {
        echo "Devin checkpoint for session $SESSION_ID"
        echo ""
        echo "Auto-generated checkpoint at session $SESSION_ID"
    } > "$MSG_FILE"
fi

if [[ "$INCLUDE_UNTRACKED" == "1" ]]; then
    git add -A 2>/dev/null || { echo "git add failed" >&2; exit 0; }
else
    git add -u 2>/dev/null || { echo "git add failed" >&2; exit 0; }
fi

STAGED=$(git diff --cached --name-only 2>/dev/null)
if [[ -z "$STAGED" ]]; then
    echo "No staged changes to commit"
    exit 0
fi

FILE_COUNT=$(git diff --cached --name-only 2>/dev/null | wc -l)

if [[ "$AUTO_COMMIT" != "1" ]]; then
    echo "Staged $FILE_COUNT file(s) for manual commit"
    exit 0
fi

if git commit -F "$MSG_FILE" --quiet 2>/dev/null; then
    SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    echo "Auto-committed $FILE_COUNT file(s) on $BRANCH (commit $SHA)"
else
    echo "Commit failed; $FILE_COUNT file(s) staged but not committed" >&2
    exit 0
fi
