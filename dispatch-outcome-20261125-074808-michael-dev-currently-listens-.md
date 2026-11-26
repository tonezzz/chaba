# Dispatch outcome — michael-dev-migrate-mn01 (2026-11-25)

## What changed

Moved the mn-ha-dev Home Assistant dev instance (container `mn-ha-dev`,
renamed from michael-dev 2026-11-24) from idc02 to mn01, live + repo.

**Live migration (executed):**
- mn01 prep: quadlet `~/.config/containers/systemd/mn-ha-dev.container`,
  secrets (`ha-mn-ha-dev.env`, ha-token), mha-state-push venv+unit,
  HA image 2026.9.0 pulled, ~1GB config rsynced idc02->mn01.
- Cutover: idc02 units stopped, delta rsync, `.storage/core.config`
  internal_url -> `https://mn01.taila0626a.ts.net:8124`, mn01 container +
  mha-state-push started.
- `tailscale serve --bg --https=8124 http://127.0.0.1:8124` on mn01.
- Consumers repointed: idc02 caddy-edge upstream, idc02 web.service +
  mn01 caddy-mn01 `/apps/ha/*` redirects, `mcp_config.json` on
  tony-dell/tony-omen/tony-macbook.
- idc02 parked: `mn-ha-dev.service` masked, `mha-state-push.service`
  disabled, config dir intact for 24h rollback.

**Repo (44 files, commit 5a0601d3441 on dispatch branch):**
- SSOT: routes, services, values, system-map, migrated-units, secrets,
  instances, lanes, mcp, ha.mcp, tools, operations, home-assistant.* —
  all idc02:8124/9585 refs -> mn01.
- Scripts: deploy-card/config, mirror-sweep, sync-ssot-from-live,
  promote-view/apply-tpl/copy-view/assess-device, mha-state-push,
  promote-michael, key-watch, ha-events/ha-report.
- Ansible audit-mcp-verify, stacks (mn01 quadlet new, web+mn01 Caddyfiles,
  apps pages, routes.json regenerated), AGENTS.md, edge-upstream-audit
  resolution note.
- Job trail: `docs/ssot/jobs/infrastructure/2026-11-25-mn-ha-dev-mn01-move.yml`

## Result / verification

- `https://mn01.taila0626a.ts.net:8124/` -> 200; `/tony-test` -> 200
- MCP `http://mn01:9585/<token>` initialize -> ha-mcp 9.2.0
- mha-state-push active, mirrored entity last_updated current
- `/apps/ha/mn-ha-dev` -> 308 mn01:8124 on both web origins
- `michael-dev.surf-thailand.com` -> CF Access 302 (edge alive)
- idc02: mn-ha-dev masked+inactive, mha-state-push disabled+inactive

## Notable findings

- idc02's `https://idc02...:8124` had been silently dead since 2026-11-24:
  a podman `PublishPort` on the tailnet-IP :8124 conflicted with
  tailscale serve's bind and killed the serve mount (only
  `http://idc02:8124` worked). mn01 avoids this — serve owns :8124,
  quadlet publishes :8124 on 127.0.0.1 only.
- Pre-existing dead automation noted (not fixed, unrelated):
  ha-card-snapshot/pv1-values on tony-dell has no timer; snapshots stale
  since Sep.

lessons:
- tailscale serve binds the tailnet IP:port itself — a podman PublishPort on the same IP:port crash-loops with "bind: address already in use"; publish HA UI on 127.0.0.1 only and let serve own :8124.
- `tailscale serve` without `--bg` runs in foreground; always pass `--bg` (or it dies with the ssh session).
- Quadlet `HealthCmd=/bin/sh -c "..."` breaks on podman 5.7 ("unterminated quoted string" — healthcheck already runs via sh -c); use `HealthCmd=curl -sf -o /dev/null <url>`.
- sed -i on single-file bind-mounted Caddyfiles leaves the container serving the old inode — restart the unit, `caddy reload` is not enough.
- When migrating HA, check `.storage/core.config` internal_url AND `.storage/http` trusted_proxies before first boot; podman bridge subnet was identical (10.88.0.0/16) so trusted_proxies carried over.
