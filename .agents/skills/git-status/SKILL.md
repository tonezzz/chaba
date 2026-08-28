---
name: git-status
description: Show git status, diff, and recent commits
allowed-tools:
  - exec
triggers:
  - user
  - model
---

Show comprehensive git status:

1. Run `git status` to show current branch and working tree status
2. If there are uncommitted changes, run `git diff` to show what changed
3. If there are staged changes, run `git diff --staged` to show staged changes
4. Run `git log --oneline -10` to show recent commits
5. Summarize the current state:
   - Branch name
   - Number of modified/staged/untracked files
   - Recent commit activity
   - Whether there are uncommitted changes that need attention
