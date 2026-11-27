# Dispatch outcome — triage five open read-only Ansible audit alerts (2026-11-27)

Card: `ansible-audit-alerts-triage-2026-11-27`

## What was done

Re-ran all five read-only audit playbooks on the real controller (idc02,
`~/CascadeProjects/chaba/ansible`, same units `ansible-audit-board.timer`
uses at 06:30 +07) WITHOUT `board_notify`, at 13:10–13:14 +07, against the
live report path `reports/ansible-benchmark/<area>/`. Pre-run reports were
snapshotted to `/tmp/audit-snap-20261127-131029` on idc02; run logs at
`/tmp/audit-rerun-20261127/` on idc02. Compared fresh verdicts against the
06:3x alert fingerprints and `ssot.audit.hosts.yml` / `ssot.jobs.yml` /
live unit state on each host.

## Verdicts

| card | verdict | evidence |
|---|---|---|
| ansible-runner-tools-drift | **live-stale — CLOSED** | 06:33 alert was pin-bump→self-update lag; 13:10 re-run: all 7 hosts OK vs manifest pin `d0465bfe` on all 6 tools. Residual: kk-mac MISSING-DEST ×4 = chaba-only lane by design (dispatch-repos.conf); audit playbook lacks per-host tool scoping → audit false-positive. |
| ansible-log-shipper-alert | **live-stale — CLOSED** | 06:34 alert (script drift + mn01 TimeoutStartSec=600) root-caused to OPS-1497; fix deployed fleet-wide ~12:00 via approved `ansible/playbooks/log-shipper.yml`. 13:11 re-run: mn01 units refreshed to 2700, all lanes success. Residual script-hash diff = fix commit 354d127 not yet merged — clears on merge, owned by `log-shipper-mddb-heartbeat-timeout-fix` (doing). |
| ansible-mcp-verify-alert | **REAL outage — open** | kk-mac/tony-macbook "unreachable" were asleep laptops (reachable now). All fails share one root cause: `mn-ha-dev.service` on mn01 crash-looping since ~09:16 (1474 failed starts today, conmon exit 126, rootless netns kill permission denied on tailnet-IP publish) → MCP mn01:9585 refused. Same signature on `xmeye-vms.service` (:5900, NRestarts=9611) — mn01 rootless-podman netns broken for `100.106.196.22` publishes; other quadlets healthy. |
| ansible-fleet-service-drift | **REAL persistent drift — open** | Verified twice (13:10 identical to 12:57 for 4 hosts): con01:6 idc02:9 idc03:26 mn01:5 tony-dell:19 tony-omen:20 tony-macbook:6. Majority = `ssot.audit.hosts.yml` census lag (last_updated 2026-11-11, predates OPS-0725 + fleet additions: opencode-serve/sidecar-collector undeclared fleet-wide, idc03 renames, jobs migrated to tony-omen/idc03). Genuine subset: mn01 mn-ha-dev+xmeye-vms crash-loops, tony-dell gemini-ollama-proxy fail + declared-absent chaba-postgres-16 running, con01 doc-mirror/mddb-vector-reindex fail, tony-omen runner-agent.timer disabled + yomi-process fail, tony-macbook zram-swap fail. No converge playbook exists — needs SSOT census refresh + per-unit fixes. |
| ansible-worktree-audit-alert | **REAL findings + policy bug — open** | Same verdicts on re-run. idc03 role-marker fail is a FALSE POSITIVE: `wt_policy` in audit-worktrees.yml hardcodes `role: readonly` for `chaba-tony-dell`, but on idc03 that checkout is the served writer (tony-dell's same path is the readonly mirror — policy can't express per-host roles). Real: dirty served checkout on idc03 (untracked litellm files), 558 dirty paths on tony-dell mirror, fleet-wide stale dispatch-wt-* accumulation. |

## Board actions

- Verdict comments posted on all five cards.
- Closed `ansible-runner-tools-drift` and `ansible-log-shipper-alert` via
  `/action do=close` after live verification.
- Kept `ansible-mcp-verify-alert`, `ansible-fleet-service-drift`,
  `ansible-worktree-audit-alert` open with verdict comments.
- Raised approval request `approve-host-state-remediation-on-mn01-f-fc1183`
  on the triage card: repair mn01 rootless-podman netns / restart
  mn-ha-dev + xmeye-vms quadlets (suggested: restart-only first).

## How to verify

- Fresh reports: `ssh idc02 'ls ~/CascadeProjects/chaba/reports/ansible-benchmark/{services,log-shipper,mcp,worktrees}/'`
- Run logs: `ssh idc02 'ls /tmp/audit-rerun-20261127/'`
- mn01 outage: `ssh mn01 'systemctl --user status mn-ha-dev.service xmeye-vms.service'`
- Answer arrival: `$TASK_DIR/answers.jsonl` (empty at finish).

## Follow-ups worth carding (not done — out of scope)

- `ssot.audit.hosts.yml` census refresh (last_updated 2026-11-11) — the
  bulk of fleet-service-drift deltas are stale declarations, not host drift.
- `audit-worktrees.yml` wt_policy per-host role override (idc03 served vs
  tony-dell readonly for the same path).
- `audit-runner-tools.yml` per-host tool scoping (kk-mac chaba-only lane).
- mn01 rootless-podman netns repair (awaiting approval request answer).

lessons:
- The five "audit alert" cards are fed by `ansible-audit-board.timer` on idc02 (daily 06:30+07, 8 playbooks, `-e board_notify=true`); reports land in that host's `~/CascadeProjects/chaba/reports/ansible-benchmark/` — re-run there without board_notify for a clean live check.
- ansible-playbook is NOT installed on con01 — the fleet controller is idc02 for the scheduled audits (tony-dell per skill doc for manual converge runs).
- Ansible report files only rewrite when content changes — mixed mtimes in a report dir do NOT mean a partial run; checksum-gated template writes preserve mtime on identical content.
- log-shipper "script differs" drift can be a fix deployed fleet-wide BEFORE its commit merges — check the owning card (OPS-1497) before treating live!=repo as bad drift; converging would revert the fix.
- mn01 rootless podman was silently broken for tailnet-IP publishes — two quadlets (mn-ha-dev :9585, xmeye-vms :5900) crash-loop with identical conmon/netns errors while loopback-publish quadlets stay healthy; suspect rootlessport/pasta layer, not the containers.
