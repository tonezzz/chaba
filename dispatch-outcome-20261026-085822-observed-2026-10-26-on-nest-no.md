# merge-sweep-resurrects-closed-cards — outcome

## What was found

Git history on `docs/ssot/kanban/cards/nest-node-hardware.yml` reconstructs the
incident precisely:

- 07:16 — `drain_verified` wrote column=done/status=done/auto_close
  (updated=07:16) — but the committed file at `482e7b4c` already shows
  `column: doing` **with** `auto_close`. A concurrent card write still
  carrying doing/running arrived with a newer `updated` (07:18), and the
  `card-union` merge driver resolves board scalars (`column`, `action.*`
  per-key) to the newer-`updated` side — the merge produced the hybrid:
  doing + running + auto_close + verified.
- 07:31 — the stale-session pass read the resurrected state literally:
  `stale_running` and `session_gone` comms+stamps on a verified,
  delivered card. The stamp writes also bumped `updated` to 07:31,
  crowning the regressed scalars for every later union merge.
- 08:29 Tony re-closed; 08:49 the lifecycle guard bounced done→doing on
  a separate verify-evidence rule (legitimate, unrelated).

So the union merge did the scalar resurrection; the sweep's part was
treating a verified/auto_closed card as a live stale session and
re-stamping it — misleading notes plus an `updated` bump that cemented
the regression.

## What changed — scripts/board/merge-sweep.py

- `TERMINAL_COLUMNS` (`done`/`verified`/`parked`) + `terminal()`;
  `sweep_card` returns immediately on a terminal column even when
  `action.status` regressed — closed cards are never sweep work.
- Verified routing: `action.verified is True` never draws
  `stale_running`/`session_gone`/`no_repo` noise — a gone session is the
  expected post-delivery state. Verified cards with unreachable sessions
  go to `drain_verified` (self-healing re-close). Reachable sessions
  keep the existing verified path (verified_unmerged anomaly flag, wt
  GC). `verified`+`failed` also falls through to the verified path.
- `drain_verified` is reopen-aware via `reopened_after_close()`: a
  deliberate-reopen comms marker after the last close ('moved done ->',
  '[lifecycle] bounced done->', 'reopen*') means a human/guard owns the
  workflow fields — the drain stands down. Unmarked regressions
  (union-merge resurrections leave no comms) get re-closed. Re-checked
  under the lock too.
- `stamp()` refuses terminal cards under the lock and no longer bumps
  `updated` (`locked_edit(touch=False)`) — bookkeeping must not crown
  stale scalars in future card-union merges.
- `fail_attempt()` and the fresh-verify `mark()` refuse under the lock
  on terminal or deliberately-reopened cards.

## Earlier reopen_events check (per card spec)

~50 cards carry stale/session_gone stamps + verified/auto_close, but
most are stamp-then-close (normal flow). The resurrection signature —
post-close sweep noise with no human reopen marker — also appears on
`news-situation-summaries` (closed 10-15 16:29, noise 20:29) and
`guard-card-yaml-syntax-validation` (closed 10-12, noise 10-22).
`openclaw-bench` had a done→backlog→doing move 10-23 but via a board-api
requeue — a different path. The qc-scoreboard column snapshot lives only
on the served host (`reports/qc-scoreboard/column-snapshot.json`, not
committed), so the counter itself can't be diffed from a worktree; the
git-history signature is the evidence. Residual risk noted: the union
driver can still regress scalars when a stale write carries a newer
`updated` (e.g. clock-skewed writer) — now mitigated consumer-side by
the re-drain; a driver-side fix would need its own card since real
reopens are legal.

## Files

- `scripts/board/merge-sweep.py` — guards + routing above.
- `tests/board/test_merge_sweep.py` — updated
  `test_verified_stale_running_drains` (verified cards no longer get the
  stale_running flag); new `test_verified_session_gone_drains_not_flags`
  (the incident repro), `test_terminal_column_never_touched`,
  `test_deliberate_reopen_not_redrained`.
- `docs/ssot/jobs/kanban/2026-10-26-merge-sweep-terminal-guard.yml` —
  trail record.

## Verify

`python3 tests/board/test_merge_sweep.py` → 34 tests, all green.
Live check after the next merge-sweep pass: the incident card's sweep
stamps stay historical; any future verified+regressed card re-closes
itself within one pass instead of posting stale/session_gone noise.
