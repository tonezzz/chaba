# GPU Job Dispatch Guide

## Current GPU Capacity

| Host | GPU | VRAM | Persistent Usage | Free for Jobs | Tags |
|------|-----|------|-----------------|---------------|------|
| **omen** | NVIDIA GeForce GTX 1650 | 4096 MB | ~2238 MB (bge-rerank-server) | ~1800 MB (after transient jobs finish) | `gpu` |

No other hosts have GPUs. The GPU is shared between a persistent embedding service and transient inference jobs.

**Implication**: GPU jobs must be small (≤2GB VRAM) or wait in the queue for VRAM to free up.

## Quick Start

### 1. Check GPU availability
```bash
python3 /home/tony/ansible/scripts/gpu_status.py
```

Output example:
```
Fleet GPU Status — 2026-11-25 18:50:00
==============================================================================
HOST         GPU                        VRAM TOTAL   VRAM USED   VRAM FREE   UTIL  TAGS
------------------------------------------------------------------------------
omen         NVIDIA GeForce GTX 1650        4096MB      3674MB        42MB     1% gpu
dell         (no GPU)                           -           -           -      -
...
GPU hosts: 1 | Total free VRAM: 42 MB (0.0 GB)

GPU job sizing guidance:
  1GB job: WAIT (insufficient free VRAM)
  2GB job: WAIT (insufficient free VRAM)
  ...
```

### 2. Enqueue a GPU job
```bash
cd /home/tony/ansible

python3 queue/queue_manager.py enqueue \
  --redis 100.123.163.11 \
  --image docker.io/nvidia/cuda:12.2.0-base-ubuntu22.04 \
  --cmd "nvidia-smi" \
  --job-id gpu-test-001 \
  --gpus 1 --min-vram 1 \
  --require-tags gpu \
  --priority 0
```

The job stays queued until omen has ≥1GB free VRAM. The scheduler checks every 5s.

### 3. Monitor
```bash
# Queue status
python3 queue/queue_manager.py stats --redis 100.123.163.11

# Scheduler decisions
ssh tony@100.123.163.11 'journalctl --user -u dispatch-scheduler -f'

# GPU status
python3 scripts/gpu_status.py
```

## Job Examples

### `jobs/examples/gpu-cuda-bench.yaml`
- **VRAM**: ~1GB (CUDA context + numpy matmul)
- **Runtime**: ~2 min (includes apt install)
- **Use**: Validate GPU dispatch end-to-end

### `jobs/examples/gpu-torch-inference.yaml`
- **VRAM**: ~1.2GB (ResNet-18, batch 8)
- **Runtime**: ~5 min (image pull + inference)
- **Use**: Real GPU compute workload

### `jobs/examples/gpu-embedding-batch.yaml`
- **VRAM**: ~1.5GB
- **Runtime**: 30s (placeholder)
- **Use**: Demonstrates queue backpressure — waits for VRAM

## VRAM Sizing Guide (GTX 1650, 4GB)

| Workload | Typical VRAM | Fits alongside bge-rerank? | Notes |
|----------|-------------|---------------------------|-------|
| CUDA hello-world | ~300 MB | ✅ Always | Minimal context |
| Small CNN inference (ResNet-18) | ~1.2 GB | ✅ When transient jobs done | Batch ≤8 |
| Sentence-transformers (all-MiniLM) | ~500 MB | ✅ Usually | CPU fallback available |
| BERT-base inference | ~1.5 GB | ⚠️ Tight | Batch 1-4 |
| LLM inference (7B, FP16) | ~14 GB | ❌ Never | Needs bigger GPU |
| Stable Diffusion (512px) | ~2.5 GB | ❌ When bge-rerank active | Wait for service restart |
| LLM fine-tuning | 8+ GB | ❌ Never | Not possible on this GPU |

## How GPU Placement Works

The scheduler's `_select_target_host()` (in `queue/scheduler.py`) does:

1. **Tag filter**: Host must have all `job_require_tags` (e.g., `gpu`)
2. **GPU count**: `gpu_count >= job_gpus`
3. **VRAM check**: Count GPUs with `mem_free_mb > job_min_vram_gb * 1024`
4. **Load check**: `load1 < cpu_count * job_max_load_pct / 100` (raw load average; values **>100% allow deliberate CPU oversubscription**)
5. **Memory check**: `mem_pct < job_max_mem_pct`
6. **Score & select**: Lowest load, most free VRAM wins

If no host qualifies, the job **stays in the queue** — this is intentional backpressure.

## Handling the Persistent GPU Service

The `bge-rerank-server.py` uses ~2.2GB permanently. Options:

### Option A: Work within the constraint
Set `job_min_vram_gb: 1` or `2` and wait for transient jobs to finish.

### Option B: Stop the service temporarily
```bash
ssh tony@100.75.102.88 'systemctl --user stop bge-rerank.service'
# ~2.2GB more free; run GPU jobs; then restore:
ssh tony@100.75.102.88 'systemctl --user start bge-rerank.service'
```

### Option C: GPU time-slot reservations (exclusive windows)

Jobs can request an **exclusive GPU window**: while the reservation is
active, the held GPU indices are invisible to *all* GPU placement — other
reservation jobs and normal VRAM-fit jobs alike wait. This prevents the
"two jobs qualify against the same free VRAM and OOM/thrash" failure.

