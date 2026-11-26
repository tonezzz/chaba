# Ansible-Centralized Job Dispatch System

Complete prototype: sidecar metrics → Redis → priority queue → scheduler → Ansible dispatch → monitoring.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Control Node (idc02)                                 │
│  ┌──────────┐   ┌──────────┐   ┌───────────────┐   ┌────────────────┐  │
│  │  Redis   │←──│ Sidecar  │   │ Priority Queue│←──│  Job Enqueue   │  │
│  │ (metrics)│   │ Metrics  │   │ (queue_mgr.py)│   │ (CLI/Playbook) │  │
│  └────┬─────┘   └────┬─────┘   └──────┬────────┘   └────────────────┘  │
│       │              │                │                                │
│       │         ┌────▼─────┐    ┌─────▼──────┐                         │
│       │         │ Sidecar  │    │ Scheduler  │ ← systemd user service  │
│       │         │ Deploy   │    │ Daemon     │   (polls every 5s)      │
│       │         └──────────┘    └─────┬──────┘                         │
│       │                               │                                │
│       └─────────────── ┌───────────────▼──────────────┐                 │
│                        │ Allocation (placement):       │                 │
│                        │ select host by tags/GPU/load  │                 │
│                        └───────────────┬──────────────┘                 │
│                                        │                                │
│                        ┌───────────────▼──────────────┐                 │
│                        │ dispatch_job.yml (Ansible)   │                 │
│                        │ → pull image, launch container│                 │
│                        └───────────────┬──────────────┘                 │
└──────────────────────────────────────────┼──────────────────────────────┘
                                           │
              ┌────────────┬───────────────┼───────────────┬────────────┐
              ▼            ▼               ▼               ▼            ▼
          ┌───────┐   ┌───────┐       ┌───────┐       ┌───────┐   ┌────────┐
          │ omen  │   │ dell  │       │ con01 │       │ idc02 │   │ idc03  │
          │ [gpu] │   │       │       │[server]│      │ [idc] │   │ [idc]  │
          └───────┘   └───────┘       └───────┘       └───────┘   └────────┘
                                                          ┌────────┐
                                                          │macbook │
                                                          │[laptop]│
                                                          └────────┘
```

## Components

| Component | File | Purpose |
|-----------|------|---------|
| Sidecar collector | `roles/sidecar/files/collector.py` | Push CPU/mem/disk/load/GPU metrics to Redis every 15s |
| Sidecar deploy | `playbooks/deploy_sidecar.yml` | Deploy collector to all 6 hosts |
| Lookup plugin | `plugins/lookup/sidecar_metrics.py` | Ansible lookup from Redis |
| Queue manager | `queue/queue_manager.py` | Priority queue, fair-share, retries, DLQ, CLI |
| Queue operations | `playbooks/queue_operations.yml` | Ansible-driven enqueue/stats/list/requeue/DLQ |
| Scheduler daemon | `queue/scheduler.py` | Dequeue → select host → dispatch → monitor → complete |
| Scheduler deploy | `playbooks/deploy_scheduler.yml` | Install scheduler as systemd user service |
| Dispatch playbook | `playbooks/dispatch_job.yml` | Eligibility checks + container launch |
| CLI wrapper | `scripts/dispatch_job.py` | Direct dispatch (bypasses queue) |

## Operating the System

### 1. Enqueue a job (CLI)
```bash
python3 queue/queue_manager.py enqueue \
  --redis 100.123.163.11 \
  --image alpine:latest \
  --cmd "echo hello" \
  --job-id my-job-001 \
  --gpus 0 --priority 0 \
  --require-tags server
```

### 2. Or via Ansible playbook
```bash
ansible-playbook -i inventory.ini playbooks/queue_operations.yml \
  -e operation=enqueue \
  -e job_spec_file=/home/tony/ansible/jobs/examples/train-llama.yaml
```

### 3. Scheduler processes it automatically
The scheduler daemon (running on idc02 as `dispatch-scheduler.service`):
1. Polls the queue every 5s
2. Selects the best host by tags, GPU, load, memory
3. Calls `dispatch_job.yml` targeting only that host
4. Monitors the container every tick
5. Marks complete on exit 0, requeues on failure

### 4. Monitor
```bash
# Queue stats
python3 queue/queue_manager.py stats --redis 100.123.163.11

# Scheduler logs
ssh tony@100.123.163.11 'journalctl --user -u dispatch-scheduler -f'

