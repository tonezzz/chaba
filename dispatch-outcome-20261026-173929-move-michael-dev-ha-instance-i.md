# Dispatch outcome — move michael-dev HA idc03:8124 -> idc02:8124

**Result: DONE.** michael-dev (Michael HA dev staging) moved from idc03 to
idc02 per the capacity-adjust procedure. Card `capacity-move-michael-dev`
moved to `done` with evidence.

## What changed (live)

- **idc02**: podman image pulled; config rsynced (1.4G, bulk + post-stop
  `--delete-after` delta); quadlet `~/.config/containers/systemd/michael-dev.container`
  installed (stacks/idc02/michael-dev/) publishing 127.0.0.1:8124,
  127.0.0.1:9585, 100.123.163.11:9585; `.storage/core.config` internal_url
  patched to `https://idc02.taila0626a.ts.net:8124` (it was still stale
  tony-dell — drift fixed); `tailscale serve --https=8124` fronts it;
  mha-state-push.service + venv + tokens moved here too.
- **idc02 caddy-edge**: `michael-dev.surf-thailand.com` upstream -> idc02;
  `http://:8124` tailnet-IP shadow block **removed** (port conflict —
  tailscale serve owns :8124 now). Backup `.bak-michaeldev-move-20261026`.
- **idc02 web.service**: `/apps/ha/michael-dev*` 308 -> idc02 + static
  app pages repointed (needed container restart — `sed -i` breaks
  single-file bind mounts). Backup `.bak-mdev-move-20261026`.
- **mn01**: Caddyfile.mn01 redir + public/ statics -> idc02; caddy-mn01 reloaded.
- **idc03 parked**: michael-dev.service masked+inactive (quadlet kept,
  unmask+start = rollback), mha-state-push disabled, `tailscale serve
  :8124` removed. 24h rollback window until ~2026-10-27 17:50 +07.
- **MCP configs**: `~/.config/devin/mcp_config.json` on tony-macbook
  (idc03:9585->idc02), tony-omen + tony-dell (stale tony-dell:9585->idc02).

## Verification

- `curl https://idc02...:8124/api/` + token -> 200; `/api/config` reports
  internal_url=idc02:8124, version 2026.9.0
- websocket `auth_required -> auth_ok`; MCP `initialize -> ha-mcp 8.7.0`
  on loopback and tailnet IP
- `https://michael-dev.surf-thailand.com` -> 302 CF Access (edge-local 200)
- `/apps/ha/michael-dev` -> 308 idc02:8124 (web origin + tailnet front)
- `audit-hosts.py --host idc03 --host idc02`: intended delta only — both
  units match declared states; remaining deltas are pre-existing baseline
  drift (renames, undeclared services, missing timers) — flagged in the
  job file for a separate reconcile sweep.

## Repo changes (commit b0be5dc1d, dispatch branch)

New `stacks/idc02/michael-dev/michael-dev.container`; job trail
`docs/ssot/jobs/infrastructure/2026-10-26-michael-dev-idc02-move.yml`;
19 SSOT files updated (values gained an idc02 host entry; instances,
michael.dev, services, routes, system-map, lanes, audit.hosts,
host-capacity, mcp, ha.mcp, operations, migrated-units, dashboards,
secrets, cards, design, howto, michael); scripts repointed
(deploy-card.sh, deploy-config.sh, mirror-sweep.py, key-watch.py,
ha-events-report.py, copy-view.py, apply-tpl.py, promote-view.sh,
assess-device.py); web/mn01 stack artifacts; stale tony-dell:8124
leftovers swept to idc02.

## Notable findings

- No ada lane consumes the dev instance: `ada-ha-michael` was renamed
  ada-ai-kraut and targets live michael-ha — the card's HASS_URL concern
  resolved negative.
- The `michael-dev-parity.timer` on tony-omen (pre-existing failure)
  needs no repoint — it inherits `mirror-sweep.py`'s DEV_URL default,
  now idc02, once its exec checkout syncs.
