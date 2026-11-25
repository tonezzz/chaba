# Dispatch outcome — awx-aap-rbac-approval-gates

## What was done

Surveyed the dispatch system and the fleet, then wrote a decision record.
The actual queue lives at `/home/tony/ansible` **on idc02** (not on this
host); all inspection was read-only over SSH.

### Findings

- **System state**: `queue/queue_manager.py` (Redis priority queue,
  fair-share, DLQ), `queue/scheduler.py` (running as
  `dispatch-scheduler.service`, active since 2026-11-25 20:56 +07),
  `playbooks/dispatch_job.yml`, `playbooks/queue_operations.yml`,
  `scripts/dispatch_job.py`. All untracked in git; the repo has **no
  remote**. Live queue currently holds 4 `gpu-rsv*` test jobs.
- **RBAC gap confirmed**: `--user`/`--project` are free-text CLI args;
  Redis on `100.123.163.11:6379` has no auth and is Tailscale-reachable,
  so any fleet host can enqueue as any user. No approval step exists.
- **AWX/AAP survey**: zero AWX/Tower/AAP anywhere — checked docker, podman,
  and all systemd units on idc02, idc03, con01, mn01, tony-dell, tony-omen
  for `awx|tower|ansible` patterns (no hits), and no awx secrets in
  `~/.config/secrets/` on idc02. kk-mac unchecked (offline).

### Decision (recorded in the deliverable)

**Do not adopt AWX now.** No deployment exists; standing one up is a
multi-container PostgreSQL-backed install for a single-operator
prototype, and AWX cannot natively gate a third-party Redis queue — the
enforcement code must be written regardless. Recommended instead: an
~80-line in-queue approval gate (Redis `approval_state` fields, pending
jobs held in `queue:pending:{priority}` until `approve`, scheduler
unchanged — zero scheduler diff). Full semantics, the hypothetical
AWX org/team/template mapping, and revisit criteria are in the record.

## Deliverables

- `docs/ssot/jobs/infrastructure/2026-11-25-awx-aap-rbac-approval-gates-decision.yml`
  — survey, mapping, approval semantics, decision, verification commands.
- Follow-up implementation card filed via board-api:
  **OPS-1411 `dispatch-queue-approval-gate`** (backlog) with the full
  patch spec — implementation is out of scope here because
  `/home/tony/ansible` is outside this worktree and untracked.
- Card comms posted on `awx-aap-rbac-approval-gates`.

## How to verify

- Read the decision record YAML above.
- `ssh idc02 'systemctl --user status dispatch-scheduler'` → active.
- `ssh idc02 'cd /home/tony/ansible && git status -sb'` → queue files
  untracked, no remote (confirms prototype state).
- Fleet AWX absence: `docker ps`/`podman ps`/`systemctl list-units` on the
  six surveyed hosts show no awx/tower units or containers.

lessons:
- The card's context path `/home/tony/ansible` does not exist on the
  claiming host (tony-macbook); the real system lives on idc02 — always
  resolve context paths against the fleet, not the local checkout.
- `/home/tony/ansible` on idc02 is an untracked prototype with no git
  remote; any code change there needs `git init` + remote before review.
- AWX cannot gate an external Redis queue natively — adopting it would
  still require custom approval plumbing; evaluate the enforcement point
  before the UI.
