# Colab MCP job pattern — the 4-step standard

Standard shape for any ad-hoc job driven through the `colab` MCP server
(`googlecolab/colab-mcp`, registered as `colab` in mcp_config.json).

The publish step is **part of the job**, not a follow-up — a job is not
done until its output has a durable home (artifact-landing rule,
`ssot.procedures.yml`).

## Job-console notebook — the canonical operator surface (OPS-0874)

For queue work the operator surface is ONE notebook —
`ada-nest/queue/ada-nest-job-console.ipynb` on Drive (canonical source
`scripts/colab/ada-nest-job-console.ipynb`, regenerated from the cell
sources by `scripts/colab/build-job-console.py`). It is instruction
markdown + exactly two code cells; there are **no per-job cells** — all
workloads are queue jobs/packs (`JOBS.py` + `packs/<name>/pack.yml`).

- **Cell 1 — preflight** (`scripts/colab/preflight-cell.py`): mounts
  Drive, checks for another fresh managed runtime, then prints identity
  (boot_id, GPU model/VRAM, RAM, Drive state), registers this VM at
  `queue/runtime-sessions/<boot_id>.json`, and refreshes it on a 60 s
  background heartbeat. A refused duplicate does not register or leave a
  heartbeat. After successful registration, it starts a runtime-local
  watcher for `mcp-colab` queue-start requests targeted at this boot ID.
  Deliberate two-VM ops set `ALLOW_SECOND_RUNTIME = True` and re-run; the
  queue lease then arbitrates writers.
- **Cell 2 — launch once** (`scripts/colab/queue-launcher-cell.py`):
  gates on Drive-mounted, GPU present (CPU runtimes refuse — the queue
  exists to fill a T4), and no fresh peer runtime, then starts
  `queue/runner.py` detached. It remains the manual fallback if the MCP
  command path is unavailable.
- **MCP launch** — after cell 1 registers a fresh T4, call
  `mcp-colab.colab_queue_start(boot_id, confirm=True)`. It writes a
  boot-targeted request to Drive; only that runtime's watcher can invoke
  the same gated launcher. The tool cannot create or stop a Colab runtime,
  and requires explicit confirmation because queue work consumes the
  active runtime's quota and can write cache/artifact files. If the runtime
  is disconnected, the watcher cannot run the request.
- **Managed-session detection is registry-scoped.** The registry sees
  only VMs that ran cell 1. Uninstrumented notebooks are invisible to it
  — Google *Runtime > Manage Sessions* stays authoritative, and nothing
  ever auto-stops a session (OPS-0872).
- **Runner identity is boot-scoped** (PID-collision fix): the runner
  writes `queue/runner.id` `{pid,boot_id,worker,epoch,ts}` beside the
  legacy `runner.pid`. A Drive-visible PID is never a process handle on
  another VM — the launcher only signals a pid when runner.id's boot_id
  equals this VM's `/proc` boot_id. Same-VM zombies (alive pid + stale
  heartbeat) are reaped; foreign/stale records are left untouched and a
  fresh heartbeat from another boot refuses the launch. On exit the
  runner removes its identity files only when they still name it, so a
  fenced-out generation can't strip a live runner's marks.
- **Registry/state layout**: `queue/runtime-sessions/<boot_id>.json` (managed
  VMs), `queue/runner.id`, `queue/lease` (unified liveness —
  `{worker,epoch,ts,job,phase}`; `queue/heartbeat` is the retired legacy
  file kept only as a reader fallback), `queue/packs-index/` (per-event
  pack state files), `queue/warmup/<boot_id>.json` (per-boot warmup
  stats). Fleet-side read: `mcp-colab` tool `colab_session_status`.
