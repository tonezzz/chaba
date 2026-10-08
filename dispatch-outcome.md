# nest-lane-tony-dell — dispatch outcome

**Result: tony-dell is now a live Nest serve+bench lane (onnxruntime CPU).
Phase-0 baseline: p50 ~11ms / p95 ~21ms for jev-student-v5 (200 calls,
0 errors) — far under the ~50ms bar, so the iGPU lane was registered as
`status: parked` rather than built out. Accuracy on the confirm-gate
suite is identical to the prod champ (49/66: golden 10/10, hard 27/35,
adv-confirm 12/21).**

## What happened

- **Phase 0 (baseline):** the champion's fp32 ONNX export already existed
  on dell (`stacks/web/public/apps/jev-bench/models/v5` — same weights as
  idc03's prod ckpt), so no re-export was needed. Provisioned
  `~/nest-lane/{venv,models,bin}` on dell (onnxruntime 1.30.0 +
  tokenizers, py3.14 — no torch). Published
  `bench/lane-20261008-100402` to ada-ha-scenario-reports with the real
  numbers.
- **Phase 1 (registry):** `tony-dell-cpu` + `tony-dell-igpu` (parked)
  added to `lanes:` in ada-pi `tests/bench/topologies.yml`, with
  host/ssh/tailnet/serve_port/python/models_dir fields the loop consumes;
  same pair added to `training_lanes` posture in
  `docs/ssot/infrastructure/ssot.nest-training.yml`.
- **Phase 2 (serve shim):** new `ada-pi/scripts/serve-jev-student-onnx.py`
  — stdlib http.server + onnxruntime twin of serve-jev-student.py
  (/health + /v1/systemone, `--provider cpu|openvino:GPU`).
  `nest-train-loop.py` gained `--lane`, `serve_onnx_lane()` (local
  subprocess, or rsync+ssh spawn bound to the lane's tailnet IP when
  remote), `export_onnx()` for torch ckpts, a `lane-probe.py` latency
  probe, and `lane-bench`/`lanes` commands. GTX1650 torch path untouched.
- **Phase 3 (bench + CMS):** lane docs carry `lane:`/`host:`/`runtime:`/
  `p50_ms`/`p95_ms` meta + a latency table + a parseable json fence;
  train docs gain `lane` meta + probe latency block when `--lane` is
  used. `bench-edge-cms.py` now also consumes `bench/lane-*` docs and
  renders a "Nest serve lanes" comparison table — republished the
  `bench-edge` CMS page (1 lane row live).

## Verified

- `nest-train-loop.py lane-bench --lane tony-dell-cpu --model
  ~/nest-lane/models/jev-student-v5` ran end-to-end **on dell** →
  published `bench/lane-20261008-100402`.
- The same command ran end-to-end **from mn01** (remote path:
  rsync + ssh + tailnet bind, bench over tailnet, `--no-publish`) —
  49/66 acc, p50 14.8ms remote. Server teardown verified clean.
- `node scripts/ssot-validate-all.mjs` — 1685 files, 0 errors.

## To merge / follow up

- ada-pi: branch `dispatch/nest-lane-tony-dell` in worktree
  `~/CascadeProjects/ada-pi-wt-nest-lane` **on tony-dell** — merge to
  main + push per normal ada-pi flow. Until merged, run the loop on dell
  with `ADA_PI=~/CascadeProjects/ada-pi-wt-nest-lane`.
- chaba: this dispatch branch; mirror commit on dell worktree
  `~/CascadeProjects/chaba-tony-dell-worktrees/nest-lane` (branch
  `dispatch/nest-lane-tony-dell`).
- iGPU stays parked: revisit only for gemma-270m (llama.cpp-server
  Vulkan) or if dell CPU p50 regresses past ~50ms.
- Full `loop --lane` (train → serve on lane) shares the same code path
  but wasn't run — it needs a trained ckpt + VENV_PY for export.
- Trail doc: `docs/ssot/jobs/infrastructure/2026-10-08-nest-lane-tony-dell.yml`.
