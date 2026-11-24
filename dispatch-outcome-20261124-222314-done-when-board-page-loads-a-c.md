# Dispatch outcome — board-weight-cards-json-still-6-2mb-at-7-894827 (KNB-1302)

## Done-when

Board page loads a compact cards payload (<1.5MB at ~750 cards) with full
card detail fetched on open via GET /card/<id>; doing holds only cards
with a live claim or running action.

## What changed

- `scripts/render-board2.py` — new `_compact_card()` projection for
  `board2/cards.json`: drops `comms`/`spec`/`verify`/`help` per card,
  keeps summaries plus derived fields (`comms_total`, `first_at`,
  `last_at`, `last_comm`, `attachments[]`, open-only `requests`,
  `checks[{k,ok}]`). Active-cycle cards keep a 5-entry comms tail for
  the control pane; a top-level `recent` array (30 events) feeds the
  ticker. Page JS modal now fetches `GET /apps/board-api/card/<id>` on
  open for full detail. `_self_sig()` folds renderer mtime into the
  `--if-changed` state hash.
- `scripts/render-board.py` — same `_self_sig()` addition so template
  fixes force one re-render of the classic board too.
- `stacks/web/public/apps/board-gantt/js/data.js` — `normalizeCard`
  prefers the precomputed `first_at`/`last_at`/`last_comm`/`comms_total`
  fields; falls back to the old comms scan for full payloads
  (board-diagram inherits via gantt's fetchCards).
- `tests/board/test_control_pane_projection.py` — contract test updated
  for the compact payload shape.
- `docs/ssot/jobs/board/2026-11-24-board2-compact-cards-payload.yml` —
  trail doc.

## Result

- `board2/cards.json` = **881,355 bytes at 726 cards** (was ~13.2MB;
  comms alone were ~12MB). Target <1.5MB met with ~40% headroom.
- Render ~3.9s; `--if-changed` skip verified.
- Node stub harness smoke test: renderBoard + control pane + modal
  detail fetch → SMOKE OK.
- `tests/board` suite: **959 passed, 17 subtests passed** (~11min).
  Excluded `test_dispatch_close_out.py` — pre-existing environmental
  failure (gate shells `python3 -m pytest`; system python3 has no
  pytest). Verified failing on clean tree too; suite run via
  `/tmp/pps-venv`.
- Doing invariant: live board had 727 cards, all 12 doing cards with
  `action.status=running` — zero doing cards lacking a live
  claim/running action. No reaper change needed;
  `merge-sweep.py reap_stalled_claims` already enforces it via
  board-janitor on idc03.

## How to verify

- `python3 scripts/render-board2.py && wc -c
  stacks/web/public/apps/board2/cards.json` → ~881KB.
- Open any card modal on the board → devtools network shows
  `GET /apps/board-api/card/<id>` returning the full card.
- board-gantt still renders activity spans (uses first_at/last_at).
- Consumers checked: needs-you band (requests/ask kept), ticker
  (`recent` array), control pane (5-entry comms tail on active cards),
  board-gantt/diagram (normalizeCard compat), classic
  `board/cards.json` (unchanged — board-api legacy base).

## Not done / notes

- Worktree only — not pushed, not deployed. Merge + the next
  board-render-guard tick (60s) will ship it; `--if-changed` self-sig
  guarantees one re-render on merge even with no card writes.
- Payload will regrow ~1.2KB/card; at ~1,400 cards it approaches the
  1.5MB line — archive-done.py --cap 600 keeps the done column bounded.

lessons:
- cards.json consumers beyond the board2 page exist — grep public/apps/*
  for fetch('cards.json') before changing payload shape; board-gantt
  and board-diagram needed a compat shim.
- render-board2.py embeds all page JS in a PAGE raw-string template —
  node syntax-check the extracted script, not just the .py.
- --if-changed hash only covered the card dir; fold renderer mtime in
  or template fixes wait for an unrelated card write.
- tests/board/test_dispatch_close_out.py fails on hosts where system
  python3 lacks pytest — run the suite via a venv python.
