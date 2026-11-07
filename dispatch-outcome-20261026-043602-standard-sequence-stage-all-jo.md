# dispatch-outcome — standard-sequence-stage-all-jo (card devnest-colab-assessment-first-cache-pre-cb223c, OPS-0880)

## What was found

- Drive `queue/JOBS.py` was stale rev-9/10 (inline GPU jobs) vs the canonical lean manifest; `runner.py` predated `runner.id`/`QUEUE_PENDING`; `runtime_registry.py` was absent (both console cells import it); the job-console ipynb was the old thin-cell build. Queue heartbeat was `exit` ~6h stale — no live runner, safe to stage.
- Packs: repo→Drive `rclone check` showed only 2 differing pack.ymls — and Drive held the NEWER live patches (doc-vo-ss1 v6 beats; nasa-embeds-ss1 `fetch`/`keep_workdir`/timeout fields). Repo would have clobbered them; they were back-ported instead. `doc-vo-v3` is the only undone pack = the next T4 package.

## What changed (commit 5a238e1a on dispatch/20261026-043602-standard-sequence-stage-all-jo)

- `scripts/colab/JOBS.py` — new env-scope job `devnest-heldout-assessment` between `assets-stage` and `save-hf-cache`: fixed fp16/bf16 TFLOPs + 256MiB H2D/D2H battery and a production-log prep-overlap audit (`bg_preps_in_run_window`, `hidden_prep_upper_s`, artifact/prep/fence counters). Zero downloads — cache-independent by construction; its GPU run hides the multi-minute cache repack (the second un-hideable window after the warmup's). Artifacts gate: `queue/assessments/devnest-heldout-<boot_id>.{json,md}`. Explicitly NOT a replay-benchmark pass (fixtures/verifiers unfrozen).
- Back-ported the two newer Drive pack.ymls into repo canonical; `scripts/ada/nest-worker.py` rc timeout 300s→900s (matches hardened Drive copy, now identical).
- `docs/kb/colab-mcp-jobs.md` — new "Standard launch sequence" subsection: stage JOBS+packs before launch (snapshot constraint + `__pycache__` purge), one cache-independent held-out assessment immediately before the next model/cache prep, serial runs + next-prep overlap only, durable-artifact gates + settle window.
- Education lesson `colab-gpu-worker` (post 2231) appended in place via board-api /lesson.
- Job record `docs/ssot/jobs/nest/2026-10-26-devnest-heldout-assessment-staging.yml`.

## Deployed to Drive (all md5-verified)

`queue/`: JOBS.py, runner.py, runtime_registry.py (new), preflight-cell.py, queue-launcher-cell.py, ada-nest-job-console.ipynb, nest-worker.py, nest-efficiency.py. Purged `queue/__pycache__` (stale bytecode could shadow the new manifest). Packs: 0 diffs after back-port.

## Result

Next console launch executes: warmup (hides restore prep) → restore/deps/assets → **assessment** (hides repack prep) → save-hf-cache → doc-vo-v3 with per-pack artifact gates + 120s settle. Verified: JOBS.py compiles; `_HELDOUT_RUN` exec'd standalone (cpu-only degradation clean, audit counters correct); `tests/colab` 30/30 pass; all Drive files checksum-match; YAML/SSOT hooks green. No benchmark pass claimed; replay-fixture freeze stays on its own card.

## How to verify

1. `rclone cat gdrive:ada-nest/queue/JOBS.py | grep devnest-heldout` and `rclone check scripts/colab/packs gdrive:ada-nest/packs --one-way` → 0 diffs.
2. After the next T4 console launch: `rclone lsf gdrive:ada-nest/queue/assessments/` shows `devnest-heldout-<boot>.{json,md}`; `queue/log-*.txt` shows the repack prep backgrounded under the assessment run; `packs/doc-vo-v3/done` lands with verified artifacts.
