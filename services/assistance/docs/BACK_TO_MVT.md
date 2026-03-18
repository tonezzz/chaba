# Back To Most Valuable Task (MVT)

## Goal
Reduce context-switching and unfinished work by enforcing:
- A single clear objective (MVT)
- A smallest-next-action loop (<= 10 minutes, binary outcome)
- A strict queue (WIP limit = 1)
- A self-improvement checkpoint

## When to run
Run this anytime you notice any of these:
- You opened a new task while the current one is unfinished
- You can’t clearly state “what success looks like”
- You are collecting info without executing a concrete verification step
- You are debugging in circles

## The workflow (overview)

```mermaid
flowchart TD
  A[Notice context-switch / stuck] --> B[Restate MVT in 1 sentence]
  B --> C[Rebuild context in 90 seconds]
  C --> D[Define SNA <= 10 min (binary)]
  D --> E[Execute SNA only]
  E --> F{SNA success?}
  F -- Yes --> G[Update queue (WIP=1, Next<=3)]
  G --> H[Self-assess + add 1 guardrail if needed]
  H --> D
  F -- No --> I[Write hypothesis + next inspection]
  I --> G

  G --> J[Update this doc: add run log entry]
  J --> H
```

## Definitions

### MVT (Most Valuable Task)
A single sentence outcome that, if completed, makes the biggest difference *right now*.

Good MVT examples:
- “Jarvis connects reliably (no system_sheet_unavailable) and module status report works end-to-end.”
- “Fix production deploy failure and verify green CI + healthy service.”

Bad MVT examples:
- “Improve the system.”
- “Refactor backend.”

### SNA (Smallest Next Action)
A step that:
- Takes <= 10 minutes
- Produces a pass/fail result
- Has exactly one next inspection if it fails

Template:
- SNA: <action>
- Success looks like: <observable>
- If fail, inspect: <one place>

## Queue policy (efficiency rules)
- WIP limit = 1 (exactly one “in progress”)
- Next = max 3 items
- Everything else is “Later” or “Waiting”
- Merge duplicates aggressively

## Self-assessment (workflow improvement)
Score each 0-2:
- Clarity (do I know what to do next?)
- Confidence (do I believe it will work?)
- Containment (did I avoid side-quests?)

If any score is 0:
- Add one guardrail for the next run (example: “No new tasks until SNA completes”).

## Run log (append/update every run)
Update this after each Back-to-MVT run.

| Date/Time | MVT | SNA | Outcome | What improved (1 sentence) |
|---|---|---|---|---|
| 2026-03-17 17:17 | Make auth screen container status UX foldable, include overall health, and prevent layout overflow | Implement collapsible container status section + overall icon + scrollable auth card; verify build | success | Reduced visual clutter while keeping diagnostics accessible without pushing primary CTA off-screen. |
| 2026-03-17 20:26 | Make Google Sheets memory timestamps typed as Date/Time and make GitHub Actions announcements short on start/completed | Commit+push backend changes for Sheets datetime format + CI started/completed messages; redeploy and verify in UI | pending | Improved operator readability by making timestamps parse as Date/Time and making CI notifications concise. |
| 2026-03-17 20:25 | Add a reliable GitHub Actions watcher loop (start/stop default stop) and persist last run result into memory | Start watcher -> confirm watch/list -> fetch latest run summary -> stop watcher -> write memory `runtime.github_actions.watch.latest` | success | Created a repeatable, bounded deploy-verification loop with a durable memory breadcrumb for the last run result. |
| 2026-03-17 21:30 | Ensure memo routing works (Thai trigger + correct memo sheet config key) | Commit+push backend changes for memo.spreadsheet_name lookup + Thai เมมโม trigger; redeploy and verify memo routes to sheet | success | Memo commands are less fragile: Thai spelling now routes correctly and spreadsheet config supports memo.spreadsheet_name with safe fallback. |
| 2026-03-18 12:45 | Stabilize Sheets logs mirroring so `/jarvis/logs/sheets/status` shows `enabled=true`, non-empty `sheet_name` (env-only), and `queue_len` decreases after a test append | Redeploy backend with env-only sheet_name + enqueue guard; verify status then POST a test log and confirm queue drains and row appears in Sheets | pending | Added workflow guardrails to prioritize Sheets logs stabilization before other tasks. |

