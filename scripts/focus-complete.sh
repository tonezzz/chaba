#!/bin/bash
# focus-complete.sh
# Mark the current task/focus as completed and commit all related changes.
# Run this when a focus is done and you want to save the work.

set -euo pipefail

REPO="/home/tony/CascadeProjects/chaba"
cd "$REPO"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <commit-message>" >&2
    exit 1
fi

MESSAGE="$1"

# 1. Validate SSOT
python3 scripts/ssot-validate-refs.py || {
    echo "ERROR: SSOT ref validation failed. Fix before committing." >&2
    exit 1
}

# 2. Stage all tracked and new SSOT/code files
#    Do not stage experiments/ data files or .docs-mcp generated files.
git add -A -- ':!experiments/*' ':!.docs-mcp/*' ':!data/*' ':!*.csv' ':!*.parquet' || true

# 3. Only commit if there is something to commit
if git diff --cached --quiet; then
    echo "Nothing to commit." >&2
    exit 0
fi

# 4. Commit
git commit -m "$MESSAGE" || {
    echo "ERROR: commit failed" >&2
    exit 1
}

# 5. Mark active focus completed in ssot.focus.current.active.yml
#    (simplified: the assistant or focus-sweep will update it)

echo "Task committed: $MESSAGE"
