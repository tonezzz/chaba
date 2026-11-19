# runner-agent-primer-coverage — outcome

## What changed

Option A implemented: the devin-lane task composition was extracted from
`kanban-dispatch.build_task` into a new shared module,
`scripts/board/dispatch_task.py`, so both dispatch claimers now render
the identical prompt — spec + TASK_RAILS + KNOWN_PITFALLS + KNOWN_GOOD +
RETRY_RAILS + REPORT_RAILS.

- **`scripts/board/dispatch_task.py` (new)** — TASK_RAILS / RETRY_RAILS /
  REPORT_RAILS moved verbatim (byte-identical, verified by import
  compare), plus `build_task_text(card, host, api, root=None)` returning
  `(task, primer_lines, good_lines)`. Primer env gates honored:
  `KANBAN_PRIMER=0`, `KANBAN_PRIMER_GOOD=0`; lp failures warn-only.
- **`scripts/board/kanban-dispatch.py`** — rail constants replaced by
  `dt.*` aliases (test compat), `build_task` delegates and keeps filling
  `LAST_PRIMER_LINES`/`LAST_GOOD_LINES` for start_pending's comms note.
- **`scripts/board/runner-agent.py`** — new `dt_module()` resolver using
  the exact `dr_module()` candidate pattern (DISPATCH_REPOS_DIR →
  `__file__.parent` → `~/CascadeProjects/chaba/scripts/board`), since the
  agent deploys as a single file to `~/.local/bin`. The devin path in
  `start_task` now calls `dt.build_task_text(card, HOST, API)`; module
  unresolvable or a build exception falls back to the legacy
  spec + RAILS — warn-only, never a claim blocker. `claim_pass` posts
  `primer injected N lesson(s): ...` (+ ` | good: ...`) to card comms
  after "started", same message shape as kanban-dispatch start_pending.
- **`tests/board/test_runner_agent_primer.py` (new)** — 9 tests.
- **`docs/ssot/jobs/kanban/2026-11-19-runner-agent-primer-coverage.yml`** —
  job trail.

## Decisions recorded (scope note)

- **Devin path only.** `start_opencode_lane` and `start_kk_mac_lane` are
  untouched — bounded profile contracts must not get extra prompt
  blocks. `executor=claude` shares the devin task build, so it gains the
  primer too (claude is a full agent, not a bounded contract).
- **Option A over B** — the import boundary is clean: the shared module
  sits beside `lesson_primer` in `scripts/board`, and runner-agent
  already had the single-file→checkout resolution pattern to copy.
- When `dispatch_task` resolves, the devin lane gets TASK_RAILS verbatim
  (vs its thinner legacy RAILS): gains the CI-pipeline note, the
  `kind:"comment"` answers note, and the `lessons:` tail that self-seeds
  the primer corpus. Legacy RAILS remains the no-checkout fallback.
- Deploy note: runner hosts pick up `dispatch_task.py` via their chaba
  checkout sync (chaba-repo-sync.timer), not the runner-agent scp. On a
  stale checkout the feature no-ops warn-only until the checkout
  refreshes.

## Verification

- `python3 -m unittest tests.board.test_runner_agent_primer` — 9/9 ok:
  KNOWN_PITFALLS renders on the devin path, KNOWN_GOOD renders,
  KANBAN_PRIMER=0 suppresses (lp.build never consulted), RETRY_RAILS on
  attempts>0, REPORT_RAILS on report-linked cards, unresolved/raising
  module falls back to plain RAILS, and claim_pass posts the
  "primer injected 2 lesson(s): ... | good: ..." comms note.
- `python3 -m unittest discover -s tests/board` — 643 tests, all green
  except one pre-existing environment error: `test_ada_job_envelope`
  fails to import `pytest` (not installed in this env) — unrelated.
- Real smoke (LESSON_BANK=0): `dt_module()` resolved on this host and
  `build_task_text` on this very card returned 8 primer + 4 good lines;
  KNOWN_PITFALLS and "This is attempt 2" both render — the primer is
  already picking up this card's own prior failures, which is the loop
  working.
- Comms evidence: this session itself was dispatched by runner-agent
  pre-fix (its prompt carried the thin RAILS, no primer); the next
  claimed devin-lane card's comms will show the `primer injected` note.

lessons:
  - runner-agent deploys via scp of runner-agent.py only — new module
    deps must resolve through the host's chaba checkout (dr_module
    candidate pattern) or the feature silently no-ops.
  - the devin-lane task build lives in start_task (~line 3650), not the
    ~1816 the card spec cited — the file grew ~2.6k lines since.
  - tests patching `lesson_primer.build` keep working across a refactor
    as long as the moved code does `import lesson_primer` — same
    sys.modules object gets patched.
