# dispatch-outcome: nest-report-integration

Card: `nest-report-integration` — wire the Nest into the layered
reporting standard (L0–L3). Runner: mn01. Status: **done**.

## What changed

- `docs/ssot/infrastructure/ssot.reports.yml` — new **Nest domain**:
  `chaba-nest` (L2-domain, generator `scripts/ada/nest-overview.py
  --force via chaba-kanban-brief.service (30 min)`, cadence 1h) with 11
  L1 children: `nest-lanes/{jev-student,student-a,student-b,heavy-a,
  heavy-b,ollama}`, `nest-brains/{nest-01-ops-classifier,jev-student,
  orch-bench-corpus,nest-edge-vision-models}` and `nest-bench/orch`.
  Child metas are written by the parent generator, so the L1
  `generator:` strings are `manual — …` (run-node.py exits "not
  runnable" instead of exec'ing a leaf only the parent produces).
  `chaba-nest` added to `system-report` children; `current_state`,
  `related_files`, and a `next_steps` entry (vendor lane_metrics into
  open-jev) updated.
- `scripts/jev/lane_metrics.py` (new) — stdlib-only monotonic counters
  for `/v1/systemone` lane servers: `requests_total`,
  `questions_total`, `escalations_total` (questions answered with a
  stub/fallback the caller must route heavier), cumulative
  `latency_seconds` buckets, `cpu_seconds` (`process_time`),
  `uptime_s`. `attach(app)` registers `GET /metrics` on a FastAPI app.
- `scripts/jev/serve-seqcls.py`, `scripts/jev/serve-gemma-head.py` —
  `lane_metrics.attach(app)` + one `observe()` call per request.
  Counters only; no behavior change.
- `scripts/ada/nest-overview.py` — probes `/metrics` alongside
  `/health` (3s timeout, graceful "no metrics" fallback); renders
  `decisions Δ` + `esc %` columns in the Lanes table (Δ computed
  against the previous `reports/nest/nest-overview.yml` artifact; ↻ =
  counter reset/first probe); renders the **Portable brains** table
  (entity/tier/status/bench from `ssot.nest-brains.yml`); MDDB bench
  fetch now tolerates outages. Writes `reports/nest/nest-overview.yml`
  (rolling artifact) + `meta.<child>.yml` for all 11 children +
  `meta.chaba-nest.yml` via `lib/report.py::write_meta` (with
  `inputs_at`), then `append_timeline`. Local outputs are written
  **before** the CMS publish so an MDDB outage can't leave the node
  stale.
- `docs/ssot/jobs/infrastructure/2026-10-08-nest-report-integration.yml`
  — job trail (decisions + limits).

## Results / verification

- `report-system.py --print` renders the `### chaba-nest` domain with
  all 11 children resolved from generated metas (live data from this
  worktree run: 4/6 lanes up — the tony-omen lanes are leashed down —
  brains 1 packed-verified / 2 candidate / 1 planned, bench
  `orch-20261007-112115`).
- All 12 `reports/nest/meta.*.yml` validate against `meta_schema`
  fields + `status_enum`.
- `nest-overview.py --dry-run` prints the page block with the new
  Lanes activity columns and Portable brains table.
- `ssot-validate-all.mjs`: 1683 files, 0 errors.
- `generator_argv`: `chaba-nest` → runnable argv; leaf nodes → None.

## Known limits

- The 4 gemma lanes run `openjev` from `~/CascadeProjects/open-jev`
  (separate repo, outside this worktree — not touched). They'll render
  "no metrics" until `lane_metrics.py` is vendored there; the jev
  confirm-gate on idc03 needs its service restart/deploy of the updated
  `serve-seqcls.py`. Same for any live gemma-head lane.
- `reports/` is gitignored — node metas/artifacts are host-local
  observed state, written next live run on tony-dell.
- No commit/push performed (dispatch mode).
