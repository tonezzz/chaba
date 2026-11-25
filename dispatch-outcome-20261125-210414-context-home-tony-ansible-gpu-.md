# dispatch-outcome — gpu-dispatch-web-ui (OPS-1409)

## What was built

A single-pane web UI over the Ansible GPU dispatch queue, deployed and
verified live on idc02:

- **Service**: `gpu-dispatch-webui.service` (systemd --user on idc02),
  stdlib `http.server` + redis-py from `~/.local/venv-sidecar`, bound to
  tailnet IP `100.123.163.11:8795` →
  **http://idc02.taila0626a.ts.net:8795/**
- **Code on host**: `/home/tony/ansible/webui/` (server + static/ +
  audit.jsonl at runtime)
- **Source in repo**: `stacks/services/gpu-dispatch-webui/` — server,
  static UI (gpu-monitor palette), systemd unit, `install.sh`, README,
  and `queue_manager-cancel.patch`
- **queue_manager.py change** (idc02, untracked checkout): added
  `QueueManager.cancel_job()` — atomic Lua check-and-cancel for
  queued/waiting jobs (LREM + status=cancelled + release holds + event) —
  plus a `cancel` CLI subcommand. Patch file is the reviewable record.

## Hosting decision (scope item 1)

Small service on idc02, documented in the service README and
`docs/ssot/jobs/infrastructure/2026-11-25-gpu-dispatch-webui.yml`.
Rationale: Redis/queue_manager/scheduler all live on idc02; the card
requires reusing queue_manager APIs; tailnet-IP bind matches
gpu-queue/secrets-console precedent (no creds, no caddy/routes change).

## Verified live (scope item 4)

- `/api/state` shows live queue stats, all `queue:job:*` + `dispatch:*`,
  6-host sidecar fleet table (omen GTX 1650), `gpu:hold:*` reservations,
  and scheduler/sidecar unit health — matches CLI output.
- Enqueued `webui-test-001` via `POST /api/jobs` (confirm:true) — stayed
  queued (impossible require-tag → scheduler backpressure, no dispatch).
- Cancelled via `POST /api/jobs/<id>/cancel` → `ok`, queue returned to
  baseline (queued 0 / processing 0 / completed 3 / failed 1 / dlq 0).
- Requeue path verified (cancelled → waiting → cancelled again).
- Guards verified: no `confirm` → 400; cancel completed job → 409;
  requeue refuses queued/waiting/processing.
- Audit: every mutation appended to `audit.jsonl` AND Redis `queue:audit`
  (actor, action, job_id, params, result).

## Notes / limits

- Cancel is pre-dispatch only; `processing` jobs are refused (container
  lifecycle belongs to host runtime — CLI stays authoritative).
- No auth — tailnet is the trust boundary, same as neighboring services.
- The ansible checkout on idc02 is untracked (no remote); the queue_manager
  diff is preserved as `queue_manager-cancel.patch`. A sibling dispatch
  (gpu-timeslot-reservations) edited the same files concurrently — my
  change is additive and verified post-deploy.

## How to verify

```
ssh idc02 'systemctl --user status gpu-dispatch-webui'
open http://idc02.taila0626a.ts.net:8795/
ssh idc02 'cd /home/tony/ansible && python3 queue/queue_manager.py stats --redis 100.123.163.11'
```

lessons:
- /home/tony/ansible on idc02 is a git repo with history but ALL working files untracked and no remote — snapshot with tar before editing; keep a .patch of any change in the chaba repo.
- queue_manager.py list_jobs() status filter is broken (filters job.metadata.status which JobSpec drops) — read the raw hash `status` field instead.
- Scheduler backpressure (requeue reset_status=False → status=waiting) is the safe way to keep a test job queued without dispatch: use a require-tag no host has.
- dispatch-scheduler runs as a systemd --user unit on idc02 via ~/.local/venv-sidecar — reuse that venv (redis-py present, no flask) for sibling services.
- idc02 caddy-edge Caddyfile is GENERATED from docs/ssot/infrastructure/ssot.routes.yml — prefer tailnet-IP bind for new idc02 services over editing it.
