# input-bridge on idc01

WS relay + vcast virtual-display registry. Moved from tony-dell 2026-09-25 to
co-locate with the Ada auth backend — key verification, claim, and redeem are
now loopback (`ADA_AUTH_URL=http://127.0.0.1:8001`) instead of a cross-host
call, and `ADA_ADMIN_KEY` no longer lives on a home host.

## Layout

- Source of truth for the server: `stacks/web/input-bridge/server.mjs`
  (shared repo — also serves the older `/apps/input-bridge/` remote pair).
- Live deployment on idc01:
  - app dir `~/apps/input-bridge/` (server.mjs + node_modules/ws)
  - quadlet `~/.config/containers/systemd/input-bridge.container` (copy in this
    directory)
  - env `~/.config/secrets/input-bridge.env` (`ADA_ADMIN_KEY`)
  - registry `~/.local/share/input-bridge/displays.json`
- Edge: tony-dell Caddy still owns `/api/input-bridge/*` and proxies it to
  `100.74.146.0:3010`, so all existing URLs (`/apps/vcast/`, the HA
  vcast-screens card, `/apps/input-bridge/` sender/receiver) are unchanged.
- Ada voice path: `VCAST_API=http://127.0.0.1:3010` is set in the idc01
  ada envs so vcast tools hit loopback.

## Install / update

```bash
# deps (once)
ssh idc01 'podman run --rm -v $HOME/apps/input-bridge:/app:Z -w /app \
  docker.io/library/node:22-alpine npm install ws --omit=dev'

# deploy a new server.mjs
scp stacks/web/input-bridge/server.mjs idc01:~/apps/input-bridge/server.mjs
ssh idc01 'systemctl --user restart input-bridge.service'

# smoke
ssh idc01 'curl -s http://127.0.0.1:3010/health'
curl -s https://tony-dell.taila0626a.ts.net/api/input-bridge/displays
```

## Notes

- `VCAST_REDEEM_HOSTS` must include `127.0.0.1,localhost` — the redeem URL is
  resolved relative to `ADA_AUTH_URL` (loopback on idc01).
- The relay binds `0.0.0.0:3010`; on idc01 that is tailnet + public VPS
  interface. `/pub` and `/claim` auth is enforced via the ada backend; there is
  no separate listener auth — same posture as before, now on the VPS.
- The former native unit (`systemd/input-bridge.service`) is kept as the
  non-podman fallback reference.
