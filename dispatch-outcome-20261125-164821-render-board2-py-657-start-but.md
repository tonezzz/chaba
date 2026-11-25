# Dispatch outcome — board2 Start button gate + write pending state

Card: `board2-start-button-renders-on-review-do-bfd250`
Branch: `dispatch/20261125-164821-render-board2-py-657-start-but`
Commit: `49ce84a0df4` — `fix(board2): gate Start button on column, add write pending state`

## What changed

All changes in `scripts/render-board2.py` (the JS embedded in the generated
`/apps/board2/` page). View layer only; no board-api or data changes.

1. **Start-button gate fixed** (was ~line 987, card said :657 — the file has
   grown since the line ref was written). Old condition:
   `!queued/running/done.includes(status) && (a.type || !terminal-columns.includes(column))`
   — the `a.type ||` clause rendered Start on any card carrying
   `action.type: dispatch` even in review/done, and clicking it POSTed
   `/action do=queue` (review→backlog re-dispatch; the 2026-11-16 near-miss).
   New condition drops `a.type` entirely and adds `verified` to the excluded
   statuses:
   `!['queued','running','done','verified'].includes(status) && !['doing','done','verified','review'].includes(column)`
   Start now renders only for cards in lab/backlog (or any future
   non-terminal column) whose action isn't already queued/running/done/
   verified. `failed` status still shows Start so a failed backlog card
   keeps its re-queue path.

2. **Client-side pending state for writes** — modal action buttons
   (queue/close), the move `<select>`, and the comment Post button now
   disable + dim (`opacity-50 cursor-wait`) and show `…` while the POST is
   in flight, instead of looking dead during board-api flock starvation.

3. **api() timeout 60s → 300s** — the observed convoy starvation was ~5min
   (kanban-commit/merge-sweep/deploy-preflight each hold `/tmp/board-api.lock`
   for minutes); 60s aborted client-side mid-wait.

## Verification

- `python3 scripts/render-board2.py` → `wrote .../board2/index.html + cards.json (799 cards, vd149dad3443b)` (generated output is gitignored; render is clean).
- `node --check` on the extracted `<script>` block → OK.
- `git status` clean apart from the committed renderer change.

## Deploy note

No deploy from this session. `board-render-guard`/`chaba-board-render.service`
on the writer re-renders board2 from the merged checkout; the change goes
live on the next repo sync + render after merge. `deploy-check.sh` verifies
the marker lands on idc03 + served root.

## lessons:

- The card's `render-board2.py:657` line ref was stale — the Start-button
  condition actually lives ~line 987 in the current file; grep for
  `data-do="queue"` instead of trusting line numbers in card specs.
- `a.type` on a card means "this card has a dispatch action spec", not "this
  card may be started from any column" — gating UI affordances on it bypasses
  the column state machine.
- board2's modal re-renders on every `load()` poll, so pending state only
  needs to survive one request — no need to persist it across renders.
