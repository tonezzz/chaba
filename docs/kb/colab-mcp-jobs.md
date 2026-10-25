# Colab MCP job pattern — the 4-step standard

Standard shape for any ad-hoc job driven through the `colab` MCP server
(`googlecolab/colab-mcp`, registered as `colab` in mcp_config.json).

The publish step is **part of the job**, not a follow-up — a job is not
done until its output has a durable home (artifact-landing rule,
`ssot.procedures.yml`).

## Steps

1. **Attach** — `open_colab_browser_connection` → user connects in browser →
   cell tools unlock. MCP attaches to the **scratch notebook**, not the
   serve-worker (whose kernel is busy in keep-alive).
2. **Setup cell** — install what the job needs (ollama via
   `ollama-linux-amd64.tar.zst` + `apt install zstd`, or pip). Pull datasets
   via `colab-gdrive-cache` (drive mount → packed artifact → extract local)
   or a fast mirror — never the slow origin directly.
3. **Job cell(s)** — the actual work. Write intermediate output to
   `/tmp` on the runtime AND return it in cell output (MCP fetches outputs
   via `get_cells includeOutputs`).
4. **Publish (mandatory)** — the agent turns output into a durable home in
   the same step it collects it:
   - report/analysis → CMS leaf page in `ada-cms-pages` (`mddb add_document`,
     meta: `report_role`, `generated_by`, `sources`, `parent`) —
     `ssot.apps.cms-reports.yml` format
   - card outcomes → `comms:` via board-api
   - reusable artifacts → gdrive cache (`rclone` on tony-dell if mount fails)
   - parked ideas → `docs/ssot/focus-inbox/`
   Never: output in `/tmp` only, or pasted in chat only.

## Verified example (2026-10-12)

Backlog triage: ollama + `gemma3:12b` installed on scratch T4 (147s), 100
kanban cards classified in 2x50 parallel batches (204s+296s), published as
`ada-cms-pages/backlog-triage-2026-10-12`.

## Gotchas

- `run_code_cell` may return `Canceled`/empty — the cell often still runs
  server-side; poll `get_cells includeOutputs` instead of re-firing.
- Kernel serializes cells — a blocking cell (keep-alive, hung download)
  stalls everything queued behind it; interrupt via the notebook stop button.
- `drive.mount()` in an MCP-run cell can fail (`ValueError: mount failed`)
  — run the mount cell manually in the notebook, or push artifacts from a
  fleet host via `rclone` (`gdrive:` remote on tony-dell).
- Runtime type (T4 etc.) is a UI-only pick — no MCP tool for it.
- Colab ends sessions on idle/quota — treat the runtime as ephemeral;
  anything worth keeping must land in step 4 before it dies.
- **VRAM: prefer resident + batched over sequential offload** (verified
  2026-10-22, LTX T4): `enable_sequential_cpu_offload()` leaves the GPU
  idle during CPU↔GPU layer shuttles — only needed when activations OOM.
  If the model fits (bf16 transformer ~4GB), `pipe.to('cuda')` + *batched*
  prompt embeds (stack B prompts into one denoise pass) fills the card:
  3 shots in 591s at 12.5/14.5GB peak vs ~233s/shot serial-offloaded.
- **System RAM (12GB), not VRAM, is the usual kill constraint**: loading a
  second pipeline into a live kernel while the first still holds ~9GB RAM
  OOM-kills the kernel silently (cell just stops, GPU memory orphaned).
  Rule: one self-contained load→render→publish cell per pipeline variant;
  `os._exit(0)` crashes just the kernel — frees orphaned GPU mem while
  `/tmp` weights + Drive mount (VM-level) survive.
- Drive FUSE writes flush async — files may `cp` locally but not appear
  to rclone for ~60s; poll before archiving. Multi-GB writes are worse:
  `tar` can exit 0 while DriveFS is still uploading in the background —
  a runtime restart before the remote listing shows the file LOSES it
  (observed: 13GB hf-hub.tar.zst written, VM restarted, never landed).
  "Durable" means visible in `rclone lsf` from a fleet host, not present
  in the local mount. Keep the VM alive until big artifacts verify.
- `torch_dtype=` (not `dtype=`) is the diffusers kwarg; the wrong one is
  silently ignored and loads fp32 (slow + big).
- **Poll out-of-band, not through MCP** (verified 2026-10-23): while the
  runner cell holds the kernel, `run_code_cell` queues behind it and MCP
  `get_cells` never sees `subprocess` output. Watch progress from a fleet
  host instead: `rclone cat gdrive:ada-nest/queue/log-<date>.txt` +
  `queue/prep-<name>.log` + `queue/done/`. con01 has `~/.local/bin/rclone`.
- **HF cache dies with the runtime** — a fresh T4 re-downloads ~19GB of
  LTX weights with the GPU idle (the first job's prep can't hide under
  anything). Persist it like any packed artifact: see the cache-restore/
  save jobs below.

## Batch-queue mode (verified 2026-10-23)

For multi-experiment sessions, drive the notebook from a **manifest** instead
of staging cells per job:

