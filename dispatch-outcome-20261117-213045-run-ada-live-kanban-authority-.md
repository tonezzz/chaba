# Dispatch outcome — ada-real-card-sweep-scenario-20261108 (2026-11-17 21:30, tony-omen)

## Verdict: duplicate dispatch of already-completed, already-merged work — no second sweep run

## What was found

This card's task (Ada live kanban authority verification + bounded 1–3 real-card
sweep) was **already executed by the 20:37 tony-dell dispatch** and auto-merged
to origin/master at 20:54 as `542be378` (confirmed ancestor of this worktree's
HEAD). Evidence verified in this worktree, not from memory:

- Trail file `docs/ssot/jobs/ada/2026-11-17-kanban-real-card-sweep.yml` is present
  in history (`3cc08f5edb`) and records: gate answer (Tony 2026-11-08,
  "safe-review — at most 3 review_kind:triage/verify cards"), 6-turn ada-dev
  scenario PASS, 3 evidence-verified closes, 2 refusal probes left untouched,
  blast-radius audit (only the 3 allowlisted cards carry ada writes).
- Scenario file `docs/ssot/jobs/ada/2026-11-17-kanban-real-sweep.scenario.yaml`
  present.
- Card states in this checkout:
  - `ada-ocb-context-windowed-excerpts` → **done** (was review|verify)
  - `unattended-pilot-health-probe` → **done** (was review|verify)
  - `openchamber-devnest-project-path` → **done** (was review|verify)
  - `nest-io-fabric` → still **review** (review_kind:decide — correctly refused)
  - `ada-ocb-ssot-direct-get` → still **review** (priority:high — correctly refused)

## Why no re-run

The Tony-approved scope was "at most 3 review_kind:triage/verify cards" — all 3
allowed slots are consumed and those cards are done. A second live sweep would
either mutate additional real cards (exceeding the allowlist) or be a no-op.
The ada-dev live-model call was also inside a bounded one-run spend scope that
is already spent.

## Why this dispatch exists at all

Known bug, already carded: `board2-start-button-renders-on-review-do-bfd250`
(backlog) — board2 renders a Start button on review/done cards; clicking it
POSTs /action do=queue, moving review→backlog and re-dispatching verified work.
The card comms show "retry requested" at 21:11 → tony-omen attempt 21:13
(failed exit=1, 53s) → this dispatch at 21:30. That card is the fix, not this one.

## Changes made this session

- Board comment posted documenting duplicate-dispatch finding (via board-api /comment).
- This outcome file. No code/config/card edits; nothing committed.

## How to verify

- `git merge-base --is-ancestor 542be378 origin/master` → exit 0.
- `cat docs/ssot/jobs/ada/2026-11-17-kanban-real-card-sweep.yml` → full run evidence.
- `grep column: docs/ssot/kanban/cards/{ada-ocb-context-windowed-excerpts,unattended-pilot-health-probe,openchamber-devnest-project-path}.yml` → done.
- Card remains in `review` awaiting Tony's review of the (already merged) work.
