# Dispatch outcome — ada-review-refresh prune timeout (ADA-1485)

Card: `ada-review-refresh-prune-timeout-fix-unpinned`
Date: 2026-11-27 · Host: con01 (worktree) → deployed to tony-omen + idc03 exec checkouts

## What failed

`ada-review-refresh.service` on tony-omen died at 09:03 with
`subprocess.TimeoutExpired` — `export-transcripts.py`'s call to
`prune-old-docs.py` exceeded its 600s timeout (unit ran 18m52s wall,
51M swap). The prune leg was not merely slow — it could not finish *at
all*: ops `host-logs` grew to ~590k docs (~390k older than the 3d
policy) and the sweep's `/v1/search` offset pagination is O(matches)
per page server-side (~15-60s/page under load), so enumerating ~390k
expired docs takes hours; any single >60s request aborts the whole
collection ("list failed — timed out"). idc03's standalone 09:30
`prune-old-docs.timer` showed the same silent failure.

## Root cause

`prune-old-docs.py` paginated `POST /v1/search` (offset+sort+meta
filter). mddb materializes **all** matching docs per request before
slicing the page — quadratic across pages — compounded by ~590k docs,
2.7M meta-index entries, idc03 load ~16, and mddb-ops 23.6GB freelist
pressure making per-doc deletes slow while the backlog is large.

## Fix (worktree → deployed)

- `scripts/ada/prune-old-docs.py`
  - Prefer `POST /v1/documents:deleteWhere` (mddb ≥2.18.8, GO-045):
    server evaluates the meta filter once per call and deletes ≤1000
    docs/call with `nextCursor` continuation. Per-call timeout 110s
    (under mddb's 120s HTTP write timeout — a dropped response just
    means the server finishes the batch orphaned; deletes are
    idempotent per-doc so the next run re-matches the remainder).
  - `--budget-seconds N` (default 540, `0`=unlimited): monotonic
    deadline shared across all collections; hitting it prints
    "budget reached, resumes next run". Partial progress is always
    safe.
  - 404 → legacy `/v1/search` sweep fallback for mddb 2.15.x
    (leader :11023); per-host `no_where` memoization.
- `scripts/ada/export-transcripts.py`: `TimeoutExpired` on the prune
  subprocess → warn + continue (same degrade pattern as the
  log-shipper guard); the unit can no longer die on the prune leg.
- `systemd/ada-review-refresh.service`: `TimeoutStartSec` 1200 → 2400
  (~15 sequential steps; prune legitimately needs ~10min when
  retention has a backlog).
- idc03 `prune-old-docs.service` ExecStart += `--budget-seconds 0`
  (primary sweeper; no TimeoutStartSec — drains fully each day).

Deployed via scp to `~/CascadeProjects/chaba` exec checkouts on
tony-omen (scripts + unit, `daemon-reload`) and idc03 (script + unit).
md5-verified identical to worktree.

## Verification — PASSED

- `py_compile` clean; `--dry-run --only host-logs` →
  `expired 389335, would delete 389335 (>3d on ts @…:11026,
  deleteWhere) in 12s` — server-side filter works.
- `systemctl --user start ada-review-refresh.service` on tony-omen at
  10:29 → **Result=success, ExecMainStatus=0**, finished 10:45:16 in
  **15m37s wall** (vs 18m52s FAILURE before). Prune leg completed well
  under the 600s subprocess cap — no TimeoutExpired warn in journal;
  leader sweep line shows the new path live:
  `host-logs: expired 0, deleted 0 (>14d on ts @…:11023, deleteWhere,
  1 calls) in 0s`. Corpus refreshed — `focus-digest.md` mtime 10:45.
- Side observation: `log-shipper` also exceeded its 600s guard
  ("skipped — per-host timers remain the primary lane") — ops-DB write
  slowness is broader than prune; its degrade path worked as designed.

## Backlog state

~390k expired host-logs docs on ops (:11026, count still ~592k and
growing ~35/min net of deletes). mddb-ops per-doc deletes are
pathologically slow while the 23.6GB freelist is poisoned — observed
drain ≈9 docs/min via orphaned timed-out calls; at that rate the
backlog cannot catch up unaided. A detached drain loop on idc03
(`prune-old-docs.py --only host-logs --budget-seconds 1800` in a
`while` loop, log `/tmp/prune-drain.log`) keeps firing
`deleteWhere` calls; the script now retries each cursor position up
to 4× (same-cursor retry is safe — orphaned batches surface as
notFound and nextCursor still advances). **Recommended follow-up:**
ops MDDB Procedure-B rebuild (export → fresh DB → swap) per the
mddb runbook — client-side deletes alone won't drain 390k docs in
reasonable time while per-commit cost stays seconds.

## Job trail

`docs/ssot/jobs/infrastructure/2026-11-27-ada-review-refresh-prune-timeout.yml`

lessons:
- mddb `/v1/search` materializes ALL matching docs per request — never
  paginate it over a large expired set; use `/v1/documents:deleteWhere`
  (≥2.18.8) for retention sweeps.
- mddb HTTP write timeout is 120s: client timeouts <120s orphan
  server-side work that still commits — budget call timeouts just
  under it (110s) and treat dropped responses as "batch may have
  landed" (idempotent retries).
- `deleteWhere`/`updateWhere`/`setTTLWhere` exist since mddb 2.18.8
  (GO-045); check `/v1` version before assuming a 404 fallback is dead
  code — here 2 of 3 endpoints are 2.18.10, leader is 2.15.3.
- A timed-out `deleteWhere` call keeps deleting server-side — a
  client-side "failed" does NOT mean zero progress; loop-and-retry
  drains still converge.
- bbolt freelist poisoning (23.6GB DB) makes every commit slow during
  mass deletes — retention backlogs on huge collections may need the
  export→fresh-DB→swap rebuild, not just faster deletes.
