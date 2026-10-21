# Host Hygiene Rules — how machines stay clean this time

> Adopted 2026-10-21, after the tony-dell drain. Applies to every host
> (dell, omen, mn01, macbook, idc01-03). The failure mode these kill:
> *things get installed ad-hoc, half-removed, and nobody can tell what's
> live.* Root cause is always the same: live state diverges from declared
> state and nothing reconciles them.

## R1 — Declared-or-dead

Every running unit/container/timer exists in the repo (`systemd/`,
`stacks/`, or quadlet dir) **and** is declared in
`ssot.audit.hosts.yml expected_services`. Anything else: disable it or
declare it — never leave it ambiguous. The audit is the enforcement:
run `scripts/audit-hosts.py --host <h>` after any service change;
`last_observed` >14d is a defect, not a statistic.

## R2 — No half-states

A unit is **enabled or deleted**. Never `.parked`, `.bak`, `.disabled`,
`migrated-off/` — those directories are where services go to become
unanswerable. History lives in git; deletion is recoverable, ambiguity
is not. Retiring a service = delete the unit file + commit the removal
in the repo + remove the SSOT expectation in the same change.

## R3 — One checkout per role

One canonical clone per host per purpose (writer / exec / dev — each
declared). Dispatch work only in `dispatch-wt-*` worktrees, and a
janitor deletes merged/stale ones (>7d). Never hand-edit a served or
writer checkout. New card work from non-writer hosts goes through
board-api, not file edits.

## R4 — Secrets live in one place

All secrets in `~/.config/secrets/` mode 600, consumed via
`EnvironmentFile=` or read-at-runtime. Zero inline tokens in units,
crontab, quadlets, or scripts (precedent violations: h3 token in
`tony-dell.sh` cron, mddb inline secrets on idc01). Audit = grep units
and crontab for token-shaped strings.

## R5 — Containers as quadlets

Services run as rootless podman quadlets
(`~/.config/containers/systemd/*.container`) declared in the repo.
No ad-hoc `docker run`/`docker-compose` orphans. Images pinned to
tags, never `:latest` in declarations.

## R6 — Data tiers, declared

Three tiers: **live** (has a named backup path), **archive**
(→ idc02:~/backups or gdrive, never the system disk), **cache**
(always disposable — excludable from any clone). Nothing else gets a
home in `~/`. Stray files = the `/home/tony/-` incident.

## R7 — Identity, not floating IPs

Every host/service gets a DHCP reservation or a tailnet identity.
No floating admin IPs (repeater lesson), no static claims outside the
router's reservation table (the `.67` poach). New device = registry
entry in ssot.mac/ip registries at setup time.

## R8 — Changes via repo + restart

Live state changes only through: commit → install/sync → unit restart.
No `systemctl edit`, `docker exec` patches, or hand-edited configs that
a restart silently reverts — that class of change is how "it worked
yesterday" happens.

## R9 — Rollback is stated before destructive ops

Every destructive step (wipe, delete, cutover) names its rollback
mechanism in advance — a second disk, a verified copy, a boot entry.
The NVMe migration worked because rollback was designed in; apply that
shape everywhere.

## R10 — Home-LAN work lives on home-LAN hosts

Scans, failover checks, LAN proxies can't run on VPS hosts. Home-net
duties → mn01/omen; cloud duties → idc03 primary / idc02 edge+archive;
warm DR → idc01. Workload placement follows the
`tony-dell-drain-plan.md` destination table.

## Enforcement

- Daily `audit-hosts.py` per `ssot.audit.yml` schedule — drift lands
  as kanban cards, not chat messages.
- Session discipline: these rules are loadable into AGENTS.md as the
  host-ops section; violations get caught by the same audit loop.
