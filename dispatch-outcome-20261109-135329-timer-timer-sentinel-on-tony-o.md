# Dispatch outcome — timer-sentinel on tony-omen result=timeout (2026-11-09, OPS-1261)

## Verdict

Not a sentinel logic bug — **board-api write congestion**. The sentinel
does ~85 serial HTTP writes per run (1 GET + ~29 findings + ~28 heals × 2),
each with a 30s socket timeout, against a 180s `TimeoutStartSec`. In both
failure windows board-api writes were serializing behind `kanban-commit`'s
git operations on the idc03 served checkout, so calls queued past their
timeout and systemd SIGKILLed the run → `result=timeout` → the sentinel's
own pipeline carded itself.

## Evidence (verified on hosts via ssh)

- **11:00 run** (old script version e2d255b36): started 11:00:06,
  `WARN timer-alert-tony-dell-wp-cam-snapshot: fire failed: read timed out`
  11:01:08, killed 11:03:06. `kanban-commit.service` on idc03 was mid-run
  and failed 11:01:55 leaving the served checkout dirty.
- **13:50 run** (new version b4f7be59b, synced ~13:36): three `warn: close
  timer-alert-* failed (read timed out)` at exact 30s spacing
  (13:51:45/13:52:15/13:52:45), killed 13:53:10. `kanban-commit` on idc03
  hit a non-fast-forward at 13:48:44 and retried pull+push through
  13:50:40 (37.7s CPU) — overlapping the sentinel window exactly.
- **board-api is healthy**: POST /comment from tony-omen now 0.19–0.23s;
  typical full sweep is 15–40s. Known mechanism documented on done card
  `board-api-write-latency-60s-under-load-r-939aed` (OPS-1075): writes
  serialize on `/tmp/board-api.lock` + synchronous git in the served
  checkout; latency tracks checkout health (currently 119 ahead, dirty).

## Changes (dispatch branch `dispatch/20261109-135329-…`, not pushed)

- `scripts/ada/timer-sentinel.py`
  - `SENTINEL_BUDGET_SEC` (default 150s) wall-clock budget: `api()` raises
    `BudgetExhausted` when <10s remain and clamps each socket timeout to
    the remaining budget → run exits 0 with deferred writes instead of
    dying at 180s. Writes are idempotent/deduped; next 10min tick retries.
  - `fire()` again tolerates a single failed write (warn + continue) —
    b4f7be59b had narrowed the catch to HTTPError-400, so one stalled
    `urlopen` crashed the whole sweep.
  - `reconcile()` breaks cleanly on `BudgetExhausted` rather than grinding
    30s timeouts through every healable card.
- `docs/ssot/jobs/ada/2026-11-09-timer-sentinel-api-budget.yml` — incident
  record + residual notes.
- Posted RCA to card `timer-alert-tony-omen-timer-sentinel` via board-api.

## Verified fix behavior

Stub board-api sleeping 20s/write + `SENTINEL_BUDGET_SEC=45`: 2 writes
landed, 3rd deferred at 5s-left with `warn: …deferred to next tick`,
clean exit 0 in 40s (previously would have burned to the kill).

## Residual / follow-ups

- Fix reaches tony-omen via dispatch-branch merge + `chaba-repo-sync` —
  not deployed by this session (per rails). Until then the live script can
  still time out during kanban-commit overlap; the card auto-closes on the
  next green sweep.
- Client-timeout-but-write-lands still produces occasional dup comments
  (BrokenPipe seen on idc03 11:07) — pre-existing board-api semantics.
- `timer-sentinel-stale-respawn` (already carded) covers the adjacent
  stale-sweep re-fire gap.

## How to verify

```
ssh tony-omen 'journalctl --user -u timer-sentinel.service --since today \
  | grep -E "Finished|Failed|budget|deferred"'
```

After merge+sync: congested-window runs show `budget exhausted —
deferred` + `Finished` (exit 0), never `Failed with result 'timeout'`.
