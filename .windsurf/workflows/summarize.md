---
description: Summarize project status — current focus, done, remaining, and next high-value work
---

When invoked with `/summarize` (or phrases like `summarize this` or `give me a summary`), produce a concise project/status summary using exactly these sections:

## Working on
1–2 lines stating the current task or focus of this session/conversation. Answer "what is being worked on right now?" — the active goal, the feature/bug/refactor in progress, or the question being investigated. If multiple threads are active, lead with the primary one and list secondary ones briefly.

## Done
Completed items, committed changes, verified deployments, and closed issues from the current context.

## Remaining
Open tasks, unfinished work, blockers, pending verification, or known debt.

## Next high-value things to do
1–3 actionable items that are highest impact, lowest blocker, or move the work forward fastest.

## KB review
After producing the summary above, assess whether the conversation contains KB-worthy facts (decisions, discoveries, infrastructure changes, conventions, workarounds) that have **not yet been saved** to memory.

Auto-archive rules:
- If there are unsaved KB-worthy facts, automatically run the `/archive` workflow steps (check existing memories, create/update in the correct corpus, skip trivia) and summarize what was saved.
- If everything is already saved or there are no KB-worthy facts, state "No new KB entries needed."
- Do **not** ask for confirmation — just archive and report.

Guidelines:
- Be concise and specific; reference files/services/URLs where relevant.
- Do not invent status; base the summary on the conversation and available evidence.
- If scope is unclear, ask which project or context to summarize.
