# Dispatch outcome — devnest-capacity-aware-dispatch (OPS-1002), re-run

**Session:** dispatch-wt-20261109-141530-implement-a-shared-devnest-cap (tony-omen)
**Result:** implemented — carried forward and verified. The prior dispatch
(135506, same card) had already implemented the shared capacity loop on its
own branch (`7f4e4a37d4`, pushed to `origin/dispatch/20261109-135506-...`
but NOT yet in master). This session merged that branch into
`dispatch/20261109-141530-implement-a-shared-devnest-cap`
(merge `b86f2d59f5`, clean — 17 files, +1474/−111) and re-verified the
full deliverable in this worktree. No push, no deploy.

## What this session did

1. Found the prior session's work on `dispatch/20261109-135506-...` —
   feature commit, outcome doc, and two small auto-checkpoint commits;
   nothing else diverged from the merge-base.
2. Merged it into this branch so the work is landable from whichever
   dispatch branch the close-out picks (commit was in origin only under
   the prior branch — confirmed `NOT in origin/master`).
3. Re-verified in this worktree (host under heavy load, ~20 load avg):
   - `tests/devnest` 125 tests OK (skipped=1)
   - `tests/ada` 125 tests OK (skipped=1)
   - `tests/colab` 70 tests OK (skipped=1)
   - focused: producer/broker/worker-ready/gdrive-roots 32 tests OK
   - `py_compile` clean on all 7 touched scripts; both edited SSOT YAMLs parse
   - one transient failure (`test_warmup_cap_when_prep_hangs`, a timing
     bound on JOBS.py warmup — untouched code) under parallel-suite load;
     passed in isolation and on full-suite rerun. Load flake, not a
     regression.
4. Audited the implementation against the card spec — all clauses covered;
   documented open gaps are upstream feeds beyond durable reports and a
   weekly ledger rollup (per-pack metrics already exist in
   `kk_mac_metrics.py`).

## What the merged change implements (from `7f4e4a37d4`)

- **Sealed staging (atomic-3-3, Tony-approved 2026-11-02):**
  `scripts/ada/nest_pack_ready.py` manifest-hash `ready` marker
  (copy → `rclone check --one-way` → seal last);
  `kk_mac_capacity_producer.py` filename-derived task_id skip fixes the
  Oct-31 4m timeout, retries unsealed unclaimed dirs, hard-clamps
  depth/new to 3/3, staging debris no longer counts as queue depth;
  `nest-worker.py --ready-policy auto` requires a valid seal on
  `*kk-llm`, validates-when-present elsewhere; `nest-pack-submit.py`
  and Colab `queue-runner.py` (canonical) apply the same contract.
- **Shared broker v2 (`devnest_capacity_broker.py`):** `normalize_spec`
  enforces task_id=filename-stem/task_class/evidence/lane/model/expect/
  artifact/timeout/fallback; `route_kk` writes the normalized spec;
  `route_colab` validates pack_source against the submit contract and
  seals; `colab_state()` observes queue heartbeat, fresh runtimes
  (duplicate-runner signal), pending packs, JOBS.py drift;
  `record_cycle()` appends per-cycle ledger records to
  `gdrive:ada-nest/devnest/capacity/`.
- **Feeds:** `devnest_report_feed.py` emits the normalized envelope
  (read-only reports lane, per the "start with" scope).
- **Docs:** procedure KB updated, `jevnest-kk-mac-capacity-procedure.md`
  sealed-staging step, `ssot.jobs.yml` notes, job record
  `docs/ssot/jobs/devnest/2026-11-09-shared-capacity-loop.yml`.

## Guarantees kept

No synthetic production filler (only explicit inbox specs route), no
duplicate Colab runners (broker never launches — duplicates are observed,
not acted on), no owner/quota gate bypass (KK admission +
`DEVNEST_KK_MAC_ENABLED` authoritative), concurrency 1, 3/3 watermark.

## How to verify

```
python3 -m unittest tests.devnest.test_kk_mac_capacity_producer \
    tests.devnest.test_devnest_capacity_broker \
    tests.ada.test_nest_worker_ready tests.devnest.test_gdrive_roots
python3 -m unittest discover -s tests/devnest -t .   # 125 OK
python3 -m unittest discover -s tests/colab -t .     # 70 OK (~50s)
```

## Deployment notes (unchanged — dispatch worktree, no deploy)

- tony-dell exec units pick this up via chaba-repo-sync + merge; unit
  args already `--max-depth 3 --max-new 3 --budget-s 90`.
- KK-Mac LaunchAgent `net.adanest.kk-llm-worker` must sync BOTH
  `nest-worker.py` and `nest_pack_ready.py` together; a missing helper
  fails closed on `required` policy.
- Drive `queue/runner.py` + `JOBS.py` update via the normal rclone deploy.
- Existing unsealed live pack dirs on kk-llm are healed by producer
  retry; unmarked legacy packs on ada-nest keep claiming (optional).

## Open gaps (documented in the job record)

- Upstream feeds beyond durable reports (audits, service deltas,
  held-out evals) still unimplemented — "start with read-only reports
  and finite Colab evaluations" scope held.
- Capacity ledger is raw per-cycle JSON; weekly JevTeam rollup
  (queue-wait/productive/verified/fallback/cost/GPU/owner-impact) not
  aggregated yet.
