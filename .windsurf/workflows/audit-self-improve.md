---
description: Audit recent assistant behavior and update the knowledge base
---
1. Ask the user for audit scope: `current session`, `last N conversations`, or `since <date>`.
2. Review the selected conversation(s) for:
   a. Explicit corrections (`no, do X`, `wrong`, `use Y instead`).
   b. Repeated mistakes or wrong assumptions.
   c. Commands that failed and how they were fixed.
   d. New conventions, shortcuts, or preferences the user demonstrated.
   e. Tool-usage mispatterns (wrong tool, wrong order, missing flags).
3. For each finding, check existing memories to see if it is already covered or contradicted.
4. Propose a ranked list of memory changes:
   - **Create** for new facts, conventions, or workarounds.
   - **Update** for stale or incomplete entries.
   - **Archive** for rules that no longer apply.
5. Present the proposal to the user and ask for explicit approval before writing.
6. Only after approval, apply the changes in the correct corpus with clear titles and relevant tags.
7. Skip temporary commands, one-off output, and obvious trivia.
8. Report what was created, updated, or archived, plus one concrete habit the assistant should adopt next time.
9. End the response with the exact message: `Audit complete. I will apply these lessons.`
