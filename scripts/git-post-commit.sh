#!/bin/sh
# Post-commit hook: refresh the NotebookLM KB when relevant files change.

REPO=/home/tony/CascadeProjects/chaba
CHANGED=$(git -C "$REPO" diff-tree --no-commit-id --name-only -r HEAD)

KB_REGEX='^(docs/kb/|docs/ssot/|AGENTS\.md|README\.md)'
CHANGES=$(echo "$CHANGED" | grep -E "$KB_REGEX" || true)

if [ -n "$CHANGES" ]; then
    echo "[notebooklm] KB-related files changed; scheduling incremental sync..."
    (systemctl --user start notebooklm-kb-sync.service >/dev/null 2>&1 &) || true
else
    echo "[notebooklm] No KB-related changes; skipping sync."
fi