# Sidecar metrics
python3 -c "import redis,json; r=redis.Redis(host='100.123.163.11'); print(json.dumps({k:r.hgetall(k) for k in r.scan_iter('sidecar:*')}, indent=2))"
```

### 5. Manage jobs
```bash
# List all
python3 queue/queue_manager.py list --redis 100.123.163.11

# Requeue failed
python3 queue/queue_manager.py requeue JOB_ID --redis 100.123.163.11

# Dead letter queue
python3 queue/queue_manager.py dlq --redis 100.123.163.11
```

## Current Fleet Status (validated 2026-11-25)

| Host | Tailscale IP | Tags | Sidecar | Notes |
|------|-------------|------|---------|-------|
| omen | 100.75.102.88 | `gpu` | ✅ active | HP Omen, NVIDIA GPU detected |
| dell | 100.68.142.13 | — | ✅ active | Dell workstation |
| con01 | 100.72.146.39 | `server` | ✅ active | Server, passwordless sudo |
| idc02 | 100.123.163.11 | `idc` | ✅ active | **Control node + Redis + Scheduler** |
| idc03 | 100.102.134.91 | `idc` | ✅ active | IDC VM |
| macbook | 100.77.76.112 | `laptop` | ✅ active | No sudo; sidecar runs user-level |

## Configuration

### Per-host tags
Set in `host_vars/<host>.yml`:
```yaml
sidecar_tags: ["gpu", "highmem", "nvlink"]
```
Auto-detected tags: `gpu` (omen), `idc` (idc02/03), `server` (con01), `laptop` (macbook).

### Job spec parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `job_gpus` | 1 | GPUs required (0 = CPU only) |
| `job_min_vram_gb` | 8 | Min free VRAM per GPU |
| `job_max_load_pct` | 70 | Max CPU load % of cores |
| `job_max_mem_pct` | 80 | Max memory % |
| `job_require_tags` | [] | Required host tags (all must match) |
| `job_exclude_tags` | [] | Excluded host tags (none may match) |
| `target_group` | all | Ansible group or specific hostname |
| `priority` | 5 | 0=highest, 9=lowest |
| `max_retries` | 2 | Retries before DLQ |
| `reserve_gpu_window_sec` | 0 | >0 = exclusive GPU hold for N sec (see GPU-JOBS.md §reservations) |
| `reservation_id` | "" | Optional reservation ID (default `rsv-<job_id>`) |

## GPU Jobs

See **[GPU-JOBS.md](GPU-JOBS.md)** for the full guide. Quick summary:

- **omen** has a GTX 1650 (4GB), shared with a persistent service (~2.2GB) → ~1.8GB free for jobs
- GPU jobs use `job_require_tags: ["gpu"]` and `job_gpus: 1`
- **Backpressure**: if insufficient VRAM, the job stays queued with **no retry penalty** until resources free up
- Check availability: `python3 scripts/gpu_status.py`

Examples:
- `jobs/examples/gpu-cuda-bench.yaml` — ~1GB, validates GPU dispatch
- `jobs/examples/gpu-torch-inference.yaml` — ResNet-18, ~1.2GB
- `jobs/examples/gpu-embedding-batch.yaml` — ~1.5GB, demonstrates queue wait
- `jobs/examples/train-llama.yaml` — aspirational (needs future multi-GPU host)

## Testing
```bash
# Full validation (check mode, no changes)
ansible-playbook --check -i inventory.ini playbooks/deploy_sidecar.yml
ansible-playbook --check -i inventory.ini playbooks/deploy_scheduler.yml

# Dry-run dispatch
python3 scripts/dispatch_job.py --job-id test --image alpine:latest \
  --cmd "echo test" --gpus 0 --dry-run

# Scheduler single tick (dry-run)
python3 queue/scheduler.py --once --dry-run
```

## Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| Sidecar not reporting | `journalctl --user -u sidecar-collector` | Verify venv has redis-py; check `SIDECAR_REDIS_HOST` |
| No eligible hosts | `python3 -c "import redis; r=redis.Redis(host='100.123.163.11'); print(r.hgetall('sidecar:omen'))"` | Check tags, load, memory in metrics |
| Job stuck in queue | `journalctl --user -u dispatch-scheduler -f` | Check fair-share limits, queue stats |
| Scheduler not running | `systemctl --user status dispatch-scheduler` | `systemctl --user restart dispatch-scheduler` |