- **Snapshot constraint**: the runner imports `JOBS.py` and scans
  `packs/` ONCE at launch, runs all JOBS before the (name-sorted) packs,
  and overlaps only the *next* job's `prep` under the current `run`.
  Stage every pack before starting cell 2 — mid-run uploads are not
  picked up until the next launch.

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
- **Detached mode (2026-10-23; hardened 2026-10-26)** — the launch path
  is cell 2 of the job-console notebook (`queue-launcher-cell.py`): it
  starts `queue/runner.py` as a session-detached process (output →
  `queue/run-<ts>.out.log`, identity → `queue/runner.id`, unified
  liveness → `queue/lease` JSON `{worker,epoch,ts,job,phase}` rewritten
  every 15 s — the legacy `queue/heartbeat` text file is retired;
  readers fall back to it for pre-unification runners, ADA-0806) after
  the session gate described above. The
  kernel stays free for diagnostics mid-run, and the queue survives a
  kernel restart. Blocking in-kernel mode is only for interactive
  debugging.
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
  session (or the next session) skips weight re-downloads entirely.
  Since ADA-0806 the cache is stored **per repo** —
  `cache/hf-hub/models--<org>--<name>.tar.zst` — and `save-hf-cache`
  writes those plus the legacy `cache/hf-hub.tar.zst` monolith (kept one
  transition cycle). `restore-hf-cache` honors `NEST_HF_REPOS` (the
  runner sets it to the union of `hf_repos` over packs/jobs still
  pending this boot): named repos extract only their own tar — or their
  `hub/models--*` subtree out of the monolith in ONE tar pass, so
  selective restore works even before per-repo archives exist;
  `'NONE'` skips the extract entirely; unset (only pre-ADA-0806 runners)
  restores the whole monolith, with per-repo tars as the monolith-less
  fallback:
  ```python
  {"name":"restore-hf-cache","scope":"env",
   # prep/run as shipped in scripts/colab/JOBS.py — selective via
   # $NEST_HF_REPOS: 'NONE' skips, 'org/name ...' extracts only those
   # cache/hf-hub/models--org--name.tar.zst archives
   ...},
  {"name":"save-hf-cache","scope":"env",
   "artifacts":["cache/hf-hub.tar.zst","cache/hf-hub/*.tar.zst"],
   # prep tars each /root/.cache/huggingface/hub/models--* dir into
   # cache/hf-hub/<name>.tar.zst AND the legacy monolith
   ...},
  ```
  Drive read + zstd decompress beats an HF re-pull, and `snapshot_download`
  becomes a fast no-op validator when the cache is warm. Keep the
  `snapshot_download` preps regardless — they self-heal when the tar is
  missing or stale. Packs declare their hub need via `hf_repos:` (see
  Packs below) so a pending LTX pack restores LTX-Video, not VoxCPM2.
- **The first GPU job's prep is the one un-hideable window** — unless you
  put the warmup first. Canonical `JOBS.py`
  (`scripts/colab/JOBS.py`) opens with `t4-session-warmup` (scope `env`):
  a small GPU smoke that keeps running until the *next* job's background
  prep exits (`WARMUP_MIN_S` 30 s floor, `WARMUP_MAX_S` 300 s cap), so the
  ~4-min `restore-hf-cache` extract hides under useful GPU work instead of
  idling the T4. Verified 2026-10-25 on boot 326f1d48: warmup 61 s/
  431 k matmuls while the cache restore ran 223 s. The runner injects
  `QUEUE_PENDING` ((name, log, Popen) of the bg prep) + `BOOT_ID` into
  every job's run namespace — that is how the warmup knows when the prep
  exits. Warmup stats land at `queue/warmup/<boot_id>.json` and are the
  job's `artifacts` gate (`{boot_id}` expands in artifact globs).
  Remaining order rule: cache-restore second, least-new-download work
  early, every later prep hides under a GPU run.

### Standard launch sequence — stage first, assessment before cache prep (OPS-0880, 2026-10-26)

The launch order that keeps the T4 fed end-to-end:

1. **Stage everything before launch.** The runner snapshots `JOBS.py`
   and the `packs/` listing ONCE at startup — anything uploaded mid-run
   waits for the next launch. Fleet-side staging is an rclone copy of the
   canonical repo files (`scripts/colab/{JOBS,queue-runner→runner,
   runtime_registry,preflight-cell,queue-launcher-cell,ada-nest-job-console}.py`
   → `gdrive:ada-nest/queue/`, `scripts/colab/packs/` →
   `gdrive:ada-nest/packs/`); purge `queue/__pycache__` after bumping
   JOBS.py so a stale `.pyc` can't shadow the new manifest, and confirm
   `rclone check` reports 0 diffs before any VM opens the console.
