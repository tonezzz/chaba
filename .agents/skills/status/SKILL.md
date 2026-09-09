---
name: status
description: Quick project status summary (working on, done, remaining, next steps)
allowed-tools:
  - read
  - postgres query
triggers:
  - user
  - model
---

Provide a concise project status summary using these sections:

## Working on
1–2 lines stating the current task or focus of this session/conversation. Answer "what is being worked on right now?" — the active goal, the feature/bug/refactor in progress, or the question being investigated. If multiple threads are active, lead with the primary one and list secondary ones briefly.

## Done
Completed items, committed changes, verified deployments, and closed issues from the current context.

## Remaining
Open tasks, unfinished work, blockers, pending verification, or known debt.

## Next high-value things to do
1–3 actionable items that are highest impact, lowest blocker, or move the work forward fastest.

## Recent Knowledge (Optional)
If relevant to the current context, query the knowledge base for recent entries related to the project or topic being discussed. Use postgres query to retrieve recent KB entries:

```sql
SELECT title, category, created_at 
FROM knowledge_base 
WHERE project = 'chaba' OR project = 'trade' 
ORDER BY created_at DESC 
LIMIT 5;
```

Show 2-3 most relevant recent KB entries that might inform the current work.

Guidelines:
- Be concise and specific; reference files/services/URLs where relevant.
- Do not invent status; base the summary on the conversation and available evidence.
- If scope is unclear, ask which project or context to summarize.
- This is a lightweight status check — no KB archiving or auto-saving.
- KB retrieval is optional and only for context, not for archiving.
- For comprehensive status + KB archiving, use `/archive` workflow instead.
