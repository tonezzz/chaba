# Dispatch outcome — kk-mac-continuous-llm-worker

## Result

Implemented and soak-verified the dedicated KK-Mac LLM lane worker.
Committed on `dispatch/20261114-131026-build-a-dedicated-kk-mac-llm-n`
as `c1bf7a9a65` (14 files, +1292/−36). No push, no deploy.

## What changed

- **`scripts/devnest/kk_mac_lane_worker.py`** (new) — dedicated consumer
  for `gdrive:ada-nest/kk-llm` only. Per pass: drain/env gate →
  `local_snapshot()` on-host or heartbeat snapshot off-host → plan
  (skip terminal/live-claim/fresh-fallback, release stale claims and
  stale fallback holds) → pre-claim task_class+prompt validation →
  first-writer claim → `kk_mac_executor.run_contract` →
  `done`/`fallback`/`failed` marker + claim release. Never runs pack
  `run:`/`run_sh`; per-pack errors contained.
- **`kk_mac_admission.py`** — `local_snapshot()` on-host ground truth
  (ollama /api/version, sysctl load, statvfs, smctemp, tmux busy,
  load/CPU normalize); fixed tailnet-IP alias selection to pick the
  freshest doc (stale `"192"` alias was shadowing fresh heartbeats).
- **`kk_mac_llm.py`** — `host=local` → direct urllib to
  `127.0.0.1:11434` (no ssh); `think:false` default; `format` option.
- **`kk_mac_memory.py`** — local host sampling via `memory_pressure`/
  `vm_stat`; Linux `/proc/meminfo` path; **fixed** `MemoryMonitor._stop`
  shadowing `Thread._stop()` (broke `join()` on every real run).
- **`kk_mac_executor.py`** — threads `format`/`think`/`host`;
  `monitor.stop()` best-effort.
- **`kk_mac_metrics.py`** — `fallback` status, `interventions` count,
  `verdict:pass` counted as verified, nested `usage` handled,
  `staged_to_done_seconds` latency.
- **`scripts/ops/net.adanest.kk-llm-worker.plist`** (new) — launchd
  template for the lane worker (60s interval, `--host local`,
  `--max-packs 1`); install/rollback documented in
  `docs/kb/jevnest-kk-mac-capacity-procedure.md`.
- **`docs/ssot/jobs/devnest/2026-11-14-kk-mac-lane-worker.yml`** —
  durable job record. `ssot.audit.hosts.yml` kk-mac block declares the
  worker unit.
- Tests: new `test_kk_mac_lane_worker.py` (18 cases) + regression cases
  in admission/memory/metrics suites.

## Soak evidence (`gdrive:ada-nest/kk-llm-soak-20261114`, on kk-mac)

11 packs: **7 done-verified, 3 fallback-held** (`invalid_output` facts
by design + one real owner-busy `load_high`), **1 never claimed**
(`task_class=video_render`), **0 failed**. Wall mean ~1.0s, p95 ~1.3s,
390 eval tokens. Zero interference with the live `kk-llm` lane;
orphaned-claim recovery proven mid-run.

## Verification

- `python3 -m pytest tests/devnest tests/ops -q` → 354 passed.
- Full suite → 1487 passed, 47 skipped (1 external ada-voice-checkout
  test deselected, unrelated).
- Plist `plutil` valid; SSOT yaml valid.

## Pending (Tony's call, not done)

1. **launchd cutover** on kk-mac (plist swap + chaba-checkout sync) —
   member-host deploy, needs approval.
2. **JEV promotion** — weekly-review gate; unchanged, not enabled.
3. `/tmp` on tony-omen is tmpfs with `usrquota` — tony is over quota
   (~6.1G stale `pytest-of-tony` + 5.5G `upsc-eval` venv). Hook pytest
   failed until `TMPDIR` redirected; worth cleaning separately.

## How to verify

```
cd <worktree>
python3 -m pytest tests/devnest tests/ops -q
rclone lsf gdrive:ada-nest/kk-llm-soak-20261114/packs/ --dirs-only
python3 scripts/devnest/kk_mac_metrics.py --remote gdrive:ada-nest/kk-llm-soak-20261114
```

## One-paragraph summary

Built and committed the dedicated `kk_mac_lane_worker` for the
`gdrive:ada-nest/kk-llm` queue — a bounded, owner-first gated consumer
that validates packs before claiming, runs the `kk_mac_executor`
contract against local Ollama, persists result/usage/admission/verdict,
writes done/fallback/failed markers, and recovers stale claims; fixed
three real bugs the soak surfaced (memory-monitor `Thread._stop`
shadowing, heartbeat-alias shadowing, per-pack crash propagation) plus
a launchd PATH gap; verified by an 11-pack supervised soak on kk-mac
(7 verified, 3 fallback-held, 1 unadmitted pack never claimed, no
lane interference), 263 devnest tests and the full 1487-test suite
green, with launchd cutover and JEV promotion left as explicit-approval
gates documented in the procedure and job record.
