# Ansible × Kanban — Phase 0 map (2026-11-25)

Tracking card: **KNB-1353** (`ansible-kanban-phase-0-map-phase-1-read-4e0267`, doing).  
Scope: Tony-approved option **A** — Phase 0 map + Phase 1 read-only pilots (audit-to-card, stale-checkout diagnosis, verify-evidence helper). No host mutations.

## 1. Current Ansible surface (chaba/ansible, 19 playbooks)

| Playbook | Mode | Primary output | Kanban fit |
|---|---|---|---|
| `ada-ocb-audit.yml` | read-only | `reports/ada-ocb/` | Good: card on drift/recovery |
| `ada-ocb-upgrade.yml` | **gated write** (`ocb_change_approved`) | service upgrade + verify | Good: card-driven runbook, already gated |
| `ada-ocb-verify.yml` | read-only gate | pass/fail | Good: closeout evidence |
| `audit-fleet-services.yml` | read-only | `reports/ansible-benchmark/services/` | Good: drift cards / summary |
| `audit-log-shipper.yml` | read-only | `reports/ansible-benchmark/log-shipper/` | Good: stale/failing shipper card |
| `audit-mcp-verify.yml` | read-only | `reports/ansible-benchmark/mcp/` | Good: MCP drift card |
| `audit-runner-tools.yml` | read-only; opt-in sync | stdout; optional copy | **Pilot A target**: drift -> board-api |
| `audit-worktrees.yml` | read-only | `reports/ansible-benchmark/worktrees/` | Good: stale worktree/exec checkout diagnosis |
| `disk-headroom.yml` | read-only + trend feed | reports + disk-trend jsonl | Good: already near kanban; add deduped card |
| `log-shipper.yml` | converge | installs/enables units | Gated: only with approval/evidence |
| `session-capture.yml` | converge (draft) | helper/timer wiring | Gated/targeted |
| `site.yml` | baseline converge | packages/unattended-upgrades | Gated/scheduled, low risk but still host write |
| `ssh-bootstrap.yml` | controller write | known_hosts | Low kanban value; controller-local |
| `ssh-config-generate.yml` | controller write | `~/.ssh/config` block | Low kanban value |
| `ssh-config-render.yml` | read-only | rendered block hash | Audit evidence only |
| `ssh-mesh-verify.yml` | read-only gate | pass/fail | Good: card on access drift |
| `verify-ada-stagger.yml` | read-only | `reports/ansible-benchmark/stagger/` | Niche, card on drift |
| `verify-host-software.yml` | read-only | `reports/ansible-benchmark/host-software/` | Good: host capability cards (R7) |
| `verify-runner-tools-sync.yml` | read-only dry-run | rsync drift preview | Good: pilot A alternative / complement |

## 2. Kanban/board-api contract (must hold)

- **Write door:** board-api only (`POST /card`, `/comment`, `/request`, `/action`, `/attach`). No direct edits to `docs/ssot/kanban/cards/*.yml` from Ansible.
- **Idempotency:** stable card ids per issue class (`ansible-<check>-<scope>`). `POST /card` may return 400 `already exists`; treat as non-fatal and comment instead.
- **Noise control:** comment only on state change or include fingerprint/summary; avoid per-run spam. Pilots start simple; refine with state-change detection.
- **Evidence:** include report path, host, reason, key command output summary. Attach logs via `/attach` when useful.
- **Secrets:** never send secret values; `no_log: true` for sensitive tasks. Use permission/metadata checks only.
- **Gates:** read-only default. Any host-changing remediation needs explicit approval var, rollback before write, producer+consumer verify, then card evidence.

## 3. Phase 1 pilots delivered (this branch)

| Pilot | Artifact | Behavior | Safety |
|---|---|---|---|
| A. Audit-to-card | `ansible/playbooks/audit-runner-tools.yml` (new optional `board_notify` controller play) | On drift, creates/updates `ansible-runner-tools-drift` via board-api with summary | Read-only; no host writes; notify off by default |
| B. Stale-checkout diagnosis | `ansible/playbooks/audit-stale-checkouts.yml` | Probes behind/ahead/dirty/lock/rebase/in-progress; writes per-host reports; optionally creates/comments `ansible-stale-checkouts` decision card | Read-only; no stash/reset/pull; notify off by default |
| C. Verify-evidence helper | `ansible/playbooks/tasks/board-api-card-notify.yml`, `board-api-comment.yml` | Reusable board-api task includes for idempotent create-or-comment and comment-only | No direct YAML writes; caller controls noise |

## 4. Gap map (next candidates)

| Gap | Candidate | Priority | Gate |
|---|---|---|---|
| Runner drift notifies but no state-change dedupe | add fingerprint/hash in comment text; skip if unchanged | High | read-only |
| Stale checkout diagnosis has no per-host request options | `POST /request` per host/card with stash-u-ff/commit-wip/leave/abandon | High | read-only; human decision |
| audit-fleet-services has no kanban output | add optional board-api summary card on delta>0 | High | read-only |
| disk-headroom has trend feed but no card lifecycle | create/comment card on CRIT/WARN, auto-close comment on recovery | Med | read-only |
| verify-host-software / ssh-mesh-verify no card output | optional board-api notify | Med | read-only |
| audit-worktrees overlaps stale-checkout diagnosis | merge or keep scoped; avoid duplicate cards | Med | design |
| Remediation playbooks not card-driven | card spec -> approved playbook id + vars schema | Med | Phase 2 gated |
| No scheduled state-change sweep | controller timer/timer+script; only on transitions | Med | noise control |

## 5. Verification plan

```bash
cd ansible
# Syntax/lint (controller has ansible tooling)
ansible-playbook --syntax-check playbooks/audit-stale-checkouts.yml
ansible-playbook --syntax-check playbooks/audit-runner-tools.yml

# Read-only dry behavior / preview (no board notify)
ansible-playbook playbooks/audit-stale-checkouts.yml --check --diff --limit localhost
ansible-playbook playbooks/audit-runner-tools.yml --limit localhost

# Board notify is opt-in; test against board-api only with explicit intent:
# ansible-playbook playbooks/audit-stale-checkouts.yml -e board_notify=true -e board_api_base=http://127.0.0.1:8787 --limit idc02
```

## 6. Risks / follow-ups

- `git fetch -q origin` in stale-checkout probe touches remote refs under `.git` (not worktree files); acceptable for diagnosis, but document it.
- Per-run comments can be noisy; add fingerprint/dedupe before scheduling.
- `ansible_env.HOME` is unavailable with `gather_facts: false`; playbooks should use `/home/{{ ansible_user }}` or explicit probe.
- The helper task uses `run_once` configurable; per-host cards must set `board_run_once=false` and host-specific card ids.
- Before any Phase 2 remediation, require explicit same-session approval, rollback text, and post-verify evidence.