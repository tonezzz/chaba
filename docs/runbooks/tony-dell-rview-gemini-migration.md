---
title: Tony-Dell RView + Gemini Live Migration Runbook
description: Move the rview-api and gemini-live backend services from tony-omen to tony-dell (rootless podman) while keeping the static UIs on chaba.h3 / tony-omen Caddy.
tags: [runbook, migration, tony-dell, podman, rview, gemini-live, quadlet]
created: 2026-08-20
updated: 2026-08-20
category: operations
related:
  - stacks/tony-dell/rview-api/rview-api.container
  - stacks/tony-dell/rview-api/rview-api-image.build
  - stacks/tony-dell/gemini-live/gemini-live.container
  - stacks/tony-dell/gemini-live/gemini-live-image.build
  - stacks/web/Caddyfile
  - chaba-h3/proxy-server.mjs
---

# Tony-Dell RView + Gemini Live Migration Runbook

Move the backend services for `rview` (`rview-api`) and `gemini-live` from `tony-omen` (Docker Compose) to `tony-dell` (rootless podman Quadlet). The static web UIs stay on `chaba.h3` / `tony-omen` Caddy; only the API upstreams move.

| Service | Old location | New location | Port |
|---------|--------------|--------------|------|
| `rview-api` | `tony-omen` Docker Compose | `tony-dell` rootless podman | `3007` |
| `gemini-live` | `tony-omen` Docker Compose | `tony-dell` rootless podman | `3008` |

`gemini-live` uses port `3008` because `mddb-panel` already occupies `3002` on `tony-dell`.

## Design highlights

- **Quadlet `.build` units** (`*-image.build`) rebuild images from the repo-root Dockerfiles on demand.
- **Quadlet `.container` units** pull in the build unit, run with `--network host`, and expose health checks.
- **`gemini-live` depends on `rview-api`** so systemd starts `rview-api` first.
- **`GEMINI_API_KEY` is injected from a Podman secret** (`gemini-api-key`) instead of a plain `.env` file.
- **`AutoUpdate=local`** lets `podman auto-update` restart the containers when the local image digest changes.
- Optional **Tailscale TCP serve** exposes `3007`/`3008` directly on the tailnet.

## Prerequisites

- `tony-dell` reachable via Tailscale (`tony-dell` / `100.68.142.13`).
- Rootless podman with Quadlet enabled (`systemd --user` generator) on `tony-dell`.
- `GEMINI_API_KEY` available.
- Repo cloned on `tony-dell` (e.g. `/home/tony/CascadeProjects/chaba` on the migration branch).

## Repo-side changes (already in this branch)

- `stacks/web/Caddyfile` proxies `/apps/rview/api/*` → `tony-dell:3007` and `/api/gemini-live/*` → `tony-dell:3008`.
- `stacks/web/docker-compose.yml` no longer defines `rview-api` or `gemini-live`.
- `stacks/web/rview-api/Dockerfile` and `stacks/web/gemini-live/Dockerfile` are repo-root build contexts and include `curl` for health checks.
- `stacks/tony-dell/rview-api/` and `stacks/tony-dell/gemini-live/` contain `.container`, `.build`, and `build.sh` files.
- `chaba-h3/proxy-server.mjs` defaults retargeted to `tony-dell`.
- SSOT docs updated.

## Tony-Dell host steps

### 1. Create state directory

```bash
ssh tony-dell
mkdir -p /home/tony/.local/share/rview-api
mkdir -p /home/tony/.config/containers/systemd
```

### 2. Copy Quadlet units

From the repo on `tony-dell`:

```bash
cd /home/tony/CascadeProjects/chaba
cp stacks/tony-dell/rview-api/rview-api.container \
   stacks/tony-dell/rview-api/rview-api-image.build \
   /home/tony/.config/containers/systemd/
cp stacks/tony-dell/gemini-live/gemini-live.container \
   stacks/tony-dell/gemini-live/gemini-live-image.build \
   /home/tony/.config/containers/systemd/
```

### 3. Create the Podman secret for Gemini API key

```bash
# Replace with the real key; do not commit this file.
printf '%s' 'YOUR_GEMINI_API_KEY_HERE' > /tmp/gemini-api-key.txt
podman secret create gemini-api-key /tmp/gemini-api-key.txt
rm -f /tmp/gemini-api-key.txt
```

Verify:

```bash
podman secret inspect gemini-api-key
```

### 4. Start the systemd user services

The first start also runs the `.build` units and creates the images.

```bash
systemctl --user daemon-reload
systemctl --user start rview-api gemini-live
systemctl --user enable rview-api gemini-live
systemctl --user status rview-api gemini-live
```

Check that the build units ran:

```bash
systemctl --user status rview-api-image gemini-live-image
```

### 5. Verify direct access on `tony-dell`

```bash
curl -s http://127.0.0.1:3007/state?action=list
curl -s http://127.0.0.1:3008/health
```

