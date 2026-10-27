# dispatch-outcome — deliver-a-canonical-colab-note (card colab-single-notebook-job-console-with-c-2528c5, OPS-0874)

## What was found

The card's Phase 1 was already built once on `fix/colab-session-control`
(commits `3f4dcabbb`, `660ebf546`, `20c89df3a`) but those commits live only
on an idc03 checkout — they were never pushed and do not exist in this
repo. This session re-implemented the work from the card spec, the card
comms, and the already-deployed Drive conventions (lesson 2231 documents
`queue/runtime-sessions/`, `ada-nest-job-console.ipynb`,
`t4-session-warmup` — naming was matched deliberately).

## What changed (commit aa349421 on dispatch/20261026-014845-deliver-a-canonical-colab-note)

- `scripts/colab/ada-nest-job-console.ipynb` — canonical notebook:
  instruction markdown + exactly two code cells, generated from the cell
  sources by new `scripts/colab/build-job-console.py` (a `--check` mode
  keeps the notebook from drifting).
- `scripts/colab/preflight-cell.py` (cell 1) — mounts Drive, prints
  boot_id/GPU/RAM, registers `queue/runtime-sessions/<boot_id>.json` on a
  60 s heartbeat thread, refuses (with the peer's identity) while another
  managed runtime's record is fresh (TTL 300 s). `ALLOW_SECOND_RUNTIME`
  is the only override.
- `scripts/colab/runtime_registry.py` — shared identity/registry/launch
  gate module (stdlib only).
- `scripts/colab/queue-launcher-cell.py` (cell 2) — full gate before
  spawn: Drive mounted, runner.py present, GPU detected (CPU refuses),
  no fresh managed peer. Runner liveness is boot-scoped: `queue/runner.id`
  `{pid,boot_id,worker,epoch,ts}` — a PID on shared Drive is never a
  process handle; foreign/stale records are never signaled; only a
  same-boot live PID + stale heartbeat is reaped. A fresh heartbeat owned
  by another boot refuses the launch.
- `scripts/colab/queue-runner.py` — `NEST_ROOT`/`NEST_QUEUE` env
  overrides, writes `runner.id` + legacy `runner.pid`, removes its marks
  on exit only while they still name it, refreshes the registry record
  on the heartbeat thread, injects `QUEUE_PENDING`/`BOOT_ID`/
  `QUEUE_STATE` into job run namespaces, `{boot_id}` expansion in
  artifact globs, `NEST_QUEUE_SETTLE_S` for the flush settle.
- `scripts/colab/JOBS.py` — canonical manifest; `t4-session-warmup`
  (scope `env`) is first: small GPU matmul smoke that runs ≥30 s and
  until the next job's background prep exits (300 s cap) so the
  ~4 min `restore-hf-cache` extract overlaps useful GPU work; writes
  `queue/warmup/<boot_id>.json` as its verify-before-mark artifact.
- `mcp-servers/mcp-colab/server.py` — new `colab_session_status` tool
  (registry + heartbeat/lease/runner.id over rclone); `colab_pack_status`
  now requires `pack.yml` for a dir to count as a pack and a non-empty
  `claim/` for CLAIMED (fixes the false-claimed/queued report Tony
  flagged on the mcp-colab card).
- `docs/kb/colab-mcp-jobs.md` — new "Job-console notebook" section +
  updated detached-mode/warmup bullets and the startup-snapshot
  constraint.
- Education lesson `colab-gpu-worker` (post 2231) updated in place via
  board-api `/lesson` — appended the landed-code section (canonical
  paths, `colab_session_status`, test coverage).
- `docs/ssot/jobs/nest/2026-10-26-colab-job-console.yml` — job record.
- Tests: `tests/colab/test_runtime_registry.py` (5) +
  `tests/colab/test_job_console.py` (16).

## Result

- `python3 -m unittest discover -s tests/colab` → **30 tests, all pass**
  on mn01 (21 new + 9 existing gap-runner).
- Card test list covered: CPU/no-Drive preflight refuses; fresh T4
  passes; duplicate managed T4 blocks naming the peer boot_id; foreign
  runner.id PID never signaled (PID-collision) while a same-VM zombie is
  reaped, and a foreign runner.id planted mid-run survives our runner's
  exit; warmup runs while the cache-restore prep is pending (min floor +
  max cap); end-to-end drain runs env jobs then packs in one VM.
- No push, no Drive deploy per dispatch rules.

## How to verify / next step

1. Merge-sweep lands the branch, then rclone-deploy
   `scripts/colab/{runtime_registry,preflight-cell,queue-launcher-cell}.py`,
   `JOBS.py`, `ada-nest-job-console.ipynb` → `gdrive:ada-nest/queue/`
   (the Drive tree currently runs the equivalent prior-session build;
   diff on sync, keep the repo copy canonical).
2. On a fresh T4: open the console notebook, run cell 1 then cell 2 —
   expect `PREFLIGHT-OK`, `queue pid … -> run-*.out.log`, and the warmup
   overlapping the cache restore; `queue/warmup/<boot>.json` lands.
3. Fleet-side: `colab_session_status` shows the managed runtime, lease,
   heartbeat and runner.id.
