---
category: operations
type: report
status: verified
date: 2026-11-24
card: ada-ocb-ansible-audit-verify
---

# Ada-OCB Ansible audit + verify — first live run (2026-11-24)

## Scope

Ground Ansible as the **declared-state and verification layer** for the
ada-ocb OpenChamber pane. The upgrade executor already exists on idc02
(`openchamber-update.service` + monthly timer, 1st 06:30 — npm install,
fail-loud `models.status` patch re-apply, restart). No installer was
duplicated and no host was written to during this pass.

Files added/changed (this worktree, branch `ada-ocb`):

- `ansible/inventory/hosts.yml` — `ocb_pane` group (idc02 primary, tony-dell fallback).
- `ansible/inventory/group_vars/ocb_pane.yml` — declared contract + pins.
- `ansible/playbooks/tasks/ada-ocb-probe.yml` — one JSON round-trip per host.
- `ansible/playbooks/tasks/ada-ocb-edge-probe.yml` — controller-side consumer probe.
- `ansible/playbooks/ada-ocb-audit.yml` / `templates/ada-ocb-audit.j2` — read-only audit + durable artifact.
- `ansible/playbooks/ada-ocb-verify.yml` — contract gate, exit 2 on drift.
- `ansible/README.md` — usage + governance notes.

## Verified live state

Producer (idc02, primary):

| Check | Observed | Expected |
|---|---|---|
| node | v24.14.0 | v24.14.0 |
| `@openchamber/web` | 2.7.3 | 2.7.3 |
| `@opencode/cli` | 2.3.2 (pre-upgrade) | 2.3.2 at first run; 2.4.1 accepted after the upgrade — see resolution below |
| 4 required units | active | active |
| update timer next | Tue 2026-12-01 06:30:00 | monthly 1st 06:30 |
| bind | 127.0.0.1:3000 | 127.0.0.1:3000 |
| local HTTP | 200 | 200 |
| models.status patch | present | present |
| `startup.env` mode | 600 | 600 |
| litellm drop-in | present | present |

Consumer (public edge): `https://ada-ocb.surf-thailand.com/` → **200**, CSP
contains `frame-ancestors` (allows `openchamber-ui://app`,
`capacitor://localhost`, `https://ada-ha.surf-thailand.com`, and the ada-ha
tony endpoint). Edge was forced to the known front IP `45.136.236.190`
via `curl --resolve` so DNS drift cannot make the check pass against a stale pane.

Fallback (tony-dell, role=fallback): web **2.7.0** (one minor behind), patch
**absent**, `ada-ocb-smoke.timer` and `ada-ocb-bridge-sync.timer` inactive.
SSOT confirms those two timers are idc02-only and tony-dell is the
pre-migration soak copy pending Tony's retire decision. The gate therefore
reports this as **INFO (non-fatal)** rather than failing — version pins and
patch are enforced only on the `primary` role. Full detail is in the durable
artifacts `reports/ada-ocb/{idc02,tony-dell}.yml` (gitignored).

## Gate behavior proof

A negative run with an overridden contract value (`-e ocb_bind=127.0.0.1:9999`)
exited **2** with a named assertion (`p.bind_3000 == ocb_bind`) and bounded
evidence for both hosts — no silent pass. The SSOT cross-check likewise fails
loudly if inventory pins drift from `ssot.audit.hosts.yml`.

## Commands

```bash
cd ansible
ansible-playbook playbooks/ada-ocb-audit.yml
ansible-playbook playbooks/ada-ocb-verify.yml
ansible-playbook playbooks/ada-ocb-verify.yml --limit idc02   # primary only
```

Both playbooks are read-only on targets. Probes carry `check_mode: no`, so
`--check` still produces genuine evidence. No secrets are read into Ansible;
the probe only asserts `startup.env` mode 600 and that the drop-in references
`litellm-ada.env`.

## Approval-gated upgrade playbook (built, not executed on prod)

ADA-0015 added `ada-ocb-upgrade.yml` plus a shared assertion file
(`tasks/ada-ocb-assert.yml`) now used by both verify and the upgrade post-gate
— one gate, no fork. The playbook is inert by default
(`ocb_change_approved: false` in `vars/ada-ocb-upgrade.yml`) and starts
idc02's existing `openchamber-update.service` only when explicitly approved.

