# dispatch outcome — con01 warm standby for ada-line-relay + ada-ha-tony

Card: `con01-ada-lane-warm-standby` (ADA-0784). Dispatch
`20261127-142108-con01-warm-standby-for-ada-lin` on tony-dell.

## Finding

The card's deliverables were already built and deployed-masked by the
2026-11-26 dedicated session (commit `6c320356d12`): standby unit files under
`stacks/con01/{ada-line-relay,ada-ha-tony}/`, the Ansible installer
`ansible/playbooks/deploy-con01-ada-warm-standby.yml`, the failover/rollback
runbook `docs/kb/con01-ada-lane-warm-standby.md`, and the job record
`docs/ssot/jobs/infrastructure/2026-11-26-con01-ada-lane-warm-standby.yml`.
A backlog-spec-enrich pass at 13:23 today already skipped the card as done.
This dispatch therefore ran as a **verify + SSOT-drift-fix** pass rather than
re-implementation.

## Verified live (2026-11-27, read-only)

- con01: both `*.service.standby` files present under
  `~/.config/systemd/user/standby/`; canonical `ada-ha-tony.service` +
  `ada-line-relay.service` are symlinks to `/dev/null` (masked), both
  `inactive`. On-host sha256 matches repo exactly
  (`d7ab3a64…` / `769e560e…`).
- Secrets path: today's `~/secrets-backup/secrets-20261127-0300.tar.age`
  decrypted-listing contains `line-bot.env`, `notebooklm-rest-api.env`,
  `tony-ha/backend.env`, `tony-ha/keys.json` — the restore runbook's inputs
  are fresh.
- caddy-edge Caddyfile on con01 still routes `/webhook/line` + `/relay-img/*`
  → `127.0.0.1:8912` and `/apps/ha/ada-tony/*` → `127.0.0.1:8002`. No edit
  needed, none made.
- Live idc03 units unchanged in every field the standby mirrors
  (EnvironmentFiles, ExecStart, ports) — standby is not stale.
- con01 `mddb-follower.service` active (the standby's MDDB target).

## Changed this session (commit `5e9153f1267`)

SSOT drift found and fixed — the standby existed on-host but the service
registry still described the retired idc01 standby:

- `docs/ssot/infrastructure/ssot.services.yml` — `ada-ha-tony` note now
  points at the con01 masked standby + runbook; `ada-ha-michael` note
  corrected (idc01 standby lost with host retirement 2026-11-14; no standby
  staged for that lane).
- `docs/ssot/infrastructure/ssot.system-map.yml` — `standby:` pointers added
  to the `chaba-ai` persona and `ada-line-relay` edge entries so failover
  lookup lands on the con01 path.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — con01
  `expected_services` now declares both masked units
  (`expected_state: inactive` — audit treats "running" as drift, which is
  correct: activation should update SSOT); host description lists the role.

Pre-commit SSOT validation + optimization gate passed.

## Result / state

Warm standby is **staged, verified, and inert** — exactly the card's scope.
Remaining activation steps (venv provisioning, unmask+start, caddy-edge
start, Cloudflare DNS repoint) are deliberately gated on Tony per the
runbook; they are failover-time actions, not pending work. Nothing was
started, no DNS/edge/service changed on any host.

## Known pre-existing gaps (not introduced here, not fixed)

- `caddy-edge.service` on con01 has been inactive since 2026-11-25 while
  `ssot.audit.hosts.yml` declares `expected_state: active`. The con01
  audit-hosts node has produced no meta since 2026-11-24 (focus-inbox
  report-watch item `2026-11-24-205554-report-watch-audit-hosts-con01`), so
  this drift is not auto-flagged. Starting the edge is a gated failover
  step — left alone.
- con01 `~/CascadeProjects/ada-voice` checkout is stale (`65a7464`,
  2026-10-22) with no `.venv` — documented gated step 4 in the runbook.

## How to verify

```sh
ssh con01 'ls -l ~/.config/systemd/user/standby/ ~/.config/systemd/user/ada-{ha-tony,line-relay}.service;
  export XDG_RUNTIME_DIR=/run/user/$(id -u);
  systemctl --user list-unit-files ada-ha-tony.service ada-line-relay.service;
  sha256sum ~/.config/systemd/user/standby/*.service.standby'
# expect: 2 standby files, 2 -> /dev/null links, both masked, hashes
# d7ab3a64…/769e560e… matching stacks/con01/*/
```

Failover procedure (all gated): `docs/kb/con01-ada-lane-warm-standby.md`.

lessons:
- Re-dispatched cards may already be done — read the card comms tail +
  docs/ssot/jobs/ before implementing; verify-then-close beats re-work.
- Masked units never appear in `systemctl --user list-units`; declare them
  in ssot.audit.hosts.yml with expected_state: inactive so the audit
  contract covers standby intent without expecting them running.
- ssot.services.yml notes go stale on host retirement — the "idc01 keeps a
  masked warm-standby unit" claim survived idc01's 2026-11-14 retirement;
  grep for retired-host claims when editing adjacent entries.
- con01's audit-hosts node produces no meta (focus-inbox since 2026-11-24),
  so declared-vs-observed drift there (e.g. caddy-edge inactive vs
  expected active) is currently invisible to automation.
