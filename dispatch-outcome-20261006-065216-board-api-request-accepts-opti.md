# dispatch outcome — board-api /request suggested option

Card: kanban-request-suggested-answer
Branch: dispatch/20261006-065216-board-api-request-accepts-opti (1 commit, 08ecd6d9)

## What I found

The core was already merged in dcffce02 ("suggested answers" batch):
`do_request` accepts + validates `suggested` against `options[]`, and
`reqAnswerHtml` (shared by the modal requests section and the Needs You
strip) renders the suggested option ★ + emerald/bold. Clicking the ★
option already answered in one click, but the spec's explicit
"accept suggestion" affordance was missing, there was no test coverage,
and the SSOT schema didn't document the field.

## What changed (this commit)

- `scripts/render-board.py`: `reqAnswerHtml` now appends a
  `✓ accept suggestion` button whenever `r.suggested` is set — posts the
  same value the suggested option button would (handles the dict-option
  `id — label` composite). Shows in both the modal and Needs You strip.
- `scripts/board/board-api.py`: selftest coverage for `suggested`
  (requires-options, must-match, string + dict option forms); docstring
  notes the recommendation-never-default convention.
- `docs/ssot/kanban/ssot.kanban.yml`: `requests[].suggested` schema doc +
  updated `/request` endpoint doc.
- `docs/ssot/jobs/kanban/2026-10-06-request-suggested-option.yml`: trail.

## Live proof (the spec's "update 2-3 open requests")

No open requests existed anywhere on the board to retrofit, so I raised
three fresh ones via `POST /request` — same write path, and they're real
decisions:

- `kanban-request-suggested-answer` — "close this card?" sug `Close`
- `dispatch-merged-branch-prune` — "close now or keep through one weekly
  run?" sug `Keep through one weekly run`
- `lab-disk-trend-watch` — "close or keep open a week?" sug
  `Keep open a week`

All three show `suggested` in `GET /cards` and appear in the Needs You
strip with the ★ marker (live page already has the marker code; the
accept button ships on merge). A fourth `to:devin` self-check request was
raised and answered via `/respond` — status flipped to `answered`,
`answer: yes`, comms recorded `devin | answered <rid>: yes` (option +
actor path verified live, no false tony attribution).

## Verify

- `python3 scripts/board/board-api.py --selftest` — passes (new cases).
- `python3 scripts/render-board.py` — renders clean; extracted
  `reqAnswerHtml` run under node produces ★ + `✓ accept suggestion` with
  correct `data-val` for string and dict options.
- Live: open the board, Needs You strip → three requests show ★ on the
  suggested option; after merge they also show the accept button.
  Answering any option records the option text + actor in comms.

## Caveats

- The live board renders from the served checkout; the `✓ accept
  suggestion` button appears only after this branch merges (the ★ marker
  is already live).
- `suggested` is informational — the API never auto-answers, per the
  card's convention.
