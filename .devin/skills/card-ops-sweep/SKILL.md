---
name: card-ops-sweep
description: Use for status/process/continue requests involving one or more Kanban cards, DevNest runners, Jules sessions, or PR closeout.
---

# Card Operations Sweep

Follow `docs/kb/card-status-and-processing.md`. Use this skill to reconcile
the board, executor, and artifact without repeating full scans or status polls.

1. Extract the named cards and decision needed. Prefer `/queue` for a queue
   overview and `/card/<id>` for specific cards; never fetch the full board
   for a small, named set.
2. Batch independent board reads. Read `comms` only for pending requests,
   failures, or state contradictions.
3. Reconcile remote work in one pass. List relevant executor sessions once;
   fetch activities only for `AWAITING_USER_FEEDBACK`, `COMPLETED`, or a
   board/session mismatch. Inspect a PR/checks only when linked to that work.
4. Reuse answers already in card requests/comms. Do not ask the same approval
   again or start a duplicate claim. While waiting, do only independent work.
5. Do not sleep-poll. Report the snapshot time, actual state, blocker, and
   next action. A status refresh needs a user request or new evidence.
6. Completion requires the declared artifact, passing relevant checks, and
   merged/verified state. A runner tombstone or a completed agent session
   alone is not completion.
7. Keep the response compact: one line per card with state, evidence, and
   blocker/next step. Separate Devin spend from provider quotas and local
   machine cost; do not run billable probes without authorization.

The procedure's authoritative read and cost details are in
`docs/kb/card-status-and-processing.md`.