```bash
python3 queue/queue_manager.py enqueue \
  --redis 100.123.163.11 \
  --image docker.io/nvidia/cuda:12.2.0-base-ubuntu22.04 \
  --cmd "nvidia-smi dmon -s pucm -d 5 -c 120" \
  --job-id gpu-exclusive-001 \
  --gpus 1 --min-vram 1 --require-tags gpu \
  --max-load 1000 --max-mem 95 \
  --reserve-window 600 \
  --priority 0
```

| Field | Meaning |
|-------|---------|
| `--reserve-window SEC` / `reserve_gpu_window_sec` | Exclusive hold duration. The scheduler creates the hold atomically at dispatch; it is released early on complete/fail/timeout/requeue, and auto-expires via Redis TTL if the scheduler dies. **Set it ≥ expected job runtime** — a job that outlives its window loses exclusivity. `0` (default) = no reservation, current shared-VRAM behavior. |
| `--reservation-id ID` / `reservation_id` | Optional stable ID (default `rsv-<job_id>`). Reused across retries so the audit trail stays continuous. |

How it works:

- Ledger: `gpu:hold:{host}:{gpu_index}` keys in Redis with TTL = window.
- Placement (`scheduler.py::_select_target_host`) counts only unheld,
  VRAM-eligible GPUs — a fully-held host is skipped like any other
  resource-unavailable host (job waits, **no retry penalty**).
- Dispatch acquires the hold in one Lua script (first N free indices) —
  concurrent dispatches cannot double-book.
- `dispatch_job.yml` receives the held indices (`gpu_device_indices`) and
  pins Podman CDI to exactly those GPUs; for non-reservation jobs it
  excludes held indices itself. Docker cannot pin indices, so a docker GPU
  job fails fast if foreign holds exist on the host — use `podman`.
- Release is automatic on complete/fail/timeout/requeue/DLQ, and manual:
  `python3 queue/queue_manager.py release <job_id>`.

Inspect reservations:

```bash
python3 queue/queue_manager.py reservations --redis 100.123.163.11   # all holds
python3 queue/queue_manager.py holds --host omen --redis 100.123.163.11  # JSON per host
python3 scripts/gpu_status.py                                        # HOLD column + detail
python3 queue/queue_manager.py stats --redis 100.123.163.11          # reservations[] in stats
```

Caveats:

- Holds only constrain **queue-scheduled** jobs. `bge-rerank.service` and
  other non-queue GPU consumers are invisible to the ledger — check
  `gpu_status.py` and size `job_min_vram_gb` accordingly (or stop the
  service for the window, then restore it).
- Direct `scripts/dispatch_job.py` / playbook runs bypass the queue but the
  playbook still refuses to launch onto GPUs held by *other* reservations.
- Running non-reservation jobs are not preempted — a reservation guarantees
  no *new* placements during the window, not eviction.
- `job_cmd` is **argv-split on whitespace** by `containers.podman` — there is
  no shell, so quotes, `&&`, `;`, pipes and redirects do not work (a
  `bash -c "..."` cmd arrives with literal quotes and exits 2). Use flat
  commands (`nvidia-smi dmon -s pucm -d 5 -c 120` for a timed GPU run) or
  bake compound logic into the job image.

## Tips

- **Set `job_max_load_pct: 1000` for GPU jobs on omen** — `load1` is a raw load average (18–70 on 12 CPUs); 100% of 12 cores = 12, so even 95% rejects every job. >100% means intentional CPU oversubscription; the GPU is the resource being scheduled.
- **Use fully-qualified image names** — Podman on omen has no unqualified-search registry; use `docker.io/nvidia/cuda:...`, not `nvidia/cuda:...`.
- **Podman GPU IDs, not counts** — the playbook selects free GPU indices from sidecar facts and passes them as `--gpus` (e.g. `0`). Docker jobs use `device_requests` with a count instead.
- **Use `--priority 0` for urgent GPU jobs** — jumps ahead of lower-priority work.
- **Check `gpu_status.py` before enqueueing** — avoids confusion when jobs sit in queue.
- **Monitor scheduler logs** — shows exactly why a job wasn't placed.
- **CDI must match the driver** — if launch fails with `cannot stat .../libEGL_nvidia.so.<old>`, regenerate: `ansible omen -i inventory.ini -b -m command -a 'nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml'`.

## Example: Full GPU Job Lifecycle

```bash
# 1. Enqueue
python3 queue/queue_manager.py enqueue \
  --redis 100.123.163.11 \
  --image docker.io/nvidia/cuda:12.2.0-base-ubuntu22.04 \
  --cmd "nvidia-smi -L" \
  --job-id gpu-hello-001 \
  --gpus 1 --min-vram 1 --require-tags gpu \
  --max-load 1000 --max-mem 95 \
  --priority 0

# 2. Watch scheduler decide
ssh tony@100.123.163.11 'journalctl --user -u dispatch-scheduler -f'
# You'll see: "No eligible hosts for gpu-hello-001" until VRAM frees up
# Then: "Selected host omen (score=...)"

# 3. Verify completion
python3 queue/queue_manager.py list --redis 100.123.163.11
```