---
name: status
description: Quick project status summary (working on, done, remaining, next steps)
allowed-tools:
  - read
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

Guidelines:
- Be concise and specific; reference files/services/URLs where relevant.
- Do not invent status; base the summary on the conversation and available evidence.
- If scope is unclear, ask which project or context to summarize.
- This is a lightweight status check — no KB archiving or auto-saving.
