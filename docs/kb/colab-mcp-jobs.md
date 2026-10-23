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
  to rclone for ~60s; poll before archiving.
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
  `{name, prep, run}` — `prep` is a shell string (fetch/install/extract),
  `run` is a Python source string exec'd in a shared namespace.
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
  {"name":"restore-hf-cache",
   "prep":"test -f /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
          " && mkdir -p /root/.cache/huggingface"
          " && tar -I zstd -xf /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
          "    -C /root/.cache/huggingface || true",
   "run":"import os;print('hub entries:',len(os.listdir('/root/.cache/huggingface/hub'))if os.path.exists('/root/.cache/huggingface/hub')else 0)"},
  # ... gpu jobs whose preps stay `snapshot_download` — they validate the
  # restored cache instantly instead of re-downloading ...
  {"name":"save-hf-cache",
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
