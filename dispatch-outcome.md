# Dispatch outcome — board-api-hardening

## What was done

Hardened `scripts/board/board-api.py` per the card spec, still single-file
`BaseHTTPRequestHandler`, no new deps (re/hashlib are stdlib).

Branch: `dispatch/20261004-180001-harden-scripts-board-board-api`
Commit: `56f7a27d fix(board): harden board-api — respond attribution, validation, /request`

**Changes in `scripts/board/board-api.py`:**

- `/respond {id, request_id, answer, from?, reopen?}` — `from` validated
  against ACTORS, defaults to `tony` (board UI sends none, backward
  compatible). 400 `answer required` on empty/whitespace answer. 400
  `already answered` when the request is already answered, unless
  `reopen` is truthy — reopen re-answers and logs `re-answered <rid>: ...`.
- `/comment` — 400 `text required` on empty/whitespace text.
- New `POST /request {id, ask, request_id?, options?, from?}` — appends
  `{id, ask, status: open, options?}` to the card's `requests[]`; id is
  `request_id` or `slugify(ask)` (slug + 6-char sha1 so Thai/non-ascii asks
  and near-identical slugs can't collide). 400 `ask required` /
  `duplicate request id <rid>`. Comms entry `raised request <rid>:
  <ask[:120]>` under the validated actor (default tony).
- New `actor()` helper; docstring now states all card writes go through
  the API and direct YAML edits must hold `/tmp/board-api.lock` first.
- `--selftest` flag: pure-function smoke test of respond/request
  validation, attribution, reopen, slugging.

**Also updated (kept in sync):**

- `scripts/board/kanban-dispatch.py` — TASK_RAILS now tell dispatched
  sessions to raise questions via `POST {api}/request` instead of editing
  card YAML (the flock race the spec called out).
- `docs/ssot/kanban/ssot.kanban.yml` — `write_path.endpoints` +
  `task_rails` updated to the new contract.
- `docs/ssot/jobs/infrastructure/2026-10-04-board-api-hardening.yml` —
  job trail entry.

## Verification

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`
- Live curl run: patched server on `BOARD_API_PORT=8878` against the
  worktree's `kanban-selftest` card — every spec case verified:
  empty answer 400, missing ask 400, duplicate request_id 400,
  unknown/missing actor 400, empty comment 400; `/request from=ada`
  created an open request and logged `raised request st1` under `ada`;
  respond `from=ada` logged `answered st1` under `ada`; re-answer 400;
  `reopen:true` logged `re-answered st1` under `tony`; auto-slug id
  `auto-generated-id-please-1c0a43` created with `status: open`.
  Card YAML inspected, then restored via `git checkout`.
- `node scripts/ssot-validate-all.mjs` — 971/971 valid.
- Backward compat: `render-board.py` JS posts `{id, request_id, answer}`
  (no `from` → tony); `/comment` still requires `from`; old 400 paths
  unchanged.

## Board triage addendum (same session, "do all")

All 15 open board requests answered via the live API; needs-you count is
now 0. Verified answers: tuya dup entry (websocket evidence — remove
newer `01M19NJ76J0020RJ`, its 28 entities are dead stubs while the old
entry's 67 are live), CAM01 = Noble-A entrance gate (vms-snap still
frame), sunsynk bat34 (`battery_{1,2,3}_*` exist, no `battery_4_*` —
4th bank not in HA). Remainder answered as recommendations with a devin
provenance comment per card (answers log under `tony` — live board-api
is still pre-patch). Next-step comms posted on all 13 affected cards.

## Deploy (out of scope — needs approval)

Merge branch → pull `chaba-tony-dell` live checkout →
`systemctl --user restart board-api.service`. New dispatch rails take
effect on the next kanban-dispatch cycle after the live pull.
