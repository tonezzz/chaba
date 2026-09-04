---
description: Audit my Devin/Windsurf usage and suggest improvements
---
1. Gather evidence:
   - `git status` in `/home/tony/CascadeProjects/chaba-tony-dell` and `/home/tony/CascadeProjects/chaba-h3`.
   - `docker ps --format "table {{.Names}}\t{{.Status}}"` for active containers.
   - `du -sh` on large caches: `~/.cache/huggingface`, `~/.cache/ms-playwright`, `~/.cache/llama.cpp` (or equivalent).
   - Recent commits: `git log --oneline -20` in each worktree.
   - Memory count and obvious stale/duplicate categories from available memories.
   - Recurring commands or tool patterns in the current conversation.
2. Identify patterns: repeated manual steps, disk/memory pressure, unused containers, stale branches, uncommitted work, or frequent workarounds.
3. Propose concrete improvements ordered by value (quick wins first).
4. Suggest any new aliases, workflows, or tooling to eliminate repetition.