2. **One cache-independent held-out assessment immediately before the
   next model/cache prep.** Canonical slot: `devnest-heldout-assessment`
   in JOBS.py between `assets-stage` and `save-hf-cache` — a fixed
   fp16/bf16 TFLOPs + H2D/D2H battery plus a production-log overlap
   audit, zero model/pulls (torch ships with the runtime image), so it
   stays valid while `/root/.cache` mutates underneath. Its GPU run hides
   the multi-minute `save-hf-cache` repack — the second un-hideable
   window after the first job's prep (which the warmup covers). Reports:
   `queue/assessments/devnest-heldout-<boot_id>.{json,md}`, env-scoped so
   every boot writes fresh evidence.
   - **Not a benchmark pass.** This is a worker/queue assessment. The
     DevNest replay benchmark's five safe fixtures + held-out verifiers
     are unfrozen — never report one as the other.
   - If the assessment needs to precede a specific *pack's* model prep
     instead, name/place it so it sorts just before that pack (packs run
     alphabetical after JOBS) — the runner only ever overlaps the NEXT
     undone job's prep under the current run; run stages stay serial.
3. **After prep, the T4 package runs with durable-artifact gates.**
   env `scope` jobs re-run per boot; packs claim → prep → run →
   verify-before-mark (`artifacts` globs must hit ≥1 non-empty file) →
   `packs/<name>/done`. The `NEST_QUEUE_SETTLE_S` drain window (default
   120 s) is the stage-then-push flush window: packs should write big
   outputs to local disk and copy them into the Drive path, and after
   settling the runner re-stats every artifact pattern marked done this
   session — sizes still growing mean the FUSE flush was incomplete at
   mark time (the 2026-10-23 lost-tar class); the check is logged for
   the fleet audit and never fails the queue. Server-side truth is
   `rclone lsf` from a fleet host.

## Packs — work units for any worker (nest-pack v2, 2026-10-23)

OPS-0759: work now ships as **packs**, not manifest jobs — a pack is a
self-contained bundle any capable worker on any store can claim, so the
same bundle runs on Colab today and a fleet host tomorrow.

