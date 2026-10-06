# Dispatch outcome — review-trust-badge

Card: `review-trust-badge` — review column verified-vs-claimed badge.

## What changed

The comms-heuristic badge from dcffce02 was already in place; this pass
added the two missing spec requirements:

- `scripts/render-board.py`
  - New `isVerified(c)` helper: an explicit `action.verified` field
    (reserved for dispatch-merge-guard's real merge/push check) wins over
    the comms heuristic — `true`/`"true"` → verified, any other set value
    (incl. `false`) → claimed; field absent → comms heuristic via
    TRUST_RE.
  - `TRUST_RE` extended with a pushed-SHA arm:
    `(?<!not )(?<!n't )pushed\b[^.\n]{0,60}\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b`
    — lookbehinds keep "not pushed"/"isn't pushed" negative; the hex-letter
    lookahead excludes all-digit timestamps (e.g. `20261005`) that occur in
    dispatch comms.
  - Badge now carries a `title` tooltip naming the verdict source
    (merge-guard flag vs comms heuristic vs none).
  - `needsYou()` stale-review check uses the same `isVerified()` (dead
    VERIFY_RE removed — TRUST_RE is a superset), so a merge-guard flag also
    clears the ">24h no verification" nudge.
- `docs/ssot/kanban/ssot.kanban.yml` — `card_schema.action` documents
  `verified`; needs_you_band item updated to the new semantics.
- `docs/ssot/jobs/kanban/2026-10-06-review-trust-badge.yml` — job trail.

Commit: `8197c830` on `dispatch/20261006-065813-render-board-py-review-column-`
(not pushed — dispatch policy).

## Verification

`python3 scripts/render-board.py` regenerates cleanly (158 cards,
v9f20574baf83). A node harness evals the generated page script with DOM
stubs and calls `cardHtml()`/`isVerified()` — 10/10 pass:

- done-claim-only comm → `⚠ claimed` (spec's required negative)
- `verified` / `auto-merged` / `pushed 022cad43` comms → `✔ verified`
- `unmerged commits remain` and `(02b2c15, not pushed)` → `⚠ claimed`
- `action.verified: true` with no comms → `✔ verified`
- `action.verified: false` + "verified" comm → `⚠ claimed` (explicit wins)
- `verified: "false"` string → `⚠ claimed` (fail-safe)
- non-review column → no badge

Against live `cards.json`: 31 review cards → 14 verified, 17 claimed —
matches reality (e.g. `dispatch-merged-branch-prune` finished with no
merge comm → claimed).

## Notes

- Pre-existing SSOT validation failure unrelated to this change:
  `docs/ssot/jobs/kanban/2026-10-05-board-request-notify.yml` missing
  required `title` (fails on clean master too).
- Verify visually after merge: review-column cards with only a done-claim
  comm show `⚠ claimed`; hovering a `✔ verified` badge shows whether the
  source was the merge-guard field or the comms heuristic.
