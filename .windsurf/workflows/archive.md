---
description: Comprehensive session archiving with status summary and KB archiving
---

Accepted triggers: `/archive`, `/summarize` (backward compatibility), or phrases like "Let's archive" or "summarize this"

## Default Behavior (no flags)
1. Generate comprehensive status summary with these sections:
   - Working on (1-2 lines on current task/focus)
   - Done (completed items, verified deployments, closed issues)
   - Remaining (open tasks, unfinished work, blockers)
   - Next high-value things to do (1-3 actionable items)
2. Auto-archive KB-worthy facts to memory (decisions, discoveries, infrastructure changes, conventions, workarounds)
3. Check existing memories to avoid duplicates; update or archive stale entries
4. Skip temporary commands, one-off output, and obvious trivia
5. Report summary of what was archived
6. End with "Ready to be archived."

## Optional Flags (for granularity control)
- `--no-status` or `--kb-only`: Skip status summary, only KB archiving
- `--session-only`: Only session YAML archiving (via archive skill), no KB
- `--status-only`: Only status summary, no archiving

## Guidelines
- Be concise and specific; reference files/services/URLs where relevant
- Do not invent status; base the summary on conversation evidence
- If scope is unclear, ask which project or context to summarize
- Context-aware: If called mid-session, skip "Working on" section (might be stale)
- Backward compatible: Accept `/summarize` trigger for existing muscle memory