---
name: ansible-first
description: Before any host, service, container, fleet, deploy, restart, provision or repeatable-configuration task — even when a job merely mentions a hostname, playbook, inventory, edge, DNS or a service name — check whether an existing Ansible playbook can do it idempotently before writing ad-hoc shell or SSH commands. Use this skill for the applicability checklist, to reuse chaba's ansible/ playbooks, and to choose --check/--limit/approval gates.
---

# Ansible-first applicability check

Use this at the start of a job, before the first mutating command. It is a 30-second triage, not a mandate: most local/repo work should **not** go through Ansible.

## 1. Triage the task

1. **Local file read/edit, repo change, test, docs** → skip Ansible; use normal tools.
2. **Kanban / wiki / SSOT / focus-inbox mutation** → use the board-api write door (`/card`, `/comment`, `/action`, `/publish`, `/wiki/page`). Ansible does not own those surfaces; do not shell into a host to edit their files.
3. **Remote host, service, container, fleet, provisioning, repeatable config** → Ansible candidate. Continue.
4. **Read-only host diagnosis** → MCP debug / read-only SSH is fine; Ansible `--check` is optional, not required.

## 2. Look for existing automation first

In an ada-ocb worktree:

```bash
grep -Rni -m 30 '<topic-or-host>' ansible/playbooks ansible/inventory docs/ssot/infrastructure | head -40
ls ansible/playbooks
```

Known entry points: `ansible/site.yml`, `ansible/playbooks/deploy-runner-agent.yml`, `ansible/playbooks/runner-cap.yml`, `ansible/playbooks/verify-runner-tools-sync.yml`, `ansible/playbooks/audit-runner-tools.yml`, `ansible/playbooks/ada-ocb-upgrade.yml`, `ansible/playbooks/session-capture.yml`, plus `ansible/templates/` and `ansible/inventory/{group_vars,host_vars}`. Also check `~/ansible` for user-level playbooks/inventory before inventing a new one. Reuse an existing playbook rather than writing `ssh <host> 'sed -i ...'`.

**Controller:** run Ansible from `tony-dell` (`/home/tony/CascadeProjects/chaba`) — that is where `ansible-playbook` is installed and whose converge timer already calls these playbooks. idc03 has no Ansible on PATH.

## 3. Preflight before any change

- Confirm the target host from `docs/ssot/infrastructure/` (or inventory), not from memory.
- Run in check mode first: `ansible-playbook --check --diff --limit <host> <playbook>`.
- Secrets stay in vault/secret files and environment substitution — never in chat, command lines or committed YAML.
- Disruptive plays (service restart, edge/Caddy, DNS, firewall, package upgrades) need explicit Tony approval and a rollback note.
- Prefer idempotent tasks/templates; repetitive `sed` on a remote host is a smell.

## 4. If no playbook exists

- **One-off**: direct shell with explicit host, dry-run where possible, and a recorded rollback.
- **Repeatable**: add a playbook under `ansible/playbooks/` with a card/job trail, then run it through the same preflight.
- Record the decision and where it was filed so the next session does not redo the search.

## Guardrails

- No Ansible for board-api-owned mutations (see triage step 2) — the door is the single writer and owns credentials.
- No blanket fleet runs: always `--limit` or an explicit inventory group.
- No direct edits to host config outside a playbook/template when a playbook exists.
- Verify after the change with the same check that identified the problem (health tool, endpoint, service status), and file the evidence.

## 5. Governed workflow (standard procedure)

The full procedure is codified in `docs/ssot/infrastructure/ssot.ansible-change-procedure.yml` with a human/Ada-readable mirror in `docs/kb/ansible-fleet-change-procedure.md`. Follow all nine steps for any mutating fleet job:

1. **Locate** an existing playbook (grep above); reuse it, never reinvent `ssh <host> 'sed -i ...'`.
2. **Confirm target** from `docs/ssot/infrastructure/` and `ansible/inventory/hosts.yml`, not memory. Respect `macos` / `disabled` / `portable` groups; always `--limit` or an explicit group.
3. **Diagnose read-only** — hash source and installed copy, check service state, capture the consumer-side symptom (e.g. `/queue` blocked reasons). Never mutate on an unverified symptom.
4. **Preflight** — `--check --diff --limit <host>`; require 0 unreachable / 0 failed.
5. **Approval** — explicit go-ahead when the play restarts a service or touches edge/Caddy/DNS/firewall/packages. A oneshot timer service still counts: name the restart and its effect (an in-flight pass will be killed and replaced by one long pass).
6. **Backup** — timestamped sibling copy of installed artifacts before the run; record the path.
7. **Converge** — real run with `--limit`; let handlers fire.
8. **Verify** — re-run the exact step-3 check, re-run `--check` for idempotency (`changed=0` everywhere), and prove consumer recovery (queue eligibility / claimed card / healthy endpoint), not just matching hashes.
9. **File evidence** — job SSOT under `docs/ssot/jobs/<area>/` with hashes, check output, consumer proof, rollback path and lessons; mirror the lesson to KB/MDDB where Ada acts on it.

Ground truths worth carrying into every similar job:

- A "newer than repo" guard compares **mtime, not content** — a newer-mtime installed copy can still be missing features. Hash both sides before choosing a direction.
- Drift flags are a lagging indicator between repo-sync and tool-sync; often already healed by the time a job lands. Verify before mutating.
- The runner-agent pin in `scripts/devin/runner-tooling.manifest.json` is the shared gate for both `sync-runner-tools.sh` and `runner-agent._self_update()` — don't deploy an unpinned build.
