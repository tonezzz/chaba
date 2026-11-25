# gpu-dispatch-webui

Single-pane web UI over the Ansible dispatch queue and fleet GPU state.
Card: `gpu-dispatch-web-ui` (OPS-1409).

## Hosting decision (card scope item 1)

**Chosen: a small self-contained service on idc02** (`/home/tony/ansible/webui/`,
systemd *user* unit `gpu-dispatch-webui.service`, tailnet-IP bind
`100.123.163.11:8795`).

Why not the chaba board/apps stack:

- The data plane is local to idc02: Redis (`:6379`), `queue/queue_manager.py`,
  `queue/scheduler.py`, and the `dispatch-scheduler.service` user unit all
  live in `/home/tony/ansible` on idc02. A UI hosted anywhere else still
  needs an API next to Redis — the apps stack only serves static files.
- The card requires mutating controls to "reuse queue_manager APIs rather
  than direct Redis writes". `QueueManager` is importable Python; the
  service imports it directly (`ANSIBLE_DIR/queue` on `sys.path`). A
  chaba-side or board-api endpoint would have to shell out to the CLI or
  re-implement queue semantics — both worse.
- Tailnet-IP bind matches existing idc02 precedent (`gpu-queue` :3001,
  `secrets-console` :8005, `weaviate` :8084): no credentials in code, the
  tailnet is the trust boundary. No caddy/routes.yml change needed, so the
  service deploys without touching the generated edge config.
- CLI stays authoritative: every mutation goes through `QueueManager`
  methods (`enqueue`, `cancel_job`, `requeue`), and `queue_manager.py`
  gained a `cancel` subcommand for parity (see
  `queue_manager-cancel.patch` — the ansible checkout is not a real git
  remote, so the patch is the reviewable record of that change).

If the pane later deserves a place in `/apps/`, a follow-up card can add a
static shell under `stacks/web/public/apps/` that iframes or reverse-proxies
`http://idc02.taila0626a.ts.net:8795/` via `ssot.routes.yml`.

## What it shows (read-only first)

`GET /api/state` (polled every 5 s by the UI):

- queue stats (`queue:jobs:*` lengths, job status histogram, DLQ,
  fair-share) — via `QueueManager.get_queue_stats()`
- every `queue:job:*` hash parsed to JSON (status, priority, user, image,
  cmd, GPU reqs, tags, retries, reservation fields) + merged `dispatch:*`
  record (host, container_id, exit result)
- fleet GPU table from `sidecar:*` hashes — per-GPU VRAM/util/temp plus
  host CPU/mem/load/disk, tags, and sidecar freshness (`stale` > 45 s)
- active `gpu:hold:*` reservations annotated onto the GPU rows
- scheduler health: `systemctl --user is-active` for
  `dispatch-scheduler` and `sidecar-collector` (pid, since, restarts)

## Mutations (confirm + audit)

`POST` endpoints require `{"confirm": true}` in the JSON body; the UI adds
it only after a `window.confirm()` dialog. Every attempt (success or
failure) is appended to `audit.jsonl` next to the service **and** mirrored
to the Redis list `queue:audit` (LPUSH + LTRIM 1000).

| Endpoint | QueueManager call | Notes |
|---|---|---|
| `POST /api/jobs` | `enqueue(JobSpec)` | full job-field validation; `job_id` charset-restricted |
| `POST /api/jobs/<id>/cancel` | `cancel_job(id, actor)` | queued/waiting only; atomic Lua check-and-remove; releases GPU holds; 409 for processing/terminal |
| `POST /api/jobs/<id>/requeue` | `requeue(id, increment_retry=False)` | failed/dead_letter/cancelled/completed only; 409 if still queued/waiting/processing (no duplicate queue entries) |

Actor identity is a free-text field (top-nav input, persisted in
localStorage) recorded in the audit trail — there is no auth, matching the
tailnet-only posture of neighboring services.

## Files

- `gpu_dispatch_webui.py` — stdlib `http.server` service (no deps beyond
  redis-py from `~/.local/venv-sidecar`)
- `static/` — single-page UI (vanilla JS/CSS, gpu-monitor palette)
- `gpu-dispatch-webui.service` — systemd user unit
- `install.sh [host]` — deploy to `idc02` (default): copies to
  `/home/tony/ansible/webui/`, installs the unit, enables + health-checks
- `queue_manager-cancel.patch` — the `cancel_job()`/`cancel` CLI addition
  applied to `/home/tony/ansible/queue/queue_manager.py` on idc02
- `audit.jsonl` — created at runtime on the host (not in git)

## Ops

```bash
# status / logs
ssh idc02 'systemctl --user status gpu-dispatch-webui'
ssh idc02 'journalctl --user -u gpu-dispatch-webui -f'

# UI
http://idc02.taila0626a.ts.net:8795/        # tailnet only

# audit trail
ssh idc02 'tail -f /home/tony/ansible/webui/audit.jsonl'
ssh idc02 'redis-cli -h 100.123.163.11 lrange queue:audit 0 20'

# CLI fallback (unchanged, authoritative)
ssh idc02 'cd /home/tony/ansible && python3 queue/queue_manager.py stats --redis 100.123.163.11'
ssh idc02 'cd /home/tony/ansible && python3 queue/queue_manager.py cancel <job_id> --actor tony'
```

## Known limits

- Cancel only works pre-dispatch. A `processing` job owns a container on a
  remote host — the UI refuses and points at the CLI/host runtime.
- Requeue of a `dead_letter` job leaves its id in `queue:dlq` — same
  semantics as the existing CLI `requeue` (the DLQ list is a history log,
  job `status` is the live truth).
- Mutations are tailnet-trust only; there is intentionally no auth token.
  If the pane is ever exposed beyond tailnet, add auth first.
