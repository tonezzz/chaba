---
description: Back To Most Valuable Task (MVT)
---

Use this workflow whenever you notice you context-switched and the current task is left half-done.

1. Restate the current objective (one sentence)
   - Write: "MVT: <single sentence outcome>".
   - If you can't say it in one sentence, split it into 2-3 outcomes and pick the most urgent one.

2. Rebuild context in 90 seconds
   - Read the last 30-80 lines of the most relevant logs (backend or CI), and the last 20 chat messages.
   - Write 3 bullets:
     - "What is failing right now?"
     - "What changed last?"
     - "What is the next verification step?"

3. Define the smallest next action (SNA)
   - Must be doable in <= 10 minutes.
   - Must produce a binary result (pass/fail, present/missing, connected/disconnected).
   - Format:
     - "SNA: <action>"
     - "Success looks like: <observable>"
     - "If fail, I will inspect: <1 place>"

4. Execute SNA
   - Do only the SNA. No refactors, no docs, no extras.
   - Capture the output (copy/paste the key lines).

5. Update the queue (WIP limit = 1)
   - Put exactly 1 item as "in progress".
   - Convert everything else into:
     - "Next" (max 3 items)
     - "Waiting" (blocked by other people/systems)
     - "Later" (nice-to-have)
   - Delete or merge duplicates.

6. Update the Back-to-MVT doc (every run)
   - Edit: `services/assistance/docs/BACK_TO_MVT.md`
   - Add a single row to the Run log table with:
     - Date/Time
     - MVT (one sentence)
     - SNA (one action)
     - Outcome (success/fail)
     - What improved (one sentence)

7. Self-assess (workflow improvement loop)
   - Score 0-2 for each:
     - Clarity (do I know what to do next?)
     - Confidence (do I believe it will work?)
     - Containment (did I avoid side-quests?)
   - If any score is 0:
     - Add ONE guardrail for next time (example: "No new tasks until SNA done").
   - Write one sentence:
     - "Next time, I will <process change>."

8. Close the loop
   - If SNA succeeded:
     - Pick the next SNA (repeat from step 3).
   - If SNA failed:
     - Write the failure hypothesis and the single best next inspection.

Notes:
- If you find yourself tempted to switch tasks, pause and run this workflow again.
- Keep a running "Decision log" in 3 lines max: Date, decision, why.
