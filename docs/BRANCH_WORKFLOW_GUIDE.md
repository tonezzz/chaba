# Branch Workflow Guide - Preventing Confusion

## The Problem

We accidentally switched from `idc1-assistance` (full Live API, 2050 lines) to `idc1-db` (placeholder, 321 lines) and lost all Live API functionality including:
- 4-scenario system
- Voice input/output
- Tool support

## Root Cause

The `idc1-assistance` branch contains the production Live API code.
The `idc1-db` branch contains a simplified stub.

## Prevention Measures

### 1. Visual Branch Indicator

Add to your shell prompt (`.bashrc` or `.zshrc`):

```bash
# Show current git branch in prompt
parse_git_branch() {
    git branch 2>/dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/(\1)/'
}
export PS1="\u@\h \[\033[32m\]\w\[\033[33m\] \$(parse_git_branch)\[\033[00m\] $ "
```

This shows: `user@host ~/chaba (idc1-assistance) $`

### 2. Branch Protection Script

Create `.windsurf/workflows/check-branch.md`:

```markdown
---
description: Check Branch Before Coding
tags: [workflow, safety]
---

## Pre-Flight Check

Before starting work, verify:

1. **Current Branch**
   ```bash
   git branch --show-current
   ```

2. **Expected Branch for Feature**
   - Live API work → `idc1-assistance`
   - Database work → `idc1-db`
   - VPN work → `idc1-vpn`
   - Gemini/MCP work → `idc1-assistance`

3. **If Wrong Branch**
   ```bash
   git stash
   git checkout CORRECT_BRANCH
   git stash pop
   ```

4. **Verify Code State**
   ```bash
   wc -l services/assistance/jarvis-backend/jarvis/websocket/session.py
   # Should be ~2000 for idc1-assistance
   # Should be ~300 for idc1-db
   ```
```

### 3. IDE Integration

Add branch check to Windsurf/Cascade:

```python
# In .windsurf/hooks/pre-command.py (conceptual)
import subprocess

def check_branch():
    branch = subprocess.getoutput("git branch --show-current")
    if "assistance" in branch.lower():
        if "session.py" in command:
            if "live" in command.lower() or "websocket" in command.lower():
                return True  # OK
    return True  # Let it proceed
```

### 4. File Headers

Add branch indicator to key files:

```python
# At top of jarvis/websocket/session.py
"""
BRANCH: idc1-assistance
PURPOSE: Gemini Live API with 4-scenario voice support
WARNING: Do not edit on idc1-db branch - this is the production implementation
"""
```

### 5. Automated Branch Check

Create `scripts/verify-branch.sh`:

```bash
#!/bin/bash
# Usage: ./scripts/verify-branch.sh

CURRENT_BRANCH=$(git branch --show-current)
EXPECTED_FILE_SIZE=2000  # session.py should have ~2000 lines on idc1-assistance

case "$CURRENT_BRANCH" in
    idc1-assistance)
        ACTUAL=$(wc -l < services/assistance/jarvis-backend/jarvis/websocket/session.py)
        if [ "$ACTUAL" -lt "$EXPECTED_FILE_SIZE" ]; then
            echo "❌ ERROR: session.py has $ACTUAL lines, expected ~$EXPECTED_FILE_SIZE"
            echo "   Branch may be corrupted. Run: git reset --hard origin/idc1-assistance"
            exit 1
        fi
        echo "✅ idc1-assistance branch verified ($ACTUAL lines)"
        ;;
    idc1-db)
        echo "⚠️  On idc1-db branch - Live API is simplified stub"
        echo "   Switch to idc1-assistance for full Live API: git checkout idc1-assistance"
        ;;
    *)
        echo "ℹ️  On branch: $CURRENT_BRANCH"
        ;;
esac
```

## Recovery Procedure

If you find yourself on the wrong branch:

### Scenario 1: No Local Changes

```bash
git checkout idc1-assistance
git reset --hard origin/idc1-assistance
```

### Scenario 2: With Local Changes

```bash
# Stash changes
git stash

# Switch to correct branch
git checkout idc1-assistance

# Apply stashed changes (may have conflicts)
git stash pop

# If conflicts, resolve manually or:
git checkout --theirs .
git add -A
```

### Scenario 3: Already Committed to Wrong Branch

```bash
# Get commit hash from wrong branch
git log -1 --oneline idc1-db

# Cherry-pick to correct branch
git checkout idc1-assistance
git cherry-pick <COMMIT_HASH>

# Revert wrong branch
git checkout idc1-db
git revert <COMMIT_HASH>
```

## Branch Purposes

| Branch | Purpose | Key Files |
|--------|---------|-----------|
| `idc1-assistance` | **Production voice assistant** | Full Live API, 4 scenarios, tools |
| `idc1-db` | Database/weaviate/mcp-wiki | Simplified stubs, DB focus |
| `idc1-vpn` | WireGuard/VPN management | VPN stack, dashboard |
| `main` | Stable releases | Tagged releases only |

## Checklist Before Pushing

- [ ] `git branch --show-current` shows expected branch
- [ ] Key files have expected size/content
- [ ] Tests pass on this branch
- [ ] Commit message mentions branch if ambiguous
- [ ] CI will deploy to correct environment

## Useful Aliases

Add to `~/.gitconfig`:

```ini
[alias]
    br = branch --show-current
    swa = checkout idc1-assistance
    swd = checkout idc1-db
    verify = !./scripts/verify-branch.sh
```

Usage:
```bash
git br          # Show current branch
git swa         # Switch to idc1-assistance
git verify      # Verify branch state
```
