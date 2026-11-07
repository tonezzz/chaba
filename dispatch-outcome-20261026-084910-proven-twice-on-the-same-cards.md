# dispatch-empty-closeout-verification-gap — outcome

## Root causes found (all confirmed in code)

1. **`finished (ok)` on a failed unit**: devin-task units run under
   `systemd-run --collect` — at exit the unit unloads and `systemctl
   show` returns *defaults* (`ExecMainStatus=0`, `Result=success`).
   `runner-agent.collect()` read those fields verbatim → every collected
   unit reported ok. `kanban-dispatch.finish_one` used `is-active` →
   collected unit = inactive → "treat as finished". The task-dir
   `exit_code` file (written by the devin-dispatch wrapper for exactly
   this reason) was never consulted.
2. **`verified` on a zero-commit push**: `dispatch_repos.close_out`
   only special-cased `head == base_tip`. Once origin/master advanced
   past the commit the worktree was cut from, a zero-commit session
   head was still an ancestor → `merged=True, noop` → callers stamped
   `verified=True` → merge-sweep drained → auto-closed. `merge_state`
   already computed `on_first_parent`/`empty_session` for this shape;
   close_out ignored it.
3. **KNB-0893 resurrection (same file)**: `locked_edit` bumped
   `updated` on bookkeeping writes — on a stale checkout the stamp's
   fabricated-newer `updated` wins the card-union driver's scalar
   resolution → stale `column=doing/status=running` beats upstream's
   `done` on the next pull.

## What changed

- `scripts/board/dispatch_repos.py` — new `unit_exit_evidence(tid)`
  (exit_code file > meta.result > systemctl fields only while
  `LoadState=loaded` > journal Succeeded/Failed; None = unproven, NOT
  ok). `close_out` now treats any `on_first_parent` ancestor head as
  `noop + empty_session` — only a head that entered base through a
  merge's non-first parent reports merged. `close_out_notes` says the
  empty session plainly instead of staying silent.
- `scripts/board/kanban-dispatch.py` — `finish_one` checks exit
  evidence: proven-failed → `status=failed` (no review, no merge);
  unproven → finishes with a "no exit record" comms note. `merge_pending_one`
  stamps `verified` only on proven exit (probed outside the card lock);
  merged-but-failed/unproven withholds it for merge-sweep's gate.
- `scripts/board/runner-agent.py` — `collect()` rewritten with the same
  precedence (inlined — remote hosts can carry a stale dispatch_repos);
  unproven → `ok=False`. `start_opencode_lane` now writes
  `exit_code` like the devin-dispatch wrapper.
- `scripts/board/merge-sweep.py` — `verify_gate` tags produced-work
  failures `zero_commit`; `fail_attempt` stamps
  `action.sweep.zero_commit` (QC input). `locked_edit(touch=False)` for
  bookkeeping writes (stamps, comms fallback) — `updated` is only
  fabricated for real workflow mutations (KNB-0893). `sweep_card` skips
  cards outside doing/review. `main()` refuses to run when the card
  checkout's `chaba-role` exists and isn't `served` — a non-writer
  board is stale by definition.
- `scripts/qc-scoreboard.py` — new `zero_commit_dispatches` counter
  (sweep stamp + `last_failure` text fallback), rendered as a scoreboard
  row + card-id list + summary part.
- `docs/ssot/jobs/kanban/2026-10-26-dispatch-empty-closeout-verification.yml`
  — trail doc: incident, root causes, design, verification.
- Tests: +14 new/updated cases across the three touched surfaces —
  moved-base empty head (the exact burn), merged-via-second-parent
  still verifies, collect() precedence x6, finish_one x3,
  verified-withheld x2, sweep zero_commit stamp, terminal-column
  guard, `updated` preservation.

## Result

`tests/board/`: **204 passed**, 2 failed — both are PRE-EXISTING
baseline-test-gate failures (`test_gate_red_suite_holds_merge`,
`test_gate_timeout_holds_merge`, broken by commit `010af8dc5`'s
baseline-aware gate; verified identical on unmodified HEAD via
stash). Not touched by this change.

## How to verify

- `python3 -m pytest tests/board/ -q` → 204 pass.
- Next empty dispatch should show: `finished (failed)`/finish-failed
  comms (not `ok`), `verified gate failed — no delivered work` +
  auto-retry, `action.sweep.zero_commit` on the card, and a
  `Zero-commit dispatches` row on the QC scoreboard.
- `git diff` review of `close_out`'s ancestor branch, `collect()`,
  `finish_one`, `locked_edit`.

## Lessons

- `systemctl show` on a `systemd-run --collect` unit is a lying oracle —
  always gate on the wrapper's `exit_code` file first.
- "Ancestor of base" ≠ "delivered": an old base commit is an ancestor
  too. Only non-first-parent ancestry proves work reached base.
- Never fabricate `updated` on bookkeeping writes to shared YAML —
  timestamp-ordered merge drivers treat it as "newest wins".