Live unit inspected: `Type=oneshot`, `RemainAfterExit=no`,
`ExecStart` = `npm i -g --prefix ~/.local/node @openchamber/web@2.7.3 @opencode/cli`,
two `ExecStartPost` steps (patch script, then `openchamber.service` restart).
Fail-loud behaviour is the host unit's, not Ansible's.

Safety proofs (all runs `changed=0` on every host):

| Run | Exit | Unit start |
|---|---|---|
| `--check --diff` | 0 | skipped (check mode) |
| no approval, no `--check` | 0 | skipped (`ocb_change_approved=false`) |
| `-e ocb_change_approved=true --check` | 0 | skipped (check mode beats approval) |
| verify with `-e ocb_bind=127.0.0.1:9999` | 2 | n/a — named assertion, bounded evidence |

Rollback is printed on the controller before the write task. The `systemd`
module cannot reach the user bus over SSH here (`Failed to connect to bus`),
so the guarded `systemctl --user` shell path is used; check mode is enforced
by `not ansible_check_mode`, not by module emulation.

### Live execution (2026-11-24 08:25–08:26 +07, Tony-approved)

The approved command was run on idc02. Outcome:

- `openchamber-update.service` finished `Result=success`, `ExecMainStatus=0`
  at 08:26:04. Journal: `changed 210 packages in 45s`, patch applied and
  syntax-checked, then the unit completed.
- Producer after the run: web **2.7.3** (correct), all four units active,
  `127.0.0.1:3000`, local HTTP **200**, patch present, `startup.env` 600.
  Consumer: public edge **200**. The transient 404 seen during the run was
  mid-install, not a post-run failure.
- **Post-gate FAILED (exit 2)**: `@opencode/cli` is **2.4.1**, while SSOT
  declares **2.3.2**. Root cause is the host unit's `ExecStart` pinning only
  `@openchamber/web@2.7.3` and installing `@opencode/cli` bare — the exact gap
  flagged before execution. The gate did its job: fail loud, named assertion,
  no silent "ok".
- Card ADA-0015 stays in **review**; its done-condition (verify green) is not
  met. Fix carded as **DEV-0020** (`ocb-cli-pin-drift`) with two options and a
  recommendation. No further host writes were made.
- Secondary finding: during install npm reported node `v22.22.1` / npm
  `11.9.0` (`EBADENGINE`: web 2.7.3 requires node `>=24.14.0`), despite the
  unit's `Environment=PATH` pointing at `~/.local/node24/bin`. The service is
  healthy now, but the install-time runtime is inconsistent.

### Resolution — CLI 2.4.1 accepted (Tony decision, DEV-0020)

Compatibility check: `~/.local/node/bin/opencode --version` → `v2.4.1`;
`openchamber.service` journal shows normal session activity with no errors;
local 200, edge 200, patch present, four units active. web 2.7.3 declares
`opencode >=2.2.4`, which 2.4.1 satisfies.

Per Tony's choice, the declaration now tracks the installed version:

- `ssot.audit.hosts.yml` — CLI pin `2.3.2` → `2.4.1`, with a note recording
  the decision and that the host unit installs CLI bare by design.
- `ansible/inventory/group_vars/ocb_pane.yml` — `ocb_cli_version: "2.4.1"`.
- `ansible/README.md` — documents that CLI may float on future updates.

Post-change checks: `node scripts/ssot-validate-all.mjs` → 5641/5641 valid,
0 errors; `ansible-playbook playbooks/ada-ocb-verify.yml` → **exit 0**,
"Pins 2.7.3 / 2.4.1 are declared in ssot.audit.hosts.yml", producer contract
OK on both hosts, edge OK. ADA-0015 can now be closed with this evidence.

Residual risk: CLI floats on every monthly update, so a future upstream
release can move it again; verify will catch that as drift and the decision
recurs. The npm/node runtime mismatch during install remains a separate
unexplained finding (service currently healthy).

## Out of scope / follow-ups

- Running the upgrade with `-e ocb_change_approved=true` on idc02 — needs
  explicit same-session approval.
- Board card writes stay on board-api only; Ansible remains stateless.
- The hourly `ada-ocb-smoke.timer` probes the MCP bridge, not the pane — this
  audit covers the pane surface explicitly.
- Adjacent drift seen in the wider fleet (idc03 `/` 98%, tony-dell `/` 99%,
  idc03 stagger hook mode 0775 vs 0755) is not caused by and not gated here;
  it belongs to the existing disk-headroom / stagger-verify playbooks.
