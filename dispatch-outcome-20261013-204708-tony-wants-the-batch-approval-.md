# board-decisions-inbox — batch-approval "Needs Tony" band on board2

## What changed

- `scripts/render-board2.py` — new `#needs-you` band between the tab row
  and the sidebar/detail split. `nyItems()` collects every open
  `requests[]` entry AND every open card-level `ask:` across all cards;
  each row shows the card title (click → jumps to the card's tab +
  detail pane), the ask text, and inline controls — the same
  option-button markup as the detail pane, refactored into a shared
  `reqAnswerHtml()`, plus `askAnswerHtml()`/`askHtml()` ported from the
  classic view (board2 previously ignored `ask:` entirely). Suggested
  options carry the existing ★ + emerald highlight. One binder
  `wireReq()` drives all `.rq-*`/`.ask-*` controls in band and detail
  (elements now carry `data-id`). Success → `/respond` → row flashes
  "✓ answered" ~1.6s then drops; `pendingAns` + `healPending()` replay
  answers onto stale `cards.json` polls so the row can't resurrect
  between render ticks. Collapse toggle → `b2-ny-collapsed`; empty state
  shows "✓ no pending decisions"; the nav pill counts correctly and
  hides at zero (previously it never re-hid). `?decisions=1` deep-link
  and the ny-pill both expand + scroll to the band.
- `scripts/board/board-api.py` — `render()` now also runs
  `render-board2.py --if-changed` after `render-board.py`, so a `/respond`
  answered on board2 disappears on the next poll instead of waiting for
  the render-guard tick.
- `docs/ssot/jobs/kanban/2026-10-13-board-decisions-inbox.yml` — trail.
- `docs/ssot/kanban/.render-state-board2` — regenerated state hash.
- Note: an ssot.kanban.yml parity doc edit was reverted — the file is
  already over the optimizer's bloat threshold and HEAD's warnings
  baseline doesn't know it, so ANY edit trips the pre-commit "new debt"
  gate (a full baseline refresh can't run: 3 pre-existing malformed job
  YAMLs — `2026-10-13-line-voice-enroll-recognize.yml`,
  `2026-10-13-tony-lane-tool-profile.yml`,
  `2026-10-13-omen-timer-pack-fixes.yml` — fail `ssot-validate-all`).
  Posted as card context; the band is documented in the job trail.

## Result

Commit `7c004ee71` on `dispatch/20261013-204708-tony-wants-the-batch-approval-`.
Verified end-to-end in headless Chrome (CDP) against a local board-api
(BOARD_API_PORT=8788, this worktree's cards) + static/proxy harness:
synthetic card with 2 option requests + 1 free-text request + 1
card-level ask — answered all four through the band (suggested ★ option,
non-suggested option, free-text box, ask option index). All landed as
`requests[].answer` / `ask.answer` + comms + `awaiting_action` on the
card; band counted 6→2 (two pre-existing real asks remained), flash
row + empty state confirmed. `board-api.py --selftest` passes; JS
syntax-checked; SSOT validate clean for touched files.

To verify live after merge+deploy: open
`/apps/board2/?decisions=1` — the band lists every open request/ask;
click a ★ option and the row drops with the answer on the card.
