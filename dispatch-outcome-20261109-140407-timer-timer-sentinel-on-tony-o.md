# Dispatch outcome — timer-sentinel on tony-omen, 2nd failure wave (2026-11-09 ~14:05, OPS-1261 follow-on)

## Verdict

**Not a regression of the budget fix — a git landmine.** The earlier
dispatch's fix (632e03f06, `SENTINEL_BUDGET_SEC`) merged and synced to
tony-omen, but `chaba-repo-sync.service` delivered it via an autostash
pop that **conflicted on `scripts/ada/timer-sentinel.py` itself**
(14:00:19). The file is outside `SAFE_PULL_GENERATED_RE`, so
git-safe-pull "kept it for manual merge" — leaving live conflict
markers in a file a systemd job executes every 10 min, while the sync
still reported `Result=success`.

The 14:00 run (`result=exit-code`, not timeout) was the collision in
action: the process imported the **pre-fix** bytecode at 14:00:10,
hit the known uncaught `TimeoutError` in `fire()` ~30s later, and its
traceback read the newly-conflicted file — which is why the journal's
line numbers looked impossible (`api` frame at line 61 showing
`class BudgetExhausted`).

## Timeline (verified on-host)

- 14:00:00–14:00:31 `chaba-repo-sync.service` pull --rebase --autostash;
  pop conflict kept at 14:00:19 → file has 5 conflict hunks, SyntaxError.
- 14:00:10–14:00:47 sentinel run on old bytecode → `TimeoutError` →
  exit 1 (`result=exit-code`).
- 14:06 restored file to upstream HEAD (`git restore --source=HEAD
  --staged --worktree`); `py_compile` clean; local drift retained in
  `stash@{0}`.
- **14:10:10 run: Result=success**, exit 0, 52.9s wall — 26 findings
  processed, 7 healed cards auto-closed, board-api writes landing.
  Sentinel REOPENed this card reflecting the 14:00 failure; its next
  reconcile auto-closes it once the timeline sweep records the success.

## Side findings

- idc03 `kanban-commit` still fires long git ops overlapping sentinel
  windows (14:03:08 "render lock held >60s — pulling anyway") — the
  congestion the budget fix was built for; served checkout now 5 dirty /
  14 ahead (was 119), draining.
- Other exec checkouts probed for the same landmine: idc03, mn01,
  tony-dell all clean (0 conflict markers). idc02 unreachable by ssh
  from this runner — its exec checkout unchecked; a conflicted file
  there would surface as its own timer-alert.
- Systemic gap carded: **`exec-sync-autostash-conflict-codefile`
  (SYS-1267)** — exec/readonly checkouts should resolve pop-conflicts
  upstream-wins (local diff is drift by definition, preserve as
  `.local-conflict-<ts>`) or at least flag loudly instead of silent
  success.

## Artifacts

- `docs/ssot/jobs/infrastructure/2026-11-09-repo-sync-autostash-conflict.yml` — incident record.
- Board comms on `timer-alert-tony-omen-timer-sentinel` (RCA + VERIFIED FIXED).

## How to verify

```
ssh tony-omen 'journalctl --user -u timer-sentinel.service --since today \
  -o short-iso | grep -E "Finished|Failed"'
# expect: Finished ticks every 10min from 14:10 onward; no SyntaxError
```
