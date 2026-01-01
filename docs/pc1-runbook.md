# PC1 Stack Runbook

This runbook describes how to operate the **split PC1 Docker Compose stacks** after the separation into:

- `pc1-db` (datastores)
- `pc1-gpu` (GPU/CUDA)
- `pc1-ai` (AI gateways + Ollama + Imagen adapter)
- `pc1-devops` (DevOps automation)
- `pc1-web` (web UI + ingress + dev-host)
- `pc1-stack` (core MCP services)
- `pc1-deka` (DEKA scraper)

## Preconditions

- **Docker Desktop** running
- Prefer the repo scripts under `scripts/` for stack lifecycle (`pc1-*.ps1`, `pc1-start-all-stacks.ps1`, `pc1-stop-all-stacks.ps1`).
- The generic runner `scripts/stack.ps1` uses `docker compose` when available and falls back to `docker-compose`.
- VPN DNS `pc1.vpn` resolves correctly from containers/host where used

## Environment Files

Each stack expects its own `.env` (copy from `.env.example`):

- `stacks/pc1-db/.env`
- `stacks/pc1-gpu/.env`
- `stacks/pc1-ai/.env`
- `stacks/pc1-devops/.env`
- `stacks/pc1-web/.env`
- `stacks/pc1-stack/.env`
- `stacks/pc1-deka/.env` (if used)

## Start Order (recommended)

Start in dependency order so downstream services can connect immediately:

1. **pc1-db**
2. **pc1-gpu**
3. **pc1-ai**
4. **pc1-devops**
5. **pc1-web**
6. **pc1-stack**
7. **pc1-deka** (optional)

### Commands

Preferred: use the scripts (recommended):

```powershell
# Start all stacks (recommended order)
scripts/pc1-start-all-stacks.ps1

# Stop all stacks
scripts/pc1-stop-all-stacks.ps1

# Stop and remove volumes
scripts/pc1-stop-all-stacks.ps1 -RemoveVolumes
```

Alternative: run from each stack directory:

```bash
# pc1-db
stacks/pc1-db

docker-compose up -d

# pc1-gpu
stacks/pc1-gpu

docker-compose up -d

# pc1-ai
stacks/pc1-ai

docker-compose up -d

# pc1-devops
stacks/pc1-devops

docker-compose up -d

# pc1-web
stacks/pc1-web

docker-compose up -d

# pc1-stack (core)
stacks/pc1-stack

docker-compose --profile mcp-suite up -d

# pc1-deka (optional)
stacks/pc1-deka

docker-compose up -d
```

## Stop Order (recommended)

Stop in reverse order:

1. **pc1-deka** (if running)
2. **pc1-stack**
3. **pc1-web**
4. **pc1-devops**
5. **pc1-ai**
6. **pc1-gpu**
7. **pc1-db**

Example:

```bash
# from each stack directory

docker-compose down
```

## Health Checks / Smoke Tests

### Core (pc1-stack)
- **1mcp-agent**: `http://127.0.0.1:3051/health`
- **mcp-agents**: `http://127.0.0.1:8046/health`
- **mcp-http**: `http://127.0.0.1:8067/health`
- **mcp-task**: `http://127.0.0.1:8016/health`
- **mcp-playwright**: `http://127.0.0.1:8260/health`
- **mcp-quickchart**: `http://127.0.0.1:8251/health`
- **mcp-tester**: `http://127.0.0.1:8335/health`

### Web (pc1-web)
- **OpenChat UI**: `http://127.0.0.1:3170/`
- **Caddy health**: `http://127.0.0.1:3080/health`
- **Dev-host** (host-mapped): `http://127.0.0.1:3100/health`

Note: `pc1-stack` references `dev-host` via `http://pc1.vpn:3100/...`.

### AI (pc1-ai)
- **mcp-openai-gateway**: `http://127.0.0.1:8181/health`
- **ollama**: TCP port open on `127.0.0.1:11435` (container 11434)
- **mcp-imagen-light**: `http://127.0.0.1:8020/health`
- **mcp-glama**: `http://127.0.0.1:7241/health` (if implemented)
- **mcp-github-models**: `http://127.0.0.1:7242/health` (if implemented)

### GPU (pc1-gpu)
- **mcp-cuda**: `http://127.0.0.1:8057/health`

### DB (pc1-db)
- **qdrant**: `http://127.0.0.1:6333/health`
- **mcp-rag**: `http://127.0.0.1:8055/health`
- **mcp-doc-archiver**: `http://127.0.0.1:8066/health`

## Common Issues

### 1) UI loads but chat fails
- Check `pc1-ai` is running.
- Verify `mcp-openai-gateway` reachable at `http://pc1.vpn:8181` from the host running the UI.
- Confirm `OPENCHAT_OPENAI_API_HOST` is set correctly in `pc1-web/.env`.

### 2) Agents backend can’t reach dev-host routes
- `pc1-stack` uses `AGENTS_API_BASE` defaulting to `http://pc1.vpn:3100/test/agents/api`.
- Ensure `pc1-web` dev-host exposes `3100:3000`.

### 3) Port conflicts
- Common ports to check on Windows:
  - 3080/3443 (Caddy)
  - 3170 (OpenChat UI)
  - 3100 (dev-host)
  - 3051 (1mcp-agent)
  - 8055/8066/6333 (DB stack)
  - 8181/11435/8020 (AI stack)

### 4) DNS / cross-stack connectivity
- Use `pc1.vpn` endpoints for cross-stack access.
- If a container must call a service in another stack, it must target a **host-reachable address** (e.g., `pc1.vpn:<port>`).

## Quick “All Green” Checklist

- `pc1-db` health endpoints respond
- `pc1-gpu` `/health` responds
- `pc1-ai` gateway + imagen `/health` respond
- `pc1-web` UI loads and `dev-host` `/health` responds
- `pc1-stack` core services `/health` respond

## Notes

- `pc1-stack/.env.example` was pruned to only include vars still used by `pc1-stack`.
- `pc1-stack/1mcp.json` was pruned to only register services still running in `pc1-stack`.
