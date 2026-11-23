# Dispatch outcome — ada-dispatch-approve-button (attempt 2)

## What changed

Recovered attempt 1's work (it died on a provider rate-limit, not a code
failure) and finished the remaining pieces.

**Cherry-picked `4df0e492` onto this branch** (`d691a0610b`) — the core
from attempt 1:

- `scripts/board/board-api.py` — `_exec_option_action`: on `/respond`,
  a selected dict option carrying `action: queue|retry|close|hold|none`
  executes through `do_action` **in the same write** — the click IS the
  approval signal (missing piece 1 + 2). Applies to both `requests[]`
  and the card-level `ask:`. Busy-card deferrals and guard refusals stay
  unexecuted so answer-sweep keeps them as backstop. Idempotent
  re-answer clears the stale `executed` stamp. Selftest coverage for all
  paths.
- `scripts/board/waiting_cards.py` — `notify_lifecycle` gains
  `verified`→milestone, `unverified`→alert events routed via `/publish`.
- `scripts/board/kanban-dispatch.py` + `merge-sweep.py` — the merge
  gate's verdict is pushed to Tony (verified → auto-close announced;
  unverified → one-shot alert on first hold). Close-the-loop (missing
  piece 3).
- `docs/ssot/ssot.procedures.yml` — `ada-approve-dispatch` procedure row.

**New in this run** (`f4ec36662d`):

- `scripts/board/approve-ask.py` — canonical emitter: raises a `/request`
  whose options are `{id,label,action}` dicts (default menu:
  Approve→queue / Hold→hold). `--approve-action retry|close`,
  `--extra-option ID|LABEL|ACTION`, `--options-json`, `--suggested`,
  `--dry-run`. Duplicate request ids are a no-op (emitters run every
  pass). BOARD_API env or the tailnet default.
- `tests/board/test_approve_ask.py` — 8 tests over payload shape,
  parse_extra, option overrides.
- `docs/kb/ada-approve-dispatch-loop.md` — runbook: flow diagram, piece
  table, emitter usage, click-execution semantics, verification,
  boundaries.

## The three missing pieces vs spec

1. **Click-level approval signal the dispatch gate accepts** — dict
   options on `/request` + `_exec_option_action` on `/respond` (queue
   flips `action.status` claimable in the same write).
2. **Menu option that can trigger dispatch** — `approve-ask.py` emits
   `{action: queue}` options; `do_request` validates the action enum at
   the door. `next/next_choice` stays read-only by design.
3. **Auto close-the-loop** — `verified`/`unverified` lifecycle events
   → `/publish` → Telegram milestone/alert; merge-sweep auto-closes the
   verified card and pushes held verdicts once.

## Result

- `python3 scripts/board/board-api.py --selftest` — ok
- `python3 -m unittest` on answer-sweep, merge-sweep, dispatch_close_out,
  board_api_mutations, deploy_preflight, approve_ask — 165 tests green.
- Status `defined` (not `verified`): board-api on idc03 runs the old
  build until this branch merges and the repo sync lands it — the live
  click→queue path can't be e2e-proven from a worktree.

## How to verify after merge/deploy

```bash
python3 scripts/board/approve-ask.py <test-card> "Dispatch the fix?" --dry-run
python3 scripts/board/approve-ask.py <test-card> "Dispatch the fix?"
# click Approve on the board -> action.status=queued immediately,
# requests[].executed = "<date> queue@respond"
# after the run: Telegram milestone "verified", card auto-closes
```

lessons:
- Dispatch retries get a fresh worktree — previous attempt's commits live on the old `dispatch/<ts>` branch; check `git log HEAD..dispatch/<old-branch>` and cherry-pick before redoing work.
- Board-api writes can 429/409 with "write lock saturated" — retry comms once after ~5s rather than dropping them.
- Hyphenated board scripts need `importlib.util.spec_from_file_location` in tests (see test_answer_sweep.py), not a plain import.
- Attempt 1 died on a provider rate-limit mid-verification, not a code failure — when a prior run's last comm says code landed, recover-and-finish beats re-deriving.