- **Layout** — `ada-nest/packs/<name>/pack.yml` (+ optional `inputs/`):
  ```yaml
  name: my-job
  needs: {gpu_gb: 3, disk_gb: 4, ram_gb: 8, egress_only_ok: true}   # capability floor
  hf_repos: [Lightricks/LTX-Video]   # HF hub repos this pack needs in
                                   # /root/.cache/huggingface/hub —
                                   # drives selective restore-hf-cache
                                   # (ADA-0806). Absent = no declared HF
                                   # need; undeclared use self-downloads.
  requires: [my-release-preflight]  # claim gate — wait for done marker(s)
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
  A worker releases its own claim on FAIL, on done, and before a
  fence-exit self-kill — a dead claim never waits out the stale-claim
  window (ADA-0806).
- **packs-index** — every state change also drops one tiny immutable
  JSON event at `queue/packs-index/<ms>-<worker>-<pack>-<state>.json`
  (states: `stage|claim|done|fail|release`; writers: nest-pack-submit,
  nest-worker, queue-runner). Fleet scans fold the dir in ONE rclone
  copy instead of `lsf` per pack; the index is advisory — consumers
  (`nest-queue-status.py`) fall back to live per-pack checks for
  anything not called terminal.
- **needs check** — workers advertise `gpu_gb` (nvidia-smi),
  `disk_gb` (statvfs), `ram_gb` (sysconf SC_PHYS_PAGES), and
  `egress_only_ok` (Colab can only egress). Unmatched packs skip
  cleanly with the reason logged — RAM floors (added 2026-10-24) keep
  low-RAM hosts (mn01: 7G) from claiming Colibri-class packs.
- **Packs run AFTER the whole JOBS manifest** — so keep env/bootstrap
  (cache restore, deps, asset extract) in JOBS.py and everything else as
  packs. A pack can depend on env jobs' outputs (`/tmp/vbench` etc.) but
  must not assume other packs ran — claims are otherwise independent.
- **`requires:` is a claim gate, not just ordering** (2026-10-27,
  kk-video-preflight-stage): a pack may declare
  `requires: [pack-name, ...]`. Both workers (Colab `queue-runner.py`,
  fleet `nest-worker.py`) refuse the claim until every required pack's
  `done` marker exists; a requirement whose name ends `-preflight` must
  also show a readable `preflight.json` with verdict `pass` or `warn` —
  that is what makes a failed release preflight block its embed/render
  dependents. `load_packs` emits discovered packs requires-first
  (Kahn over the staged set), so a CPU-only `*-preflight` pack drains
  before its GPU dependents inside one launch. Stage the whole release —
  preflight pack + dependents — BEFORE cell 2; pack discovery still
  happens once at runner start, so the stage never retro-fits a running
  queue snapshot.
- **Release preflight pack** — `scripts/colab/pack-preflight.py` is the
  canonical deterministic validator (manifest/provenance, planning docs,
  fact-vs-dream, identity policy, audio/subtitle decision, pack.yml
  contract, artifact globs, output privacy, needs/timeout declarations,
  no paid/public-publish flags). A `*-preflight` pack carries it plus a
  `policy.yml` (see `packs/kk-video-c9f99fee6146-preflight/`): project
  docs resolve from `$NEST_ROOT/projects/<id>/` or the pack's
  `inputs/<id>/`. Outputs `preflight.json` + `preflight.md` are
  byte-deterministic (hashes, no timestamps) and carry a per-pack +
  `release_sha256` hash reference.
- **PACK_DIR** — `ada-nest/packs/<name>` absolute path, injected into the
  run namespace; write outputs under `PACK_DIR/` so the pack stays
  self-contained and the artifacts globs stay inside the pack.
- **No signal.alarm inside pack run code** — it cancels the runner's
  timeout_s alarm. Per-step guards belong in the runner or a thread.
- Verified live 2026-10-23: `smoke` pack (lifecycle proof) +
  `thonburian-bench` (Thai voice-clone eval — 10 wavs in 98 s on T4,
  report.md inside the pack dir).
- **Member-surface mirror** — `scripts/ops/queue-mgr.py` (tony-dell,
  `queue-mgr.timer` every 5m via ssot.jobs.yml) watches the Drive store
  and mirrors job/pack state into WP `nest_job` posts via board-api
  `POST /job` (upsert by slug, `status`, `comms` append log, `parent`
  for job trees). One root post `ada-nest-queue` (kind=queue) parents
  every pack (kind=pack) and manifest job (`job-<name>`, kind=sub);
  root status is derived from children. Writes are delta-only — a
  per-slug fingerprint in `~/.local/state/queue-mgr.json` means
  unchanged entities cost zero WP calls, and `comms` lines land only on
  transitions. Kill switch: `touch ~/.config/queue-mgr.off` on
  tony-dell; `--dry-run` prints the derived plan with no writes.
  Watchers stay read-only on Drive; the door is the only writer —
  workers and Colab never hold WP creds.
  See `docs/kb/board-api-write-door.md`.

### Gap packs — idle GPU during main-queue prep (2026-10-25)

`ada-nest/queue/gap-runner.py` fills the GPU-idle prep/prep-wait windows
of the main queue with tiny self-contained **gap packs** under
`ada-nest/gap-packs/<name>/pack.json`. It runs only while the main
queue liveness is fresh (<=60s — `queue/lease` ts, heartbeat fallback)
AND phase is `prep`/`prep-wait`, a VRAM gate
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

## Job status lifecycle and storage map

How a nest job's status flows across the four surfaces, and where each
piece of truth lives (OPS-0922 SOP: `docs/kb/job-package-status-sop.md`;
enforcement: OPS-0923).

| Surface | What it stores | Writer / reader |
|---|---|---|
| `queue/lease` | unified liveness `{worker,epoch,ts,job,phase}` — what the runner is doing *right now* | runner rewrites ~15 s; `queue/heartbeat` text is the pre-unification fallback |
| `packs/<name>/claim/` + `done`/`failed` markers | per-pack queue truth — who claimed, terminal proof | worker writes claim, verify-before-mark writes `done`; readers: `nest-queue-status.py`, `nest-job-reconcile.py` |
| `queue/packs-index/*.json` | advisory event fold `{ts,pack,state,worker}` — `stage|claim|done|fail|release` | nest-pack-submit / nest-worker / queue-runner write; fleet scanners fold in one rclone copy; never authoritative alone |
| WP `nest_job` CPT meta | member-facing mirror — `status`, `result_ref`, `error`, `evidence`, `artifact_verified`, `comms[]` | board-api `/job` (and `/publish` job sink) is the ONLY writer; queue-mgr mirrors Drive state through it |

Status flow: `queued → claimed → running → done|failed|stalled|
cancelled`. `done`/`cancelled` are terminal — they exit only via
`queued` (explicit requeue) or `failed` (honest correction).

Write-door contract (enforced in `do_job`, board-api):

- transitions follow `JOB_TRANSITIONS` — illegal jumps get HTTP 400;
- `status=done` requires `result_ref` **and** verified artifact
  evidence (`evidence[]`, `verified:true`, or `confidence=verified`);
- `/publish` milestones never imply `done` — only an explicit
  `meta.job_status` does, and it hits the same gate;
- evidence lands in `meta.evidence` + `meta.artifact_verified` so the
  mirror carries its own proof.

Read side: `GET /nest-jobs` on board-api lists the mirror (slug,
status, meta — comms stripped unless `comms=1`);
`scripts/ops/nest-job-reconcile.py` cross-checks all four surfaces and
reports drift without mutating anything.
## KK-Mac isolated Nest and DevNest jobs

Use this lane for explicitly approved, bounded work on KK's member Mac
(`kk-mac`, M4 Max, 36 GiB unified memory). It is not a general-purpose
always-on fleet worker. The host is owner-first, may go offline without
notice, and must pass a fresh resource admission before each run. Keyboard
or mouse input and an open design app are not blockers by themselves.

### Stores and lane boundaries

- Video/MPS experiments use the isolated root
  `gdrive:ada-nest-kk-mac-video-pilot`.
- Local-model/DevNest experiments use the separate root
  `gdrive:ada-nest-kk-mac-pilot`.
- Never mix the two roots or launch a worker against `gdrive:ada-nest`
  from KK-Mac. A Mac worker's `--once` scans every claimable pack in its
  selected root, not just a named pack.
- The recorded Qwen3:8B model-only slot in the LLM root is `partial` (2/5
  fixtures) and postdates the `deterministic-only` decision recorded on
  OPS-0966. Do not rerun or extend that inference lane until its authorization
  is reconciled.

### Admission and package contract

1. **Card and lifecycle first.** Link the job to the relevant card and create
   `planning` before execution. State the exact input hashes, output contract,
   timeout, privacy, stop condition, owner workload protection, and rollback.
2. **Use a versioned, bounded pack.** One pack should do one verifiable unit
   (for video, one shot); use an immutable name for each revision. Declare
   `needs.ram_gb` and `needs.disk_gb`. Do not use `gpu_gb` to describe Apple
   MPS capacity: the generic fleet worker probes NVIDIA with `nvidia-smi`.
3. **Do not treat `egress_only_ok: false` as host pinning.** The generic
   `nest-worker.py` ignores that field when matching capabilities. The isolated
   Mac root plus an explicit trusted-host one-shot launch is the placement
   control; never run a generic fleet worker against that root.
4. **Keep Mac execution offline and cache-only.** Pin the local model revision,
   set `HF_HUB_OFFLINE=1`, verify required model files before inference, and
   do not install dependencies, pull models, change services, or read personal
   files unless separately approved.
5. **Repeat safety gates in the pack's `prep`.** Require AC power, at least
   80% free system memory before loading the video model, no resident Ollama
   model, no competing Nest worker, and no active render/export process.
   Sample design-app and system CPU with `mac-owner-resource-gate.py`;
   recent input is informational and idle open apps may remain open. If a
   gate fails, return nonzero before model load. Never close owner apps,
   unload owner models, or stop owner workers to make a pack pass.
6. **Hash-bind private inputs.** Put only the approved source files in
   `inputs/`; verify source revision, audit record, image page, embedding and
   byte/hash values before model load. Do not stage voice references or
   narration unless the pack explicitly needs them.
7. **Keep artifact gates strict.** Declare every required non-empty output;
   independently verify media codec, size, frame count/duration, full decode,
   black-frame threshold, output hash and private visibility. Technical pass
   is not human quality approval.

### Stage, run, verify

1. Stage from a trusted fleet checkout to the specific Mac root:
   `nest-pack-submit.py <pack-dir> --remote gdrive:ada-nest-kk-mac-video-pilot`.
   Dry-run first; use a new pack name; then require `rclone check --one-way`
   to report zero differences. The Colab MCP pack submitter may not be able to
   see a satellite worktree path.
2. Before launch, verify Tailscale reachability and the trusted tony-dell to
   kk-mac SSH route without disabling host-key checking. Read AC state,
   memory pressure, resident-model count, owner-app gate, disk and model-cache
   status. If the Mac is offline or busy, leave the pack staged and stop.
3. Confirm the isolated root contains only the intended runnable pack(s), no
   active claim, and a completed prerequisite marker. Then run exactly one
   worker pass from the trusted Dell hop:
   ```bash
   ssh -o BatchMode=yes kk-mac \
     '$HOME/kk-video/.venv/bin/python "$HOME/CascadeProjects/chaba/scripts/ada/nest-worker.py" \
       --once --remote gdrive:ada-nest-kk-mac-video-pilot \
       --workdir "$HOME/.cache/nest-worker"'
   ```
   Do not start a persistent loop or launch parallel workers. The worker scans
   every claimable pack in that root and runs them serially.
4. If `prep` stops, treat that as a successful safety stop: do not retry until
   a fresh preflight passes. If `run_sh` fails, inspect the claim/log and
   artifact state before retrying. A failed run may leave local partial output;
   stage per-shot packs or explicitly publish each verified checkpoint if
   resumability is required.
5. Require a remote `done` marker, non-empty declared artifacts, and a
   fleet-side `rclone check`/read-back. Update the lifecycle and card through
   board-api; keep human review separate from technical verification.

### Renderer-neutral video contract

Keep one shared job record and make renderer details adapter-specific. The
same lifecycle can drive local MLX, local MPS, or a hosted provider without
pretending their capabilities, cost, or continuity are interchangeable.

1. The shared job record captures project/card, private-by-default visibility,
   immutable job/version ID, source asset paths and SHA-256 values, action
   plan, prompt, target duration/format, timeout, output location, audio plan,
   and review gates. Record the renderer adapter, exact model/provider
   revision, and any spend authorization.
2. Each adapter receives a small native manifest. For example,
   `~/kk-video/kk_mac_video_batch.py` accepts serial `shots` with `id`,
   `image`, `prompt`, `frames`, `height`, `width`, `seed`, `steps`, and `fps`,
   and writes one MP4 per shot plus `batch-result.json`. The MPS panel runner
   additionally verifies its storyboard map and embeddings. Do not force
   provider-specific controls into fields an adapter cannot honor.
3. The local MLX and MPS adapters use verified local caches and produce silent
   video in the current KK-Mac lane; audio/mux is a separate, hash-recorded
   step. A hosted Veo adapter is a separate paid route: require explicit spend
   authorization and provider billing verification before submission. Never
   silently fall back from a local render to a paid provider.
4. Run one short proof cut first. Give every retry a new immutable version;
   do not overwrite output. A technical pass does not authorize the next cut:
   human review must accept the action, identity, continuity, and framing
   before extending or assembling a sequence. A creative rejection stops the
   chain; a corrected same-cut retry needs a concrete prompt/input change.
5. Independently verify output codec, dimensions, frame count, duration, full
   decode, black-frame result, audio presence, size, and SHA-256. Keep the
   technical report separate from the human creative-review result.
6. Use explicit lifecycle states: `staged`, `ready`, `admitted`,
   `rendering`, `produced`, `technical_pass`, `creative_review`,
   `accepted_private`, and `published`. “Prepared” or “embedding complete”
   never means a video exists.
7. Keep the source, immutable manifest, logs, output, QC report, and review
   decision in the private project artifact root. Verify the upload with
   `rclone check --one-way`; do not publish or deliver it to LINE without the
   applicable approval.

The 2026-11-04 dance-party pilot confirmed the MLX adapter produces a
73-frame, 640x384 silent proof in about 33 seconds on this host. Free memory
briefly fell during model load and recovered after each run; keep runtime
memory/swap under observation and stop the current render if pressure remains
critical. This is a measured pilot, not a duration guarantee.

### Current Sacred Father sequence

- The 25-frame page-9 MPS I2V probe passed: H.264 640x384, 1.04 s, full decode.
- `kk-mac-storyboard-i2v-fullshot01-20261030` passed at 73 frames/40 steps;
  the user then requested one additional test render, and shot02/page12 passed
  with the same settings. Both outputs remain private and need visual review.
- A user-requested one-off test may run before visual review, but do not stage
  or launch the remaining scene batch until shot01/shot02 are reviewed.
  After review, package shots 3-10 as bounded child units with the approved
  page/image/embedding map and a review gate. Keep MPS stages serial.
- Only after all mapped shots pass artifact verification should the held
  Colab V2 pack be resumed for cloned narration and assembly.
- The Colab V2 pack currently has an explicit resume prerequisite; do not
  remove that hold while Mac video work is in progress.
