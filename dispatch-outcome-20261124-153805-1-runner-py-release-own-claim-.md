# dispatch-outcome — ada-nest drive-store hardening (ADA-0806)

Card: `ada-nest-drive-store-hardening-stale-cla-558c90`
Worktree: `dispatch-wt-20261124-153805-1-runner-py-release-own-claim-`
Date: 2026-11-24. Repo landing only — no push, no Drive deploy (per card rails).

## What changed (all 5 spec items)

### 1. runner.py releases own claim on FAIL + fence-exit
`scripts/colab/queue-runner.py` — item 1 was partially landed by `8f2e01ffe1`
(release on PREP/artifact/exception FAIL). This change completes it:
- `fence_watch()` now calls `release_claim(state['claim'])` **before**
  `os._exit(1)` — `os._exit` bypasses `finally`, so the old code poisoned
  the pack for the whole stale-claim window.
- New `fail_pack(name, why)` pairs `touch_index(name,'fail',why)` +
  `release_claim(name)` on every FAIL path.
- Claim is also released on DONE (claim lifecycle completes; done marker
  is the durable record). `state['claim']` replaces the single `current`
  var so the `finally` release covers exactly the held claim.

### 2. packs-index on Drive — O(1) fleet scans
Design: **immutable event files**, not an append log — rclone has no Drive
append, and per-event files are atomic between Colab (FUSE) and fleet
(rclone) writers.
- `queue/packs-index/<ms>-<seq>-<worker>-<pack>-<state>.json`, states
  `stage|claim|done|fail|release`. Writers: queue-runner (`touch_index`),
  nest-worker (`index_event`, incl. stale-claim `release`),
  nest-pack-submit (`stage` on submit).
- `nest-queue-status.py`: `packs_index()` folds the whole dir in ONE
  `rclone copy`; `batch_done_markers()` fetches all `*/done` markers in
  one `--files-from` copy. Index is **advisory** — non-terminal packs
  still get live `lsf`/`cat`; terminal-state worker attribution comes
  from the index event. `index_retention()` prunes events >14d at
  runner startup.

### 3. hf-hub.tar.zst split per-repo
- `JOBS.py save-hf-cache`: writes `cache/hf-hub/models--<org>--<name>.tar.zst`
  per repo AND keeps the legacy `cache/hf-hub.tar.zst` monolith (one
  transition cycle). Artifacts gate now covers both globs.
- `JOBS.py restore-hf-cache`: honors `$NEST_HF_REPOS` — `'NONE'` skips
  the extract entirely; named repos extract their own per-repo tar, or
  their `hub/models--*` subtree out of the monolith in ONE tar pass
  (selective even before per-repo archives exist — important because
  Drive currently only has the monolith); unset (only pre-ADA-0806
  runners never set it) restores the whole monolith with per-repo tars
  as the monolith-less fallback.
- `queue-runner.py`: `hf_repos_needed()` computes the union of `hf_repos`
  over packs/jobs without a done marker, exports it to prep env as
  `NEST_HF_REPOS`. New optional pack.yml field `hf_repos:` (list of
  `org/name`, validated in `nest-pack-submit.py`).
- **Annotated 16 packs**: 9 LTX packs → `Lightricks/LTX-Video`; 5 f5-tts-th
  packs (doc-vo-ss1/v3, vyncx-v2-ada2-redo/ada9s/bench) →
  `VIZINTZOR/F5-TTS-TH-V2` + `charactr/vocos-mel-24khz`;
  thonburian-bench → `biodatlab/ThonburianTTS` + vocos;
  vyncx-v2-cer → `Systran/faster-whisper-small`. Embeds packs deliberately
  unannotated (their input is `model-archive/t5xxl`; LTX-Video is only a
  missing-archive fallback — annotating would pull 17GB needlessly).

### 4. Stage-then-push / flush-settle formalized
`queue-runner.py`: at done-mark time the runner records artifact glob byte
counts; after `NEST_QUEUE_SETTLE_S` it re-stats every pattern and logs
`flush-check <name>: sizes still moving …` when bytes grew during settle —
the 2026-10-23 lost-tar detector. Logged for fleet audit, never fails the
queue; `NEST_QUEUE_SETTLE_S=0` skips the sleep.

