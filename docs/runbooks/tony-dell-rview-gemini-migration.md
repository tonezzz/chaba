---
title: Tony-Dell RView + Gemini Live Migration Runbook
description: Move the rview-api and gemini-live backend services from tony-omen to tony-dell (rootless podman) while keeping the static UIs on chaba.h3 / tony-omen Caddy.
tags: [runbook, migration, tony-dell, podman, rview, gemini-live, quadlet]
created: 2026-08-20
updated: 2026-08-20
category: operations
related:
  - stacks/tony-dell/rview-api/rview-api.container
  - stacks/tony-dell/gemini-live/gemini-live.container
  - stacks/web/Caddyfile
  - chaba-h3/proxy-server.mjs
---

# Tony-Dell RView + Gemini Live Migration Runbook

Move the backend services for `rview` (`rview-api`) and `gemini-live` from `tony-omen` to `tony-dell`.
The static web UIs stay on `chaba.h3` / `tony-omen` Caddy; only the APIs move.

| Service | Old location | New location | Port |
|---------|--------------|--------------|------|
| `rview-api` | `tony-omen` Docker Compose | `tony-dell` rootless podman | `3007` |
| `gemini-live` | `tony-omen` Docker Compose | `tony-dell` rootless podman | `3008` |

`gemini-live` uses port `3008` because `mddb-panel` already occupies `3002` on `tony-dell`.

## Prerequisites

- `tony-dell` reachable via Tailscale (`tony-dell` / `100.68.142.13`).
- Rootless podman and `quadlet` configured on `tony-dell` (`systemd --user` generator enabled).
- `GEMINI_API_KEY` available for `gemini-live`.
- Repo cloned on `tony-dell` (e.g. `/home/tony/CascadeProjects/chaba` on the `master` or migration branch).

## Repo-side changes (already in this branch)

- `stacks/web/Caddyfile` proxies `/apps/rview/api/*` to `tony-dell:3007` and `/api/gemini-live/*` to `tony-dell:3008`.
- `stacks/web/docker-compose.yml` no longer defines `rview-api` or `gemini-live`.
- `stacks/tony-dell/rview-api/` and `stacks/tony-dell/gemini-live/` contain `Containerfile`, `.container` quadlet unit, and `build.sh`.
- `chaba-h3/proxy-server.mjs` defaults updated to `http://tony-dell:3007` and `http://tony-dell:3008`.
- SSOT docs updated under `docs/ssot/infrastructure/`.

## Tony-Dell host steps

### 1. Create state and secrets directories

```bash
ssh tony-dell
mkdir -p /home/tony/.local/share/rview-api
mkdir -p /home/tony/.config/containers/systemd
```

### 2. Copy quadlet units

From the repo on `tony-dell`:

```bash
cd /home/tony/CascadeProjects/chaba
cp stacks/tony-dell/rview-api/rview-api.container \
   /home/tony/.config/containers/systemd/
cp stacks/tony-dell/gemini-live/gemini-live.container \
   /home/tony/.config/containers/systemd/
```

### 3. Create the `gemini-live` environment file

```bash
cat > /home/tony/.config/containers/systemd/gemini-live.env <<EOF
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
EOF
chmod 600 /home/tony/.config/containers/systemd/gemini-live.env
```

### 4. Build images

```bash
cd /home/tony/CascadeProjects/chaba
bash stacks/tony-dell/rview-api/build.sh
bash stacks/tony-dell/gemini-live/build.sh
```

Both build from the repo root so they can copy `scripts/mcp_rview` into the `gemini-live` image.

### 5. Start the systemd user services

```bash
systemctl --user daemon-reload
systemctl --user start rview-api gemini-live
systemctl --user enable rview-api gemini-live
systemctl --user status rview-api gemini-live
```

### 6. Verify direct access on `tony-dell`

```bash
curl -s http://127.0.0.1:3007/state.php?action=list
curl -s http://127.0.0.1:3008/health
```

If `gemini-live` is not ready, check logs:

```bash
journalctl --user -u gemini-live -n 50 --no-pager
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
curl -s http://tony-omen.local:8080/apps/rview/api/state.php?action=list
curl -s http://tony-omen.local:8080/api/gemini-live/health
```

## chaba.h3 steps

The `chaba.h3` Node proxy server (`proxy-server.mjs`) already defaults to `tony-dell:3007` / `tony-dell:3008` in this branch.
Restart the app so the new defaults take effect:

```bash
ssh <chaba-h3-host>
cd /path/to/chaba-h3
# however the Plesk/Node process is managed, e.g.
npm restart
# or kill and restart the process
```

If you need to override without redeploying, set these env vars before starting the process:

```bash
export RVIEW_API_URL=http://tony-dell:3007
export GEMINI_LIVE_API_URL=http://tony-dell:3008
node proxy-server.mjs
```

### Test chaba.h3 proxy

```bash
curl -s https://chaba.h3.gizmo-thailand.com/apps/rview/api/state.php?action=list
curl -s https://chaba.h3.gizmo-thailand.com/api/gemini-live/health
```

## Verification checklist

- [ ] `curl http://tony-dell:3007/state.php?action=list` returns JSON.
- [ ] `curl http://tony-dell:3008/health` returns JSON.
- [ ] `curl http://tony-omen.local:8080/apps/rview/api/state.php?action=list` returns JSON.
- [ ] `curl http://tony-omen.local:8080/api/gemini-live/health` returns JSON.
- [ ] `curl https://chaba.h3.gizmo-thailand.com/apps/rview/api/state.php?action=list` returns JSON.
- [ ] `curl https://chaba.h3.gizmo-thailand.com/api/gemini-live/health` returns JSON.
- [ ] `gemini-live` can call `rview_show` end-to-end (open the UI, start a session, and confirm the remote view updates).

## Rollback

1. On `tony-dell`: `systemctl --user stop rview-api gemini-live`
2. On `tony-omen`: restore the `rview-api` and `gemini-live` service blocks in `stacks/web/docker-compose.yml`, then `docker compose --profile production up -d`.
3. Revert `stacks/web/Caddyfile` to proxy to the local service names.
4. Revert `chaba-h3/proxy-server.mjs` defaults to `tony-omen.local`.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rview-api` not listening | State dir missing or image not built | Create `/home/tony/.local/share/rview-api`; re-run `build.sh` |
| `gemini-live` cannot spawn `mcp_rview/server.py` | `scripts/mcp_rview` not copied into image | Re-run `stacks/tony-dell/gemini-live/build.sh` from repo root |
| `gemini-live` health fails | Missing `GEMINI_API_KEY` | Verify `/home/tony/.config/containers/systemd/gemini-live.env` and reload |
| Caddy returns 502 | `tony-dell` hostname not resolving | Use `100.68.142.13:3007` / `100.68.142.13:3008` in Caddy or `/etc/hosts` |
| `chaba.h3` still proxies to old host | Old process cached defaults | Restart the `chaba.h3` Node process or set env overrides |
