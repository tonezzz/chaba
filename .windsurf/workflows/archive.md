---
description: Comprehensive session archiving with status summary and KB archiving
---

**Related:** [KB Helper Skill](../.devin/skills/kb-helper/SKILL.md) - KB operations and functions

Accepted triggers: `/archive`, `/summarize` (backward compatibility), or phrases like "Let's archive" or "summarize this"

## Default Behavior (no flags)
1. Generate comprehensive status summary with these sections:
   - Working on (1-2 lines on current task/focus)
   - Done (completed items, verified deployments, closed issues)
   - Remaining (open tasks, unfinished work, blockers)
   - Next high-value things to do (1-3 actionable items)
2. Auto-archive KB-worthy facts to PostgreSQL knowledge_base table (decisions, discoveries, infrastructure changes, conventions, workarounds)
   - Use postgres MCP server: INSERT INTO knowledge_base (title, content, tags, project, category, source)
   - Include relevant tags for searchability
   - Set project (chaba/trade) and category (documentation/infrastructure/feature/troubleshooting/workflow)
   - Set source to 'session' for session-archived entries
   - **Auto-invoke KB helper skill** to use save_kb_entry() function
3. Check existing KB entries to avoid duplicates; update or archive stale entries
   - Use KB helper skill: check_kb_duplicates(title, content)
   - Query: SELECT title, content FROM knowledge_base WHERE tags @> ARRAY['relevant-tag']
   - Update existing entries if content is similar but newer
4. Skip temporary commands, one-off output, and obvious trivia
5. Report summary of what was archived (count of KB entries, categories used)
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