### 5. Unified heartbeat+lease liveness
`queue/lease` is now THE liveness file: `{worker,epoch,ts,job,phase}`
rewritten every 15s; the heartbeat thread only writes while the lease
still names this worker (a fenced writer can't resurrect its lease).
`queue/heartbeat` text is retired. Every reader is lease-first with
heartbeat fallback for pre-unification runners:
- `scripts/ops/nest-queue-watch.py` (stall alert `liveness()`)
- `scripts/ops/nest-queue-health.py` (snapshot; lease ts stays the clock,
  heartbeat still supplies job/phase for old-format leases)
- `scripts/ada/nest-queue-status.py`
- `scripts/colab/queue-launcher-cell.py` (`_liveness_ts`, reap/zombie gate)
- `scripts/colab/gap-runner.py` (eligibility heartbeat → lease-first)
- `mcp-servers/mcp-colab/server.py` (`colab_session_status` +
  `colab_queue_start` freshness gate — single liveness age check)
- gap-lease/gap-heartbeat deliberately NOT unified (separate space).

## Files changed
- `scripts/colab/queue-runner.py`, `JOBS.py`, `queue-launcher-cell.py`,
  `gap-runner.py`, `build-job-console.py`, `ada-nest-job-console.ipynb` (rebuilt)
- `scripts/ada/nest-worker.py`, `nest-pack-submit.py`, `nest-queue-status.py`
- `scripts/ops/nest-queue-watch.py`, `nest-queue-health.py`
- `mcp-servers/mcp-colab/server.py`
- 16 × `scripts/colab/packs/*/pack.yml` (`hf_repos:`)
- `docs/kb/colab-mcp-jobs.md`, new
  `docs/ssot/jobs/nest/2026-11-24-ada-nest-drive-store-hardening.yml`
- tests: `tests/colab/test_job_console.py`, `tests/ops/test_nest_queue_watch.py`,
  `tests/ada/test_nest_worker_scan.py`

## Verification
- `python3 -m pytest tests/colab/ tests/ops/test_nest_queue_watch.py
  tests/ada/test_nest_worker_scan.py tests/board/test_stalled_claim_lifecycle.py
  tests/colab/test_pack_preflight.py tests/devnest/test_kk_mac_lane_worker.py
  tests/ops/test_kk_mac_worker_installer.py -q` → **179 passed**
  (8 deselected: `test_kk_mac_image_render_poc.py` fails identically on
  clean HEAD — pre-existing, unrelated).
- New coverage: e2e drain asserts lease JSON + no heartbeat file; e2e
  packs-index claim/done events + `NEST_HF_REPOS` in prep env; launcher
  fresh-lease-without-heartbeat blocks; watch fixture serves lease JSON;
  nest-worker `index_event` unit tests.
- JOBS.py restore/save prep strings extracted and `bash -n` clean;
  restore selection exercised end-to-end against real tar.zst fixtures:
  named repo → per-repo tar; named repo missing per-repo tar → monolith
  `hub/models--*` subtree in one pass; `NONE` → skip; unset → full
  monolith; monolith-less per-repo fallback verified.
- All modified .py files `py_compile` clean; all 16 annotated pack.yml
  parse via `yaml.safe_load`.

## Deploy notes (for whoever lands this)
- `queue-runner.py` → Drive `queue/runner.py` via the documented fleet
  rclone flow; purge `queue/__pycache__` after bumping JOBS.py.
- `nest-worker.py`/`nest-pack-submit.py` deploy via chaba-repo-sync.
- Backward compatible: pre-unification runners still write heartbeat +
  old-format lease; all readers fall back. Per-repo tars appear only
  after the next `save-hf-cache` run — until then restore uses the
  monolith (or per-repo subtree semantics unchanged).

lessons:
- rclone has no Drive append — per-event immutable files beat a shared
  index.json for multi-writer (FUSE + rclone) state; fold at read time.
- `os._exit` in fence paths bypasses `finally` — any cleanup a dead
  runner owes the store must run BEFORE the exit, not in finally.
- A pack field that only some workers understand is safe when absent =
  old behavior (hf_repos: undeclared HF use self-downloads).
- Lease-as-liveness works only if the writer can't resurrect a lost
  lease — heartbeat() rewrites lease only while it still names us.
- `tar -xf archive member-dir` extracts the whole subtree — selective
  restore works from a monolith before per-repo archives exist; pass all
  wanted members in ONE tar invocation or you pay N decompress passes.
- Unset env fallback must keep the OLD complete-restore semantics
  (monolith first); per-repo tars only pay off on the selective path.
