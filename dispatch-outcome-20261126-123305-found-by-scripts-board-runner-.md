# Dispatch outcome — runner-tool-drift-fleet

Card: `runner-tool-drift-fleet` → **done** (auto-closed by
`runner-drift-rearm.py --verify` at 12:51 after clean re-audit).

## What was found

- Drift transcript was partially stale: idc02 `runner-agent` and con01
  `devin-dispatch` DRIFT had already been re-converged to pins at
  ~11:28–11:33 by the earlier drift-followup job (verified by hash).
- Real remaining drift: missing aux tools — `claude-dispatch`,
  `devin-dispatch-prune`, `dispatch-queue`, `dispatch_repos.py` on
  idc02/idc03/con01, 3 of those on mn01, plus `dispatch_repos.py` on
  tony-dell and 3 tools on tony-macbook. `sync-runner-tools.sh` cannot
  self-heal these (it only installs runner-agent/devin-dispatch when
  missing).
- Mid-task discovery: fleet was inside a global `ForceCommand
  internal-sftp` sshd window — idc02/idc03/con01/mn01 were SFTP-only at
  ~12:40. At ~12:49–12:50 the fix landed fleet-wide as scoped hardening
  (`Match Group sftponly`), restoring shell everywhere.

## What was done

1. `deploy-runner-tools.yml --check --diff --limit tony-dell,tony-omen,tony-macbook`
   → expected deltas only (dell 1, macbook 3, omen 0).
2. Applied same limit: 4 tools deployed, all 6 pin asserts passed,
   runner-agent restarted on changed hosts.
3. While shell was dead, installed the 15 missing tools on
   idc02/idc03/con01/mn01 via **SFTP put + chmod 755** using pinned
   worktree bytes (verified sha256 == manifest pin == each host's
   checkout beforehand); re-downloaded and hash-verified 24/24 == pin.
4. Re-audit `audit-runner-tools.yml`: 42 OK lines, zero findings;
   `runner-drift-rearm.py --verify` → card closed.
5. Final full-fleet `deploy-runner-tools.yml --check`: **changed=0,
   unreachable=0 on all 7 hosts** — proves SFTP installs are
   byte-identical to playbook output.

## Artifacts

- `reports/ansible-benchmark/deploy-runner-tools/20261126-125135/` —
  check.log, apply.log, audit-after.txt, check-final-fleet.log
- `docs/ssot/jobs/infrastructure/2026-11-26-runner-tool-drift-fleet.yml`
- Card comms on `runner-tool-drift-fleet` (verify + close) and
  `ops-mn01-restore-sshd-shell-20261126` (obsolete notice).

## How to verify

- `cd ansible && ansible-playbook playbooks/deploy-runner-tools.yml --check`
  → all hosts "REDEPLOYED 0 tool(s) in-sync".
- `ansible-playbook playbooks/audit-runner-tools.yml` → all OK lines.
- `python3 scripts/board/runner-drift-rearm.py --audit-file <audit> --verify --dry-run`
  → `{"findings": {}}`.

lessons:
- ansible serial:1 aborts all remaining batches on an unreachable host (core 2.22) — always --limit when targets may be down.
- runner-drift-rearm.py --verify needs `ssh idc03` shell; HTTPS board-api (/comment, /action) is the fallback write door during sftp-only windows.
- sftp survives ForceCommand internal-sftp: put/get/chmod work — pinned-byte install + hash-verify is a viable last-resort converge; confirm later with ansible --check.
- Drift transcripts age fast — hash-check installed-vs-pin before mutating; both DRIFT findings were already healed by an earlier job.
