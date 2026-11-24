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
| `@opencode/cli` | 2.3.2 | 2.3.2 |
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

## Out of scope / follow-ups

- `ada-ocb-upgrade.yml` (prod write) — needs explicit same-session approval;
  when built it must start the host's existing update unit, not reimplement `npm i -g`.
- Board card writes stay on board-api only; Ansible remains stateless.
- The hourly `ada-ocb-smoke.timer` probes the MCP bridge, not the pane — this
  audit covers the pane surface explicitly.
- Adjacent drift seen in the wider fleet (idc03 `/` 98%, tony-dell `/` 99%,
  idc03 stagger hook mode 0775 vs 0755) is not caused by and not gated here;
  it belongs to the existing disk-headroom / stagger-verify playbooks.
