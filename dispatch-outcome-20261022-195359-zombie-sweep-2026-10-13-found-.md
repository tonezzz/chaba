# dispatch outcome — queue-type-starvation-guard

## What was wrong

`/action do=queue` (and both `do_create` queue paths) sets
`action.status=queued` on any card, but `kanban-dispatch.py` claims only
`action.type == dispatch`. A card typed `manual`/`devin`/`self`/`container`
queued that way starves forever — the 2026-10-13 zombie-sweep found 6 of
them sitting for days with zero claims, and the dispatcher's skip was a
bare `continue` with no log line.

## What changed (option b, plus the warn half of a)

Picked the observability route — no queue semantics changed, nothing is
auto-converted:

- `scripts/board/board-api.py` — new `queue_starve_warn()`. Wired into
  all three queue paths: `do_action` verb=queue, `do_create` re-arm
  (`on_exists:"queue"`), and `do_create` new-card `queue:true`. When a
  card is queued with `action.type != dispatch`, the response message
  carries `WARNING: action.type=... — will starve in queue` and a chaba
  comms line is stamped on the card. Warns rather than flips the type —
  a manual card queued by hand may legitimately mean "not for dispatch".
- `scripts/board/kanban-dispatch.py` — the non-dispatch skip now prints
  `<id>: skipped — action.type 'x' is not dispatchable` per pass,
  matching how the other claim gates (push guard, host cap) report.
- `scripts/board/board-invariants.py` — new invariant class **Q1**: card
  `action.status=queued` with non-dispatch `action.type` and `updated`
  >24h old gets flagged. It rides the existing 4-hourly `--alert` timer
  on idc03/tony-dell and drops a deduped
  `invariant-starved-queued-cards.yml` in focus-inbox — that is the
  "sweep reports starved queued>24h" leg, with no new unit needed.
- `docs/ssot/infrastructure/ssot.jobs.yml` — board-invariants job note
  updated to list Q1.
- `tests/board/test_queue_starvation.py` — 8 new tests covering the warn
  paths (incl. "type is NOT auto-flipped"), the dispatcher skip log, and
  the Q1 age gate.

## Result / verification

- `python3 -m unittest tests.board.test_queue_starvation` — 8/8 pass.
- Full board suite: 169 tests pass, 2 skipped (pre-existing — pytest not
  installed on this host).
- Live `board-invariants.py` run over the real card dir: all classes ok.
  The one currently-starved card in this snapshot
  (`migration-stragglers-orphaned-units`, `type: manual`, `queued`) has
  `updated: 2026-10-22 19:33`, i.e. <24h, so Q1 correctly stays quiet;
  it will alert on the next 4h scan once it crosses 24h unclaimed.
- Commit `ed7858be` on session branch
  `dispatch/20261022-195359-zombie-sweep-2026-10-13-found-`. Not pushed
  (dispatch rails); the kanban close-out will merge it.

## Follow-ups (not done — outside this card's scope)

- The live board still holds whatever starved cards zombie-sweep found;
  the Q1 alert will now enumerate them on the next scan. Each needs a
  human/`kanban-act` decision: flip `type` to `dispatch`, or `do=hold`.
- If Tony prefers auto-conversion over warning on `do=queue`, that's a
  one-line change now that `queue_starve_warn` exists.

lessons:
- board-api has THREE queue paths (do=queue, create queue:true, on_exists:queue re-arm) — a guard on only one leaks.
- board-invariants.py is the right home for "silent starvation" reports: read-only, already on a 4h --alert timer, dedupes by inbox filename.
- board-api tests need BOARD_API_COMMIT=0 and a tmp CARD_DIR; _commit_write no-ops on non-repo paths anyway.
- Q1 uses card `updated` as the starvation clock — any card touch resets it, which is correct: a recently-touched starved card means someone looked at it.
