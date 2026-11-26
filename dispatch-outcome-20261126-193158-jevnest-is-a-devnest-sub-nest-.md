# Dispatch outcome — jevnest-kk-mac-capacity-loop

**Card:** `jevnest-kk-mac-capacity-loop` (doing → dispatch on idc02)
**Branch:** `dispatch/20261126-193158-jevnest-is-a-devnest-sub-nest-`
**Commit:** `a397a89528`

## What I found

The capacity-aware producer for `gdrive:ada-nest/kk-llm` already exists
and is live (`kk_mac_capacity_producer.py` + `devnest_capacity_broker.py`
+ `devnest_report_feed.py` + `kk_mac_plan_validator.py` upstream,
`kk_mac_lane_worker.py` consumer). I audited it against the card spec
and verified live state from idc02:

- **Admission gate live-verified:** heartbeat 185s fresh, `ollama_ok`,
  load 2.32 vs per-core limit 14.0, disk 58G, temp 42C, node not busy
  → `eligible: true`.
- **Producer dry-run:** `queue_before=6` → correctly skipped
  `queue_at_capacity` (packs already above watermark).
- **Metrics live:** 171 packs — 155 done / 10 failed / 3 fallback-held
  / 3 live; queue wait p50 353s. 7d window: 8 packs, 0 done / 4 failed
  / 3 fallback — recent week was mostly holds+failures (kk-mac offline
  stretches + verifier rejects), real signal for the weekly review.

### Spec-vs-reality deltas (all deliberate later decisions, docs were stale)

- `load_1m<=4` → per-core gate (1.0/core, deployed 2026-11-25 after the
  absolute 4.0 starved the 14-core lane at 0.29/core).
- `queue depth<3 / ≤3 per cycle` → deployed `--max-depth 5 --max-new 5`
  since 2026-11-13 (inflow ~8/hr vs throughput ~20/hr).
- `operator_brief`/`safe_route` in spec → HELD unadmitted per
  `kk-mac-admitted-classes-narrow` (done 2026-11-23; 2026-11-19 eval
  scored them 0.31–0.60). Only `summary` + `structured_extract` admit.

### The real gap I closed

`kk_mac_metrics.py` existed but **nothing published it** — no schedule,
no report node — so "Publish L0-L3 evidence and feed weekly JevTeam
review" had no machine feed.

## What changed (commit `a397a89528`, 9 files)

- `scripts/devnest/kk_mac_metrics.py` — `collect()` gains `window_s`/`now`
  producing a `window` block (counts, queue wait, latency, wall, tokens)
  scoped to packs active in the last N days; result.json cats are scoped
  to the window so pack-history depth can't blow the budget. New
  `publish()` writes `reports/kk-llm/kk-llm-metrics.json` +
  `meta.kk-llm.yml` via `lib.report.write_meta`; status=`delta` only on
  window `failed>0` (fallback is retryable, failed needs a human). CLI:
  `--window-days`, `--publish`, `--out-dir`. No-window output unchanged.
- `docs/ssot/infrastructure/ssot.reports.yml` — new L1 node
  `nest-lanes/kk-llm`, added to `chaba-nest` L2 children → flows to
  SYSTEM-REPORT L3.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new job
  `jevnest-kk-llm-metrics` on tony_dell, 15m, timeout 5m:
  `kk_mac_metrics.py --tokens --publish --window-days 7 --budget-s 240`.
  Units rendered to `systemd/generated/tony_dell/` (committed).
- `docs/kb/jevnest-kk-mac-capacity-procedure.md` +
  `docs/kb/devnest-capacity-aware-dispatch-procedure.md` — drift fixes
  (per-core load ceiling, 5/5 watermark, broker-exists current state).
- `tests/devnest/test_kk_mac_metrics.py` — +4 cases (window scoping,
  cat-path bounds, live-pack exclusion, publish writes, delta status).
- `docs/ssot/jobs/devnest/2026-11-26-jevnest-kk-mac-capacity-evidence.yml`
  — full audit + change record.

## Verification

- `pytest tests/devnest/test_kk_mac_metrics.py` — 9 passed.
- `pytest tests/devnest/` — 421 passed; 3 failures
  (`test_quota_exceeded`, `test_s1_requires_opencode_lanes_env`,
  `test_profile_envelopes_parse_and_lint`) confirmed **pre-existing on
  the clean tree** (verified via stash) — unrelated lane_gate /
  opencode-profile drift.
- Live `--publish` run wrote the L1 pair correctly (status=delta,
  summary "155 done / 10 failed / 3 fallback-held / 3 live; window
  interventions 7").
- `render-jobs.py --host tony_dell --check` — OK, 134 jobs.
- `ssot-validate-refs.py` — 4 pre-existing errors in untouched files.
- Registry resolves: `generator_argv` → runnable argv, node in
  chaba-nest children.

## Not done (deploy gates, by design)

- `render-jobs.py --host tony_dell --install` — unit install is a deploy
  step; the dispatch rails say no deploy. The job is declared + rendered;
  it activates on the next normal install pass.
- First scheduled tick + meta pull into con01's daily SYSTEM-REPORT is
  the remaining proof — job doc `pending_gates` records it.

## How to verify

1. `python3 scripts/devnest/kk_mac_metrics.py --tokens --publish
   --window-days 7` on any host with rclone+gdrive → inspect
   `reports/kk-llm/meta.kk-llm.yml`.
2. After install: `systemctl --user list-timers | grep kk-llm-metrics`
   on tony-dell; next daily SYSTEM-REPORT shows `nest-lanes/kk-llm`.
3. Audit detail: `docs/ssot/jobs/devnest/2026-11-26-jevnest-kk-mac-capacity-evidence.yml`.

lessons:
- kk_mac_metrics --tokens cats EVERY finished pack's result.json — at
  171+ packs it blows a 120s budget (150 skipped). Scope cats to a time
  window before scheduling it.
- The card spec text is stale vs deployed reality in three places
  (per-core load gate, 5/5 watermark, held classes) — later owner
  decisions superseded it; check git log on ssot.jobs.yml before
  "fixing" apparent spec violations.
- reports/* is gitignored — producer metas only reach the L3 render via
  pull-report-metas.sh on con01; a new L1 node needs its generator to
  write meta via lib.report.write_meta on a producer host in the pull
  list (tony-dell qualifies).