- **Manifest** — `gdrive:ada-nest/queue/JOBS.py`: a `JOBS` list of
  `{name, scope, prep, run, artifacts}` — `prep` is a shell string
  (fetch/install/extract), `run` is a Python source string exec'd in a
  shared namespace. `scope` (default `'work'`) picks the marker space;
  `artifacts` is a list of globs vs `ada-nest/` that must match ≥1
  non-empty file before the job may mark done.
- **Runner cell** — one self-contained cell loops the manifest: per-job
  try/except isolation, `queue/done/<name>.done` markers make it
  resumable (rerun the same cell after any crash/recycle), and every job
  publishes its artifact to Drive inside its own `run`.
- **Overlap rule** — while job N's `run` holds the GPU, the runner starts
  job N+1's `prep` in a background `Popen` and `wait()`s for it before
  that job's run. This is how you fill the GPU: downloads, tar extracts
  and pip installs are CPU-bound, denoise is GPU-bound — running them
  serially wastes one side or the other. On 2026-10-22 the LTX 17GB
  extract (~9min CPU) ran entirely inside the VoxCPM2 gen window.
- **Write the manifest from a fleet host** (`rclone copy JOBS.py
  gdrive:ada-nest/queue/` from tony-dell) — no notebook edit needed to
  requeue; bump the file and rerun the cell.
- **Order jobs GPU-heavy-first within constraints**: queue the work that
  needs no new weights first if its inputs are already staged; put the
  big extract/download as the *next* job's prep so it hides under the
  current job's GPU time.
- **Done markers + log**: `queue/done/` + `queue/log-<date>.txt` +
  `queue/prep-<name>.log` (prep stdout/stderr) on Drive are the durable
  record — the notebook doc can be recycled at will.
- **Marker scope is part of the contract** (2026-10-23): `scope:'env'`
  jobs (pip installs, `/tmp` extracts, HF-cache restore/save) mark under
  `queue/env-done/<boot_id>/` so a fresh VM always re-runs them — a pip
  install cannot outlive its VM. `scope:'work'` (default) marks under
  `queue/done/` globally. Earlier, a runtime restart left a stale
  `deps.done` while the pip env was gone — the next job died on import.
- **Verify-before-mark** (2026-10-23): a job's `run` returning is not
  proof its artifact landed — observed live: `save-hf-cache.done`
  existed while `hf-hub.tar.zst` never reached Drive (runner exited
  before the FUSE upload flushed). The runner now requires every
  `artifacts` glob to match ≥1 non-empty file and records matched sizes
  in the marker; a fleet-side rclone check remains the server-side
  truth. Runner also settles 120 s after drain so big uploads land
  before the VM idles.
- **Detached mode (2026-10-23)** — prefer `queue-launcher-cell.py`: it
  starts `queue/runner.py` as a session-detached process (output →
  `queue/run-<ts>.out.log`, pid → `queue/runner.pid`, `queue/heartbeat`
  rewritten every 15 s). The kernel stays free for diagnostics mid-run,
  and the queue survives a kernel restart. Blocking in-kernel mode is
  only for interactive debugging.
- **Interrupts don't propagate into `subprocess.run`** — a cell stop
  button may leave a hung prep/running job alive; only
  Runtime → Interrupt execution reliably kills it (MCP has no interrupt
  tool). Preps launched `start_new_session=True` die with the runner on
  VM/kernel teardown.
