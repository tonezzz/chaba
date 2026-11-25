# Dispatch outcome — ada-review-refresh-log-shipper-timeout

Card: `ada-review-refresh-log-shipper-timeout` (ref ADA-1166)
Branch: `dispatch/20261125-103752-ada-review-refresh-service-on-` (3 commits, not pushed)

## What was found

- The failing unit runs on **tony-omen** (investigation done over ssh from
  this idc02 worktree). Its user journal only retains the current boot, so
  the failing run's journal is gone; the 2026-11-25 08:45 run **succeeded**
  (9min18s wall / 1min27s CPU). The failure streak was 11-08→11-09 per the
  timer-alert card.
- Chain: `ada-review-refresh.service` → `export-transcripts.py` →
  `subprocess.run(log-shipper.py, timeout=600)` invoked with **no args** =
  fleet fallback lane, all 8 hosts, 500 docs/host, **sequential per-doc
  `/add` posts**. `TimeoutExpired` was uncaught → exit 1 → the whole
  ~15-step digest chain died.
- Standalone timings today (pre-fix code): fleet run 3m53s / 1151 docs;
  `--self --max-docs 2000` 32s / 737 docs; per-host timers 40-65s.
  MDDB healthy (~20-80ms). The 600s budget only holds while `/add` stays
  fast — under load it measured 2-6s/doc (OPS-1153, Nov 8), which cannot
  drain even one host's 500-doc cap.
- **The fix already existed unmerged**: commit `0ffe452274` on
  `dispatch/20261125-103752-...`-era branch
  `dispatch/20261108-134744-timer-log-shipper-on-idc03-fai` (OPS-1153)
  adds `/v1/ingest` batching (100/batch, ~0.09s/doc), per-batch cursor
  checkpoint, SIGTERM handling, per-doc `/add` fallback on 404. It sat
  unmerged for 17 days; idc03's shipper still records `result=timeout`
  runs as of 11-24.
- Drift found: fleet-deployed `~/.local/share/log-shipper/log-shipper.py`
  (tony-omen AND idc03 verified) matches **stash@{0}** "OPS-1330
  pre-convergence idc02" — repo + exit-code-on-add-failure, NO batching.
  A third variant living only in a stash.

## What changed (this branch)

1. `e1914574f6` — cherry-pick of `0ffe452274`: `scripts/ada/log-shipper.py`
   now bulk-posts via `/v1/ingest` with per-batch cursor checkpoints.
   Applied clean (file unchanged on master since Nov 8).
2. `d5a1aae675` — `scripts/ada/export-transcripts.py`: catch
   `subprocess.TimeoutExpired` on the shipper call → warn + continue.
   The shipper is a fallback lane; per-host timers are primary, so a slow
   run degrades instead of failing the unit.
3. `99c6a58878` — job doc:
   `docs/ssot/jobs/infrastructure/2026-11-25-ada-review-refresh-log-shipper-timeout.yml`

## Verification

- `/v1/ingest` live on both MDDB endpoints (11026 ops + 11023 leader):
  `POST {documents:[]}` → 200.
- `py_compile` both files; `export-transcripts.py --help` OK.
- **Real run** of the new code on idc02:
  `log-shipper.py --self --max-docs 2000` → 135 docs shipped in **2.4s**
  (vs ~30-60s on the per-doc lane); `ship/idc02` state doc confirms
  `shipped:135 failed:0` at 2026-11-25T03:47:54Z.
- Not deployed (per dispatch rules): after merge, tony-omen's exec
  checkout picks up the repo copy via hourly `chaba-repo-sync`;
  `~/.local/share/log-shipper/` bundles need `install-log-shipper.sh`
  per host — flagged on the card for approval.

## How to verify after merge/deploy

- Next 08:45 timer run on tony-omen: `journalctl --user -u
  ada-review-refresh.service` should show the shipper finishing in
  seconds-to-~1min and the unit `status=0/SUCCESS`.
- `ship/<host>` docs in `host-logs-state` keep updating; a slow MDDB day
  now loses ≤1 batch (100 docs) of cursor progress, not the whole leg.

lessons:
- tony-omen's user journal only keeps the current boot — timer-alert
  forensics older than ~1-2 days are gone; use ship-state docs + CMS
  timer-timeline instead.
- Check `git log --all` / branch containment before re-implementing —
  the exact fix for this failure class sat unmerged on a Nov-8 dispatch
  branch for 17 days.
- Deployed `~/.local/share/log-shipper/` copies can match a git STASH,
  not master or any branch — md5-compare deployed vs repo before
  assuming which code is live.
- `subprocess.run(timeout=)` SIGKILLs — in-script SIGTERM handlers only
  help systemd kills; per-batch cursor checkpoints are what survive a
  hard kill.
