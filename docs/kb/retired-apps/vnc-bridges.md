# VNC websockify bridges — retired 2026-11-23 (OPS-1312)

Former surface: `/apps/vnc/` (noVNC UI) and `/apps/vnc/ws`, `/apps/vnc/ws-mn01`, `/apps/vnc/ws-macbook` (WebSocket proxies) on the tony-dell edge, upstreamed to the two websockify bridges on idc02. Also retired: the `vms` and legacy `macbook` keys in `cast-browser-server.mjs` on tony-dell and tony-omen, and the static `stacks/web/public/apps/{vnc,vms}` bundles.

**Not retired:** `/apps/vms-snap` — the XMEye channel snapshot shim on mn01 (`:8377`), used by `/apps/eye ?src=vms:<channel>`. It has no dependency on websockify.

## Why retired
Consumer audit (2026-11-23): zero established VNC sessions in 30 days of journal; the 10,814 `405 Method Not Allowed` lines were `check-routes.py` issuing plain GETs to a WebSocket-only endpoint. The bridges were nonetheless wired into the HA cast path (`vms`/`macbook` aliases, `cast-browser` vnc.html handling) and a user-facing app tile, so retirement was done as a coordinated config → cast-client → host sequence. Full evidence: `idc02-consumer-audit-ops1310-ops1312.md` and `vnc-bridge-retirement-plan-ops1312.md` in the infra workspace.

## What was removed
- `stacks/web/Caddyfile`: the `/apps/vnc/ws*` proxy handles and the static `/apps/vnc/*` file_server block.
- `docs/ssot/infrastructure/ssot.routes.yml`: `vnc-ws`, `vnc-ws-mn01`, `vnc-ws-macbook`, `vnc` routes and the `websockify-vms` / `websockify-macbook` listener entries; `routes.json` re-rendered.
- `stacks/web/public/apps/apps.yml`: `vnc` tile and its entry in the `remote` category; `ssot.health.home.apps.yml` regenerated (no `app-vnc`).
- `stacks/web/public/apps/vnc/` and `vms/` static noVNC bundles; dead `/apps/vms/` link removed from `stacks/web/public/apps/lab/index.html`.
- `ssot.migrated-units.yml`, `ssot.audit.hosts.yml`, `ssot.security.tony-dell.yml`, `ssot.home-assistant.automations.yml`: websockify unit/listener/automation references.
- On tony-dell and tony-omen: `cast-browser-server.mjs` `vms` key, `macbook` alias and the `if (url.includes('vnc.html'))` special-case.
- On idc02: `websockify-macbook.service` and `websockify-vms-mn01.service` stopped and disabled (unit files renamed `*.disabled-ops1312`).

## Restore steps
1. On idc02, restore the two units (exact contents below), then `systemctl --user daemon-reload && systemctl --user enable --now websockify-macbook.service websockify-vms-mn01.service`. Verify `ss -ltnp | grep -E ':6080|:6082'` shows both listeners.
2. Restore the `/apps/vnc/ws*` handles in `stacks/web/Caddyfile` and the four registry entries in `docs/ssot/infrastructure/ssot.routes.yml`; re-render with `python3 scripts/render-routes.py --caddy && python3 scripts/render-routes.py --check`.
3. Restore `stacks/web/public/apps/vnc/` (and `vms/` only if the old `/apps/vms/` Tailscale Serve mapping is also recreated), the `vnc` tile in `apps.yml`, and regenerate `ssot.health.home.apps.yml` from the generator.
4. Sync the Caddyfile to tony-dell's served checkout and restart the bind-mounted container with `systemctl --user restart web` — a bare `caddy reload` serves the stale inode (`docs/kb/host-reboot-verification.md:178-183`). Verify `curl -s -o /dev/null -w '%{http_code}' http://localhost/apps/vnc/` returns 200.
5. Re-add the `vms` key, `macbook` alias and vnc.html branch to `cast-browser-server.mjs` on **both** tony-dell and tony-omen, restart `cast-browser.service`, and smoke-test a `vms` cast.
6. Re-add the SSOT references listed above and the HA `input_select.tv_display` `vms` option.

### websockify-macbook.service (idc02)
```ini
[Unit]
Description=websockify macbook VNC (migrated from tony-dell 2026-10-17 OPS-0725 — tailnet-IP bind)

[Service]
ExecStart=/usr/bin/websockify 100.123.163.11:6080 100.124.59.112:5900
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

### websockify-vms-mn01.service (idc02)
```ini
[Unit]
Description=websockify mn01 VNC (migrated from tony-dell 2026-10-17 OPS-0725 — tailnet-IP bind)

[Service]
ExecStart=/usr/bin/websockify 100.123.163.11:6082 100.106.196.22:5900
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

### cast-browser keys (both hosts, pre-retirement)
```js
  vms: 'http://tony-dell/apps/vnc/vnc.html'
    + (MACBOOK_VNC_PASSWORD ? `?password=${encodeURIComponent(MACBOOK_VNC_PASSWORD)}` : '?password='),
  yolo: 'http://127.0.0.1:8080/apps/yolo/',
};

// Legacy aliases that keep old cast requests working.
const ALIASES = {
  macbook: 'vms',
};
```
plus, inside the navigation helper, after the waiting/login steps:
```js
  if (url.includes('vnc.html')) {
    await waitForVnc(p, 15000);
    // Give the VMS desktop a moment to paint after the VNC handshake.
    await p.waitForTimeout(4000);
  }
```
