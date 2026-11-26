# Dispatch outcome — dispatch-queue-approval-gate (OPS-1411 follow-up)

## What was done

Implemented the RBAC-lite approval gate spec'd by the AWX do-not-adopt
decision (`awx-aap-rbac-approval-gates`, decision record
`docs/ssot/jobs/infrastructure/2026-11-25-awx-aap-rbac-approval-gates-decision.yml`)
directly on the target repo `/home/tony/ansible` **on idc02**.

Constraint hit: idc02's sshd is **sftp-only** (no exec). All work was done
against an sftp snapshot in `.scratch/ansible-idc02`, tested locally against
the live Redis (`uv run --with redis`, since this host has no pip/redis lib),
and uploaded via sftp; all 5 files re-downloaded and `cmp`-verified
byte-identical.

### Changes (live on idc02)

- `queue/queue_manager.py` — JobSpec gained `status`/`approval_state`/
  `approved_by`/`approved_at`/`approval_reason`; `enqueue()` resolves user
  from `SUDO_USER`/`getpass.getuser()` (CLI `--user` mismatch → rc=2 unless
  `--as-user`); gated jobs go to `queue:pending:{priority}` with
  `status=awaiting_approval`, LPUSH to `queue:jobs:{priority}` only on
  approve; new `approve`/`reject`/`pending` subcommands (Lua-atomic decide,
  approver + self_approve policy checks); `expire_pending_approvals()`;
  `cancel_job` handles pending jobs; `list_jobs` status filter fixed (was
  reading `metadata.status`, never set); stats count pending/new statuses;
  policy loaded from `approval_policy.yml` with a no-PyYAML fallback parser.
- `queue/scheduler.py` — `_tick()` runs the approval-expiry sweep (pending
  > `ttl_sec`=24h → `approval_state=expired` + `queue:events`). No dequeue
  change, as designed.
- `approval_policy.yml` — NEW at repo root: enabled, ttl 24h,
  self_approve=true, approvers=[tony], require when `job_gpus>0 OR
  priority<=2 OR 'gpu' in require_tags`.
- `playbooks/queue_operations.yml` — `operation=approve/reject/pending`
  mapped to the CLI (syntax-check PASS).
- `queue/test_gpu_reservations.py` — approves its gated jobs; db-15 suite
  all-PASS.

## Verification (live queue, real scheduler)

- gpu/priority enqueue → `awaiting approval`, `queue:jobs` stayed empty,
  `pending` listed both test jobs.
- `approve` → LPUSH `queue:jobs:1` → **live scheduler claimed it ~5s later**
  (zero scheduler diff, as designed).
- `reject` → `status=rejected`, visible via `list --status rejected`, never
  dispatched.
- End-to-end container proof: `approval-gate-test-005` (gated via 'gpu'
  tag) → approved → dispatched to omen → **completed** 12:56.
- Expiry/bad-approver/double-decide verified on isolated db 15.

## Findings

- **OPS-1437 filed** (high): all gpus=0 dispatches fail on con01/idc02/
  idc03 — podman 4.9.3 conmon rejects `--log-tag`
  (`k8s-file doesn't support --log-tag`). Reproduced by running
  dispatch_job.yml from this host. Only omen+dell (podman 5.7.0) can run
  containers; macbook has no podman. Placement doesn't check runtime
  capability → CPU jobs DLQ. Pre-existing, unrelated to the gate.
- **Service restart needed on idc02**: running `dispatch-scheduler.service`
  and `gpu-dispatch-webui` still hold the OLD queue_manager — expiry sweep
  and webui-side gating start only after `systemctl --user restart
  dispatch-scheduler` (and the webui unit). Could not restart: no exec on
  idc02.
- **git init + remote NOT done** (card asked for it): impossible without
  exec on idc02. Reviewable diff is at
  `docs/ssot/jobs/infrastructure/2026-11-26-dispatch-queue-approval-gate.patch`;
  job record at `docs/ssot/jobs/infrastructure/2026-11-26-dispatch-queue-approval-gate.yml`.
  Operator runbook: `cd /home/tony/ansible && git init && git add -A &&
  git commit` then add a remote — or apply the patch onto a fresh clone.
- Webui has no approve/reject buttons yet — UI-submitted gated jobs wait in
  `pending` until CLI/playbook approval on idc02 (by design for RBAC-lite).

## Test artifacts left in queue (audit trail)

`approval-gate-test-001/003/004` dead_letter (dispatch infra bug above),
`approval-gate-test-002` rejected, `approval-gate-test-005` completed,
`cli-asuser-test` dead_letter — all `tony`/`webui-test` users, harmless
alpine echo jobs.

lessons:
- idc02 ssh is sftp-only: file work is possible via `sftp get/put -r`, but no git/python/systemctl — verify by re-downloading and `cmp`, and leave restart/git steps as documented follow-ups.
- No pip on tony-macbook python3.14: `uv run --with redis python3 ...` gives a redis-capable interpreter for testing queue_manager against live Redis.
- dispatch_job.yml fails on podman 4.9.3 hosts (conmon `--log-tag`) — only podman 5.7 hosts (omen, dell) can run containers; check `podman --version` on the target before trusting a dispatch result.
- scheduler._select_target_host picks by load/tags only — a CPU job can land on a host with no podman or an too-old conmon; placement needs a runtime-capability signal (OPS-1437).