- **Never bare-`snapshot_download` multi-variant repos** — LTX-Video is
  ~187 GB across all variants; only transformer+vae+scheduler (~9 GB)
  are needed. Always `ignore_patterns` (text_encoder/tokenizer/.bin/fp8)
  or the disk fills mid-queue (observed: ENOSPC at 235 GB used, killed
  the run's final job). Surgical cleanup: keep only the snapshot paths
  the pipeline loads, then delete unlinked blobs + `*.incomplete`.
- **Per-clip timeouts** — any GPU call that can hang gets a
  `signal.alarm(N)` guard + a `start` print before it; a silent stall
  otherwise looks identical to a slow run (VoxCPM2 sat ~1 h at 0% GPU).
- **Bracket every manifest with cache jobs** so the second runtime of a
  session (or the next session) skips weight re-downloads entirely:
  ```python
  {"name":"restore-hf-cache","scope":"env",
   "prep":"test -f /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
          " && mkdir -p /root/.cache/huggingface"
          " && tar -I zstd -xf /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
          "    -C /root/.cache/huggingface || true",
   "run":"import os;print('hub entries:',len(os.listdir('/root/.cache/huggingface/hub'))if os.path.exists('/root/.cache/huggingface/hub')else 0)"},
  # ... gpu jobs whose preps stay `snapshot_download` — they validate the
  # restored cache instantly instead of re-downloading ...
  {"name":"save-hf-cache","scope":"env","artifacts":["cache/hf-hub.tar.zst"],
   "prep":"tar -I zstd -cf /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
          " -C /root/.cache/huggingface hub",
   "run":"print('hf cache packed')"},
  ```
  Drive read + zstd decompress beats an HF re-pull, and `snapshot_download`
  becomes a fast no-op validator when the cache is warm. Keep the
  `snapshot_download` preps regardless — they self-heal when the tar is
  missing or stale.
- **The first GPU job's prep is the one un-hideable window** — nothing
  runs before it. Minimize it: cache-restore first, and order the queue
  so the job needing the *least* new download runs first; every later
  prep hides under a GPU run.

## Packs — work units for any worker (nest-pack v2, 2026-10-23)

OPS-0759: work now ships as **packs**, not manifest jobs — a pack is a
self-contained bundle any capable worker on any store can claim, so the
same bundle runs on Colab today and a fleet host tomorrow.

- **Layout** — `ada-nest/packs/<name>/pack.yml` (+ optional `inputs/`):
  ```yaml
  name: my-job
  needs: {gpu_gb: 3, disk_gb: 4, ram_gb: 8, egress_only_ok: true}   # capability floor
  timeout_s: 1200     # runner-side SIGALRM around the whole run
  artifacts:          # globs vs ada-nest/ root — verify-before-mark gate
    - packs/my-job/out/*.wav
  prep: |             # shell — CPU-bound fetch/install (same as manifest)
    pip install -q ...
  run: |              # python exec'd in shared ns; PACK_DIR injected
    ...
  # run_sh: |       # alternative: shell run instead of python
  ```
- **Canonical source** = `scripts/colab/packs/<name>/` in the chaba repo;
  deploy to Drive with `rclone copy` (con01 has rclone).
- **Claiming** — worker writes `packs/<name>/claim/<worker-id>`
  (first-writer-wins, 2 s settle; Drive listing lag makes it best-effort
  for simultaneous claims — fine at our scale). Done marker is a FILE:
  `packs/<name>/done` (note: not `.done` suffix — inside the pack dir).
- **needs check** — workers advertise `gpu_gb` (nvidia-smi),
  `disk_gb` (statvfs), `ram_gb` (sysconf SC_PHYS_PAGES), and
  `egress_only_ok` (Colab can only egress). Unmatched packs skip
  cleanly with the reason logged — RAM floors (added 2026-10-24) keep
  low-RAM hosts (mn01: 7G) from claiming Colibri-class packs.
- **Packs run AFTER the whole JOBS manifest** — so keep env/bootstrap
  (cache restore, deps, asset extract) in JOBS.py and everything else as
  packs. A pack can depend on env jobs' outputs (`/tmp/vbench` etc.) but
  must not assume other packs ran — order is `sorted(os.listdir)` and
  claims are independent.
- **PACK_DIR** — `ada-nest/packs/<name>` absolute path, injected into the
  run namespace; write outputs under `PACK_DIR/` so the pack stays
  self-contained and the artifacts globs stay inside the pack.
- **No signal.alarm inside pack run code** — it cancels the runner's
  timeout_s alarm. Per-step guards belong in the runner or a thread.
- Verified live 2026-10-23: `smoke` pack (lifecycle proof) +
  `thonburian-bench` (Thai voice-clone eval — 10 wavs in 98 s on T4,
  report.md inside the pack dir).
- **Member-surface mirror** — queue-mgr (dell, watches the Drive store)
  mirrors job/pack state into WP `nest_job` posts via board-api
  `POST /job` (upsert by slug, `status`, `comms` append log, `parent`
  for job trees). Watchers stay read-only on Drive; the door is the
  only writer — workers and Colab never hold WP creds.
  See `docs/kb/board-api-write-door.md`.

### Gap packs — idle GPU during main-queue prep (2026-10-25)

`ada-nest/queue/gap-runner.py` fills the GPU-idle prep/prep-wait windows
of the main queue with tiny self-contained **gap packs** under
`ada-nest/gap-packs/<name>/pack.json`. It runs only while the main
heartbeat is fresh (<=60s) AND phase is `prep`/`prep-wait`, a VRAM gate
passes, and `queue/gap-lease` is free — and it SIGKILLs the pack's process
group the moment the window closes (claim released for retry). Gap packs
never pull models, never touch HF/Drive caches or production indexes, and
get `done`/`failed` FILE markers plus verify-before-mark artifact gates —
all under `gap-packs/`, never the main pack space. Canonical source:
`scripts/colab/gap-runner.py` + `scripts/colab/gap-packs/`; launch once
per runtime with `scripts/colab/gap-launcher-cell.py`. Policy + contract:
`gap-packs/PROCEDURE.md`; job record:
`docs/ssot/jobs/nest/2026-10-25-ada-nest-gap-runner.yml`.

### Writing packs — lessons so far

- Declare honest `needs` floors — they decide which workers can take the
  pack; too high and it starves, too low and it claims then OOMs.
- `ref_text`-equivalent inputs belong in `inputs/` (pack-local) when not
  already staged by an env job — a pack is meant to be self-contained.
- Pack `run` is exec'd in a *shared* namespace with the manifest jobs —
  pop stale `model`/`pipe` globals and `torch.cuda.empty_cache()` first.