View logs if needed:

```bash
journalctl --user -u rview-api -n 50 --no-pager
journalctl --user -u gemini-live -n 50 --no-pager
```

### 6. Optional: expose via Tailscale TCP serve

```bash
tailscale serve --bg --tcp 3007 127.0.0.1:3007
tailscale serve --bg --tcp 3008 127.0.0.1:3008
```

Then the services are also reachable at `tony-dell.taila0626a.ts.net:3007` and `:3008`.

### 7. Rebuild images after a git update

Option A — use the `.build` units:

```bash
systemctl --user start rview-api-image gemini-live-image
systemctl --user restart rview-api gemini-live
```

Option B — manual build fallback:

```bash
cd /home/tony/CascadeProjects/chaba
bash stacks/tony-dell/rview-api/build.sh
bash stacks/tony-dell/gemini-live/build.sh
systemctl --user restart rview-api gemini-live
```

Option C — use `podman auto-update` (restarts units when the local image digest changes):

```bash
podman auto-update --user
```

## Tony-Omen steps

### 1. Stop and remove the old containers

```bash
ssh tony-omen
cd /home/tony/CascadeProjects/chaba/stacks/web
docker compose --profile production stop rview-api gemini-live
docker compose rm -f rview-api gemini-live
docker rmi rview-api:latest gemini-live:latest 2>/dev/null || true
```

### 2. Validate and reload Caddy

```bash
cd /home/tony/CascadeProjects/chaba/stacks/web
caddy validate --config Caddyfile
docker compose reload caddy
# or
docker compose restart caddy
```

### 3. Test through Caddy

```bash
curl -s http://tony-omen.local:8080/apps/rview/api/state?action=list
curl -s http://tony-omen.local:8080/api/gemini-live/health
```

## chaba.h3 steps

The `chaba.h3` Node proxy server (`proxy-server.mjs`) already defaults to `tony-dell:3007` / `tony-dell:3008` in this branch. Restart the app so the new defaults take effect:

```bash
ssh <chaba-h3-host>
cd /path/to/chaba-h3
# however the Plesk/Node process is managed, e.g.
npm restart
# or kill and restart the process
```

If you need to override without redeploying, set env vars before starting:

```bash
export RVIEW_API_URL=http://tony-dell:3007
export GEMINI_LIVE_API_URL=http://tony-dell:3008
node proxy-server.mjs
```

### Test chaba.h3 proxy

```bash
curl -s https://chaba.h3.gizmo-thailand.com/apps/rview/api/state?action=list
curl -s https://chaba.h3.gizmo-thailand.com/api/gemini-live/health
```

## Verification checklist

- [ ] `podman secret inspect gemini-api-key` shows the secret.
- [ ] `systemctl --user status rview-api-image gemini-live-image` shows the builds succeeded.
- [ ] `curl http://tony-dell:3007/state?action=list` returns JSON.
- [ ] `curl http://tony-dell:3008/health` returns JSON.
- [ ] `curl http://tony-omen.local:8080/apps/rview/api/state?action=list` returns JSON.
- [ ] `curl http://tony-omen.local:8080/api/gemini-live/health` returns JSON.
- [ ] `curl https://chaba.h3.gizmo-thailand.com/apps/rview/api/state?action=list` returns JSON.
- [ ] `curl https://chaba.h3.gizmo-thailand.com/api/gemini-live/health` returns JSON.
- [ ] `gemini-live` can call `rview_show` end-to-end (open the UI, start a session, and confirm the remote view updates).

## Rollback

1. On `tony-dell`:
   ```bash
   systemctl --user stop rview-api gemini-live rview-api-image gemini-live-image
   ```
2. On `tony-omen`: restore the `rview-api` and `gemini-live` service blocks in `stacks/web/docker-compose.yml`, then `docker compose --profile production up -d`.
3. Revert `stacks/web/Caddyfile` to proxy to the local service names.
4. Revert `chaba-h3/proxy-server.mjs` defaults to `tony-omen.local`.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rview-api` not listening | State dir missing or image not built | Create `/home/tony/.local/share/rview-api`; run `systemctl --user start rview-api-image rview-api` |
| `gemini-live` cannot spawn `mcp_rview/server.py` | `scripts/mcp_rview` not copied into image | Run `systemctl --user start gemini-live-image && systemctl --user restart gemini-live` |
| `gemini-live` health fails | Missing `GEMINI_API_KEY` or `rview-api` not ready | Verify `podman secret inspect gemini-api-key`; check `rview-api` is running |
| Caddy returns 502 | `tony-dell` hostname not resolving | Use `100.68.142.13:3007` / `100.68.142.13:3008` in Caddy or `/etc/hosts` |
| `chaba.h3` still proxies to old host | Old process cached defaults | Restart the `chaba.h3` Node process or set env overrides |
| Health check fails inside container | `curl` not in image | The Dockerfiles install `curl`; rebuild the image |
