# merge-sweep verified gate — verified means delivered, not merged

**Result: done.** `scripts/board/merge-sweep.py` now gates every
`action.verified=True` stamp (both the fresh-merge path and the
already-merged path) on three conditions, per the card spec:

- **(a) unit exit==0** — `unit_exit()` walks a precedence chain of surviving
  evidence: `$TASK_DIR/exit_code` (written by the devin-dispatch wrapper,
  survives `systemd-run --collect` GC) → `meta.json.result` (watch stamp) →
  `systemctl` unit fields (only trusted when `LoadState=loaded` — a
  never-loaded/collected unit reports phantom `Result=success` /
  `ExecMainStatus=0`) → `journalctl` `Succeeded./Failed with result` lines →
  the card's own finish comms (`finished (ok): exit=N`, `run finished
  (<state>)`) → `status==done` as the weakest tier for pre-`exit_code` tasks.
- **(b) produced work** — `produced_work()`: `dispatch-outcome-<tid>.md` in
  the head tree (research sessions deliver only the doc), else a non-empty
  `git diff` of the session's base vs head. For unmerged heads that's
  `merge-base..head`; for heads already in base via a merge's second parent,
  `_containing_merge()` walks first-parent merges and diffs `M^1..head`.
  `head == base tip` or an old first-parent base commit = provably empty.
- **(c) auto_done_when** — `auto_done_ok()` imports
  `scripts/ada/kanban-act.py`'s `CHECKS` vocabulary; a self `verified_true:`
  entry counts the a+b gate itself. Failing/unevaluatable checks **defer** to
  kanban-act — never a retry trigger.

Verdicts: `verify` → `verified=True`; `fail` (no deliverable, or nonzero exit
on *unmerged* work) → `verified=False` + `last_failure` + `status=queued`
under `KANBAN_AUTORETRY`/`max_attempts`, else `status=failed`; `hold` (work
landed but exit unprovable, or a too-old merge, or nonzero exit on work that
is already merged) → merge still lands, verified withheld, one comms flag;
`defer` → merge lands, verified withheld for kanban-act's cadence.

The nest-mgr repro is the `head == base_tip` + clean-exit case:
`test_nothing_produced_fails_and_requeues` — before this change it was
stamped verified; now it marks the attempt failed and requeues.

## Changed

- `scripts/board/merge-sweep.py` — probes extended (remote probe + local
  `_local_exit_evidence` collect `exit_code`/unit/journal), gate section added
  (`unit_exit`, `_containing_merge`, `produced_work`, `_kanban_act`,
  `auto_done_ok`, `verify_gate`, `fail_attempt`), `sweep_card` rewired to
  evaluate the gate before any merge/stamp, docstring updated.
- `tests/board/test_merge_sweep.py` — fixture writes `exit_code=0`; the old
  "empty session → verified" test now asserts fail+requeue; new tests cover
  failed-unit-no-merge, attempt cap, hold-on-missing-evidence, auto_done_when
  defer + `verified_true:` idiom, outcome-doc-only deliverable, and the
  already-merged-via-second-parent diff path.
- `docs/ssot/jobs/kanban/2026-10-10-merge-sweep-verified-gate.yml` — job doc.
- `docs/ssot/kanban/cards/kanban-autoretry-off-by-one.yml` — filed: the
  `merge_pending_one` retry path this was meant to mirror double-counts
  `attempts`, so at default `max_attempts=2` auto-retry never fires.
  `fail_attempt` implements the documented semantics (attempts counted at
  claim; requeue while `attempts_used < max_attempts`) instead of mirroring
  the dead math.

## Verified

- `python3 -m unittest discover -s tests/board` — 60 tests, 0 failures
  (19 merge-sweep tests incl. 6 new gate tests).
- `merge-sweep.py --dry-run` on the worktree card dir — clean, probes collect
  the new fields.
- `unit_exit` tier table exercised directly; the `LoadState=not-found`
  phantom-success trap is handled.

lessons:
- `systemctl --user show` on a never-loaded unit returns defaults
  (Result=success, ExecMainStatus=0) — only LoadState=loaded means the fields
  are real. --collect'd units are LoadState=not-found after exit.
- the durable exit record for dispatch tasks is $TASK_DIR/exit_code (the
  devin-dispatch wrapper writes it); meta.json's `result` is the
  devin-dispatch-watch stamp, secondary.
- 'already merged' ≠ 'produced work': head==base_tip passes the ancestor
  check while proving the session committed nothing — diff the branch's base,
  not base tip.
