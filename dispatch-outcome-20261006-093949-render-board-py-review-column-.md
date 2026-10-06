# Dispatch outcome — review-trust-badge (re-run, no changes needed)

Card: `review-trust-badge` — review column verified-vs-claimed badge.

## Finding

The spec was already fully implemented on master by the previous dispatch
session: commit `8197c830` ("feat(board): review badge trusts explicit
action.verified + pushed-SHA comms") is an ancestor of this worktree's
HEAD. This dispatch was a re-run of completed work; **no code changes were
required** and the worktree is clean.

Prior trail: `dispatch-outcome-20261006-065813-render-board-py-review-column-.md`,
`docs/ssot/jobs/kanban/2026-10-06-review-trust-badge.yml`.

## Current implementation (verified in this worktree)

`scripts/render-board.py` (generated board page JS):

- Review-column cards get a trust badge in `cardHtml()`:
  `✔ verified` (emerald) or `⚠ claimed` (amber), with a `title` tooltip
  naming the verdict source.
- `isVerified(c)`: an explicit `action.verified` field — reserved for
  dispatch-merge-guard's real merge/push check — wins over the comms
  heuristic. `true`/`"true"` → verified; any other set value (incl.
  `false`) → claimed; field absent → heuristic.
- `TRUST_RE` heuristic matches `verif` / `auto-merged` / `merged into` /
  `confirm` / `works` / `lgtm` / `tested` / `checks out` / `pushed <SHA>`
  (SHA arm requires a hex letter so timestamps don't count; lookbehinds
  keep "not pushed"/"n't pushed" negative).
- `needsYou()` stale-review check uses the same `isVerified()`, so a
  merge-guard flag also clears the ">24h no verification" nudge.
- `docs/ssot/kanban/ssot.kanban.yml` `card_schema.action` documents
  `verified` (lines 76-78); needs_you_band updated.

## Verification (re-run this session)

- `python3 scripts/render-board.py` regenerates cleanly: 159 cards,
  v9f20574baf83. Output is gitignored; worktree clean.
- Node harness evals the generated page script with DOM stubs and calls
  `cardHtml()` — 9/9 pass, covering both spec cases:
  - card with only a done-claim comm → `⚠ claimed` (spec negative)
  - card with a verification comm (`verified` / `auto-merged` /
    `pushed 022cad43`) → `✔ verified`
  - `commits remain (…, not pushed)` → `⚠ claimed`
  - `action.verified: true` with no comms → `✔ verified`
  - `action.verified: false` + "verified" comm → `⚠ claimed` (explicit
    field wins); `"false"` string → `⚠ claimed` (fail-safe)
  - non-review column → no badge
- Against live `cards.json`: 33 review cards → 19 verified, 14 claimed.

## Notes

- If cards like this keep getting re-dispatched after their work merged,
  the dispatcher may be re-queuing on stale card state — worth checking
  that the card's `action.status` is set to `done` when it moves to
  review/done.
