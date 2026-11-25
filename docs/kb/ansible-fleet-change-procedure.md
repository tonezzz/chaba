# Ansible fleet-change procedure

**Canonical spec:** `docs/ssot/infrastructure/ssot.ansible-change-procedure.yml`
**Standing order:** AGENTS.md "Procedure-lookup duty" — answer from the system, not memory.

Use this for remote-host, service, container, fleet or repeatable-config jobs.
Do **not** use it for board state (`/card`, `/comment`, `/action`, `/publish`,
`/wiki/page` are the only writers there) or for local repo-only work.

## Where to run

Controller is **tony-dell** (`/home/tony/CascadeProjects/chaba`), because that is
where `ansible-playbook` is installed and whose `runner-agent-converge.timer`
already invokes the converge playbook. idc03 has no Ansible on PATH.

```bash
ssh tony-dell 'cd /home/tony/CascadeProjects/chaba/ansible && ansible-playbook ...'
```

Inventory: `ansible/inventory/hosts.yml`. Always `--limit` or an explicit group.

## The nine steps

1. **Locate** — `grep -Rni <topic> ansible/playbooks ansible/inventory docs/ssot/infrastructure`.
   Reuse an existing playbook; do not invent `ssh <host> 'sed -i ...'` when one exists.
   No playbook? One-off = direct shell + dry run + rollback note. Repeatable = add a playbook.
2. **Confirm target** from inventory + `docs/ssot/infrastructure/`, never memory. Respect
   `macos`, `disabled` and `portable` groups.
3. **Diagnose read-only** — hash src and dest, check service state, and capture the
   consumer-side symptom (for runner drift: `/queue` blocked reasons).
4. **Preflight** — `ansible-playbook --check --diff --limit <host> <playbook>`; require
   0 unreachable / 0 failed.
5. **Approval** — explicit go-ahead if the play restarts a service or touches
   edge/Caddy/DNS/firewall/packages. Call out oneshot timer restarts too.
6. **Backup** — timestamped sibling copy of each installed artifact.
7. **Converge** — real run with `--limit`; let handlers fire.
8. **Verify** — re-run step 3, re-run `--check` for idempotency, and prove consumer
   recovery (queue eligibility, claimed card, endpoint healthy).
9. **File evidence** — job SSOT under `docs/ssot/jobs/<area>/` with hashes, outputs,
   consumer proof, rollback path, lessons; mirror the lesson to KB/MDDB.

## Worked example — runner-agent drift, 2026-11-25

All 7 Linux hosts held a stale installed `runner-agent`; the board-api drift gate
marked every host ineligible and 16 cards were stuck.

```bash
# diagnose
sha256sum ~/.local/bin/runner-agent ~/CascadeProjects/chaba/scripts/board/runner-agent.py
curl -s http://127.0.0.1:8787/queue | python3 -m json.tool   # blocked reasons

# preflight, then converge (controller = tony-dell)
cd ~/CascadeProjects/chaba/ansible
ansible-playbook playbooks/deploy-runner-agent.yml --check --diff
ansible-playbook playbooks/deploy-runner-agent.yml

# verify
ansible-playbook playbooks/deploy-runner-agent.yml --check   # changed=0 everywhere
curl -s http://127.0.0.1:8787/queue | python3 -m json.tool   # eligible != []
```

Result: 7/7 converged, drift-blocked hosts 0, queue 16 -> 7, 11 claimed.
Evidence: `docs/ssot/jobs/board/2026-11-25-runner-agent-drift-redeploy-verify.yml`.

## Lessons that generalise

- A "newer than repo" guard compares **mtime, not content** — a newer-mtime copy can
  be missing a thousand lines of features. Hash both sides.
- Drift flags are a lagging indicator between repo-sync and tool-sync; often already
  healed by the time a job lands. Verify before mutating.
- A restart handler on a oneshot service kills an in-flight pass. Expect one long
  replacement pass (tony-dell took 4m / 1.7 GB with 41 worktrees) before cadence
  returns to ~1 minute. Do not mistake it for a hang.
- Idempotency is the proof the fleet is converged: a second `--check` must show
  `changed=0` on every host.
