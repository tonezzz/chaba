# idc1-webtop

This stack provides browser-accessible Linux desktop "webtop" sessions (LinuxServer Webtop) with a lightweight control plane:

- `webtops-cp`: simple admin UI (served under `/cp/`) to create/list/stop/delete sessions
- `mcp-webtops`: session manager API that creates Docker containers/volumes for sessions
- `webtops-router`: routes `/webtop/<session_id>/` traffic to the correct session container

It supports multiple **profiles** (e.g. `windsurf`, `claude`) which select different session images and environment.

## High level architecture

- **Control panel** (`webtops-cp`) calls `mcp-webtops` via `POST /invoke`.
- **Session manager** (`mcp-webtops`) creates a Docker container for each session:
  - container name: `webtops-sess-<session_id>`
  - attached to Docker network: `idc1-stack-net` (configurable via `WEBTOPS_DOCKER_NETWORK`)
  - a dedicated Docker volume is created per session for persistence (typically mounted at `/config` by LinuxServer Webtop)
- **Router** (`webtops-router`) maintains a state file mapping `session_id -> container upstream` and reverse proxies requests.
- **Caddy (outside this repo)** terminates TLS and forwards:
  - `/webtop/*` -> `webtops-router`
  - `/cp/*` -> `webtops-cp` (usually protected by BasicAuth)

### Networks

This stack expects these Docker networks to already exist (external):

- `idc1-web-net`: for the webtop control-plane services
- `idc1-stack-net`: where session containers are created (router is attached here too so it can reach sessions)

### Volumes

- `webtops_workspaces`: shared workspaces mounted into sessions at `WEBTOPS_WORKSPACES_MOUNT_PATH` (default `/workspaces`)
- `webtops_windsurf_cache`: optional cache volume for Windsurf downloads
- Per-session volumes are created dynamically by `mcp-webtops` (session persistence)

## Services

### `webtops-router`

- Listens on `WEBTOPS_ROUTER_PORT` (default 3001)
- Routes requests under `WEBTOPS_BASE_PATH` (default `/webtop`)
- Must be connected to **both** `idc1-web-net` and `idc1-stack-net`

### `mcp-webtops`

- Listens on `MCP_WEBTOPS_PORT` (default 8091)
- Requires access to Docker:
  - `/var/run/docker.sock:/var/run/docker.sock`
- Key settings:
  - `WEBTOPS_PUBLIC_BASE_URL`: public base URL used when returning `access_url` for a session
  - `WEBTOPS_ROUTER_BASE_URL`: internal URL to the router (`http://webtops-router:3001`)
  - `WEBTOPS_DOCKER_NETWORK`: network to attach session containers to (must be the external network name)

### `webtops-cp`

- Listens on `WEBTOPS_CP_PORT` (default 3005)
- BasicAuth is enforced by the app itself (`WEBTOPS_CP_USERNAME` / `WEBTOPS_CP_PASSWORD`)
- Proxies actions to `mcp-webtops`

## Profiles

Profiles are selected in the control panel when creating a session.

- `default`
  - image: `WEBTOPS_SESSION_IMAGE` (default `lscr.io/linuxserver/webtop:latest`)
- `windsurf`
  - image: `WEBTOPS_SESSION_IMAGE_WINDSURF`
  - uses Windsurf-related env vars (`WEBTOPS_WINDSURF_VERSION`, `WEBTOPS_WINDSURF_DEB_URL_TEMPLATE`, etc.)
- `claude`
  - image: `WEBTOPS_SESSION_IMAGE_CLAUDE` (default `ghcr.io/tonezzz/webtops-claude:latest`)
  - passes `ANTHROPIC_API_KEY` into the session container

## Portainer deployment notes

- Prefer setting environment variables in Portainer rather than relying on `env_file`.
- If you deploy via Git in Portainer, make sure required values are not blank:
  - `WEBTOPS_CP_PASSWORD`
  - `WEBTOPS_ADMIN_TOKEN`
  - `WEBTOPS_ROUTER_ADMIN_TOKEN`

## Troubleshooting / gotchas

### Control panel list goes empty after create/refresh

If `mcp-webtops` is slow (image pull, container create), `webtops-cp` can time out while calling `list_sessions`.

- Newer `webtops-cp` versions increase the upstream timeout and return a clearer error instead of a blank screen.

### Claude Code `EACCES: permission denied, open` (appendFileSync)

Symptom: Claude Code fails writing under `/config` (state/logs) due to ownership mismatch.

Fix:

- Newer `webtops-claude` image includes a `cont-init.d` script to `chown` Claude state dirs under `/config` to the runtime user (`abc`) on every container start.

If you hit it on an existing session volume, the quick workaround is:

```sh
docker exec -u root <session_container> sh -lc 'chown -R abc:abc /config/.claude /config/.cache/claude /config/.local/state/claude /config/.claude.json* || true'
```

### noVNC / Webtop terminal: Enter key does not confirm

Some noVNC/browser focus combinations can cause the Enter key not to be delivered to terminal TUIs.

Workarounds:

- Click inside the terminal area to ensure focus is captured.
- Use the noVNC side panel to **Send Enter**.
- If a browser window auto-opens inside the desktop and steals focus, close it and retry.

### GitHub Actions build failures mentioning submodules

If Actions shows `fatal: No url found for submodule path ... in .gitmodules`, the repo has a gitlink (mode `160000`) without a proper `.gitmodules` entry.

Fix:

- Add/update `.gitmodules` with correct `path` + `url` for that submodule.

## What to avoid

- Do not set placeholder or empty admin tokens/passwords for CP/router; it leads to confusing behavior.
- Do not attach the router to only one network; it must be on `idc1-stack-net` to reach session containers.
- Avoid printing secrets (`ANTHROPIC_API_KEY`, admin tokens) in logs/terminal output; rotate if accidentally exposed.
