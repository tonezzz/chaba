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

## Next Steps
1. Create `~/stacks/pc2-worker/docker-compose.yml` with the profiles above.
2. Draft helper scripts:
   - `scripts/pc2-worker/start.sh --profile base-tools`
   - `scripts/pc2-worker/stop.sh`
3. Once GPU support is ready, add profile `"gpu"` to the compose file and test with a simple CUDA container.
