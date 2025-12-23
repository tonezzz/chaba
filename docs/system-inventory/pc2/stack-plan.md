# pc2 Worker Container Plan

## Goals
1. Keep reusable tooling containers on standby so delegated jobs start immediately.
2. Mirror key MCP services locally for integration testing before deployments.
3. Prepare for optional GPU workloads once WSL2 GPU pass-through is enabled.

## Directory Layout
```
~/stacks/pc2-worker/
├─ .env                   # shared secrets (paths only; real secrets from ~/.ssh/.env)
├─ docker-compose.yml     # master compose file
├─ base-tools/            # Dockerfiles or overrides for helper containers
├─ mcp-services/          # bind-mounted repos (voice_chat, etc.)
└─ data/                  # persistent volumes (Redis data, logs)
```

## Compose Profiles

### 1. base-tools
Purpose: provide ephemeral build/test helpers.

Services:
| Service | Image | Notes |
| --- | --- | --- |
| `node-runner` | `node:22-alpine` | mounts repo via `${HOST_REPO}`; installs deps via entry script. |
| `python-runner` | `python:3.11-slim` | includes Poetry/pipx; used for lint/tests. |
| `redis` | `redis:7-alpine` | optional cache for integration tests. |

Common settings:
- `profiles: [base-tools]`
- Shared network `pc2-worker-net`.
- Bind-mount SSH agent socket for private repo access (via `SSH_AUTH_SOCK`).

### 2. mcp-suite
Purpose: run voice_chat MCP services locally.

Services:
| Service | Build/Image | Ports |
| --- | --- | --- |
| `mcp-github` | build from `voice_chat/mcp/mcp-github/Dockerfile` | `localhost:7201` |
| `mcp-memory` | build from `voice_chat/mcp/mcp-memory/Dockerfile` | `localhost:7202` |
| `mcp-vaja` | `voice_chat-mcp-vaja` image (from repo) | `localhost:7203` |
| `mcp-meeting` | build from `voice_chat/mcp/mcp-meeting/Dockerfile` | `localhost:7204` |
| `ngrok`/`localtunnel` | existing tunnel images for external callbacks. |
| `dev-proxy` | `caddy:2-alpine` or `nginx:stable-alpine` to reverse-proxy everything. |

Notes:
- Add `profiles: [mcp-suite]`.
- Mount repo directories read-only; secrets injected via `.env` file referencing `~/.secrets`.
- Provide healthchecks hitting `/health` endpoints.

### 3. gpu-inference (future)
Purpose: host inference workloads once GPU passthrough is configured.

Service template:
```yaml
inference:
  image: nvidia/cuda:12.2.0-base-ubuntu20.04
  profiles: ["gpu"]
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: ["gpu"]
  volumes:
    - ${HOST_MODEL_DIR:-/srv/models}:/models:ro
  command: ["bash", "-c", "sleep infinity"]
```

Prereqs:
- Enable WSL GPU support in Docker Desktop.
- Install NVIDIA drivers on host + `nvidia-container-toolkit` inside WSL.

## Operational Notes
1. **Env management**: use `/home/chaba/.env` with `dotenv-cli`; do not commit secrets.
2. **Startup**: `docker compose --profile base-tools up -d`, etc.
3. **Cleanup**: `docker compose down` followed by `docker system prune -af` (already scripted).
4. **Monitoring**: `node-exporter`/`cAdvisor` require shared-mount access to `/`. WSL2 defaults prevent this, so keep the `monitoring` profile disabled for now; revisit when we run these containers on a native Linux host or enable `mount --make-rshared /`.
5. **Backups**: persist volumes under `~/stacks/pc2-worker/data`; snapshot via `tar czf backups/pc2-worker-data-$(date +%Y%m%d).tgz data/`.

## 1MCP Agent (pc2-worker)

The `1mcp-agent` service aggregates multiple MCP backends (currently `filesystem` + `docker`) behind a single HTTP endpoint.

### Start

From `stacks/pc2-worker/`:

- `docker compose --profile mcp-suite up -d --build 1mcp-agent`

### Verify

- OAuth/status dashboard:
  - `http://127.0.0.1:3050/oauth`
- Both `filesystem` and `docker` should show as `Connected`.

Note: the agent starts in a synchronous loading mode and may take ~30-90s on first boot while `docker-mcp` initializes.

### Windsurf

Point Windsurf at the aggregated endpoint (example):

- `C:\Users\Admin\.codeium\windsurf\mcp_config.json`
  - `url: http://127.0.0.1:3050/mcp?app=windsurf`

### Secret Management Workflow (pc2-worker)
1. **Authoritative template**: `stacks/pc2-worker/.env.example` stays in git with `__REPLACE_ME__` placeholders.
2. **Private overrides**: create an untracked file such as `stacks/pc2-worker/.env.local` or a secrets bundle (`.secrets/.env/tony.env`) containing real values (MCP0 admin token, API keys, etc.).
3. **Sync helper**: run `pwsh ./scripts/pc2-worker/sync-env.ps1 -SourcePath <path-to-private-env>` before invoking any compose workflow.  
   - The script copies the env file over WSL SSH/SCP to `/home/chaba/chaba/stacks/pc2-worker/.env` and enforces secure permissions.
   - If `PC2_STACK_ENV_SOURCE` is set (for example to `c:\chaba\.secrets\.env\tony.env`), the `-SourcePath` flag is optional.
4. **Automations**: MCP DevOps workflows (e.g., `pc2-compose-stop-all`, `pc2-compose-rebuild-vaja`) should call the sync helper first to ensure PC2 has the latest secrets. This allows operator assistants like **Dever** to:
   - Detect stale envs by comparing `.env.example` vs. the synced `.env`.
   - Suggest credential rotations or new provider entries (e.g., for additional MCP agents) before triggering compose-control.
   - Propose creating new agents by appending env keys + `MCP0_PROVIDERS` entries via the same templated workflow, then re-running `sync-env.ps1` and the relevant compose command.

5. **MCP0 providers (pc1 + pc2)**:
   - Keep `MCP0_PROVIDERS` in your private `.env.local` aligned with `stacks/pc2-worker/.env.example`. Each entry follows `name:base_url|health=/health|capabilities=/.well-known/mcp.json|tools=...`.
   - Register both `mcp-agents-pc1` and `mcp-agents-pc2`, pointing at `https://dev-host.pc1/test/agents/api` and `https://dev-host.pc2/test/agents/api` respectively. Include `relay_prompt` in their `tools` list so Cascade can forward Dever prompts through either host.
   - After updating secrets, rerun `scripts/pc2-worker/sync-env.ps1` and trigger a MCP0 refresh (e.g., restart the service or hit the admin `/providers/refresh` workflow) to propagate new providers to MCP clients.

> **Tip for Dever**: incorporate a “sync secret env” step into any pc2 automation plan. If the helper reports missing secrets, prompt the operator to update their private env file, then retry. This keeps MCP0 credentials and agent definitions consistent across the repo, the local machine, and PC2.

## Next Steps
1. Create `~/stacks/pc2-worker/docker-compose.yml` with the profiles above.
2. Draft helper scripts:
   - `scripts/pc2-worker/start.sh --profile base-tools`
   - `scripts/pc2-worker/stop.sh`
3. Once GPU support is ready, add profile `"gpu"` to the compose file and test with a simple CUDA container.
