# Ada Nest Gap-Job Procedure

Use the Colab GPU during CPU/disk preparation gaps without fighting the main
queue runner.

## Eligibility gate

A gap job may run only when all are true:

1. `queue/heartbeat` is fresh (age <= 60s).
2. Main phase is `prep` or `prep-wait` for a CPU/disk-only preparation.
3. `nvidia-smi` succeeds and free VRAM exceeds the job's declared minimum.
4. The job does not pull models, mutate HF/Ollama caches, write production
   indexes, or use the main queue lease.
5. The gap lease (`queue/gap-lease`) is free, stale (>180s), or already ours;
   only one gap runner runs at a time.
6. The job has a hard timeout and a non-empty declared artifact.
7. The pack is unclaimed and has no `done`/`failed` marker.

Stop/skip when the main phase becomes `run`, `flush-settle`, `done`, or when
heartbeat age exceeds 60s. A running gap pack is SIGTERM-killed (process
group, SIGKILL after 5s grace) the moment the window closes — its claim is
released so a later gap retries it.

## Pack contract — `gap-packs/<name>/pack.json`

```json
{"name": "my-gap-job",
 "run": "python3 - <<'PY'\n...\nPY",
 "timeout_s": 120,
 "min_free_gpu_gb": 1,
 "artifacts": ["gap-packs/my-gap-job/out/*.json"],
 "disabled": false}
```

- `run` execs via `bash -lc` with `GAP_PACK`, `GAP_OUT`, `NEST_ROOT` in env,
  cwd `/tmp`, own process group. stdout/stderr land in `out/gap.log`.
- `artifacts` are globs vs `ada-nest/` root — every pattern must match at
  least one non-empty file before `done` is written (verify-before-mark).
- A pack that exits nonzero or fails the artifact gate gets a `failed`
  marker and is skipped until an operator deletes it. Aborts/timeouts
  (window events, not pack faults) release the claim for a natural retry.
- `pack.yml` is also accepted if PyYAML is importable; `pack.json` wins when
  both exist.

## Good gap jobs

- GPU telemetry and a short CUDA smoke test.
- Embedding throughput on a small fixed corpus using an already-loaded
  model (check residency first — see embedding-smoke's no-pull guard).
- Voice/TTS latency on an already-loaded model and fixed five-sentence corpus.
- Image preprocessing or benchmark scoring that does not download weights.

## Forbidden gap jobs

- Model pulls or HF/Drive cache restore/save.
- Anything that changes the main pack's cache, index, or artifacts.
- Long-running agent loops.
- Jobs needing more VRAM than the main pack's declared free budget.
- A second `runner.py` or a second main queue lease.

The runner additionally refuses packs whose `run`/`prep` text matches a
forbidden pattern (`ollama pull`, `snapshot_download`, `pip install`,
`ada-nest/cache`, `runner.py`, ...). That scan is a seatbelt — the policy
above is the contract.

## Operational sequence

1. Start the normal queue runner once (`queue-launcher-cell.py`).
2. Start the gap runner once from the same runtime
   (`gap-launcher-cell.py`) — a detached loop re-invokes
   `queue/gap-runner.py` every ~20s; each invocation does one scan pass.
3. It re-checks the window + gap lease before and during every job.
4. It writes only to `gap-packs/<name>/out/`, plus `queue/gap-lease` and
   `queue/gap-heartbeat`.
5. Inspect artifacts after the main queue reaches a stable phase:
   `rclone cat gdrive:ada-nest/queue/gap-runner.log`,
   `queue/gap-heartbeat`, `gap-packs/<name>/{done,failed,out/}`.
6. Leave the runtime keep-alive running; no browser interaction is needed.

The gap runner is opportunistic: a missed gap is safe. It must never delay,
kill, or alter the main queue.
