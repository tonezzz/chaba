# dispatch-claim-eligibility-visibility — outcome

## What was wrong (OPS-1097)

Three `ops0790-rollout-*` dispatch cards sat queued ~3h on 2026-11-07:
`action.labels: [exec]` matched no runner's `RUNNER_LABELS`, and
`target_host: idc03` couldn't satisfy them either. Every claimer just
skipped the cards — kanban-dispatch's label gate was a bare `continue`
(not even a log line), `queue_starve_warn` only covered
`action.type`/`executor=manual`, and runner-agent defer notes only
covered push/gpu/executor. The starvation mode was invisible.

## What changed

**Shared verdict — `scripts/board/dispatch_repos.py`**
- `fleet_capabilities()` parses the `runner_fleet` prose in
  `ssot.kanban.yml` into `{host: {labels, types}}` — the declared claim
  surface (mtime-cached, `{}` on unreadable input = never flag).
- `unsatisfiable_reasons(card, fleet?, local_host?, push_probe?)`
  returns deterministic gaps only: pins (`action.host`/`target_host`/
  `runner`) naming no declared runner, conflicting host+target_host
  pins, labels satisfied by no single declared host, served-type
  mismatch on a pinned host, unknown `action.executor`, and push-guard
  failure **only when the sole eligible runner is the checking host**
  (the local `git push --dry-run` probe is real evidence; a remote
  runner's push state is unprovable declaratively and already covered
  by live `<host> defers: push guard` notes).

**Queue time — `scripts/board/board-api.py`**
- New `queue_unclaimable_warn()` runs beside `queue_starve_warn` in
  `do_action("queue")` and both `do_create` queue paths: writes a chaba
  comms line, sets `awaiting_action`, and returns the reason to the
  queuer. The card is flagged the moment it's armed.
- `queue_starve_warn` no longer calls container/script cards doomed —
  runners serve those types.
- `/comment` accepts `awaiting_action: true` so remote runners can
  raise the triage flag in the same write as a defer note.

**Eval time — `scripts/board/kanban-dispatch.py`**
- `_flag_unclaimable()` at every queued-card skip (host pin, type,
  executor, target_host, labels, push, runner pin): writes
  `unclaimable by the declared runner fleet: <reasons>` comms +
  `awaiting_action`, debounced on the card's own comms (`new`/`present`/
  `''` tri-state — a present flag suppresses the noisier per-host note
  and never re-renders the board every pass).
- `_defer_note()` writes `<host> defers: missing labels [...]` /
  `push guard: ...` comms for per-host refusals — the served-side twin
  of runner-agent's `note_defer`; label skips were log-silent before.
- Every skip now prints a reason to the journal.

**Eval time — `scripts/board/runner-agent.py`**
- `note_defer()` gains `awaiting=` and `claim_pass` posts
  `kind=unclaimable` defer notes (`awaiting_action` over `/comment`)
  when `dr.unsatisfiable_reasons` reports a fleet gap — remote eval
  flags even while the served dispatcher is down.

**Declared surface — `docs/ssot/kanban/ssot.kanban.yml`**
- `runner_fleet` now declares tony-dell's push labels
  (`push:chaba,push:ada-voice,push:sunsynk-card,push:mddb-fork,
  push:gods-eye-view`) — the prose already said it pushes all dispatch
  repos; the parse needs it declared to not flag pinned-to-dell cards.
- The `labels` field doc now documents the visibility mechanism.

**Trail** — `docs/ssot/jobs/kanban/2026-11-08-dispatch-claim-
eligibility-visibility.yml`.

## Verify

- `python3 -m unittest tests.board.test_queue_starvation` — 20 tests:
  fleet parse, the ops0790 reason verbatim (`idc03 lacks labels
  ['exec']`), pin/executor/push legs, queue-time flag+`awaiting_action`,
  eval-time flag + defer note + debounce. Plus the four neighboring
  suites (`test_executor_contract`, `test_runner_push_guard`,
  `test_board_api_mutations`, `test_claim_order`: 102 tests) and
  `test_board_api_reads`/`test_runner_agent_lane`/
  `test_kanban_dispatch_rails` (41 tests) — all green.
- Reproduce live: queue a card with `action.labels: [exec]` → immediate
  WARNING + `awaiting_action`; on the dispatcher's next pass its comms
  gain `unclaimable by the declared runner fleet: labels ['exec']
  satisfied by no declared runner ...`.

## Notes / follow-ups

- `runner_fleet` prose is still the hand-synced declared surface — a
  machine-readable fleet table (or per-host `/ready` label reports)
  would remove parse drift.
- Remote push truth stays with live defer notes + fleet-health's
  `runner-auto-queue` card; the declarative check deliberately never
  flags push it can't prove.
- `board-invariants` Q1 could add queued-declared-unsatisfiable >24h as
  a third tripwire (out of scope here).

lessons:
- `git check-ignore` exit 0 prints the paths — rendered board files
  (index.html/cards.json) are ignored, so tests that re-render don't
  dirty the diff.
- kanban-dispatch's save_card stamps `updated`; an every-pass write
  would reset the starvation clock — debounce on the card's own comms
  text instead.
- 'unproven' is not 'failed': remote `git push --dry-run` results
  belong to per-host defer notes; declarative flags need local or
  declared evidence only.
