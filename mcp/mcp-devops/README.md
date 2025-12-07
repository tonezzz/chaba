# mcp-devops

Model Context Protocol (MCP) server that turns the existing Chaba preview and publish scripts into hands-off workflows. It exposes structured MCP tools so Claude Desktop—or any MCP-capable client—can list available workflows and trigger them with one call.

## Features

- **Preview automation**: boots the dev-host stack, PM2 services, and validates `/test` routes (detects/chat/agents/vaja) via the existing PowerShell scripts.
- **Publish orchestration**: wraps `scripts/deploy-a1-idc1.sh` through WSL so remote rsync + release promotion stay consistent with today’s manual runbook.
- **Workflow catalog**: discoverable metadata (description, tags, URLs) so agents can pick the right workflow before running anything.
- **Dry-run support**: request the exact command that would run (with rendered env/args) without touching the system.

## Getting started

```bash
cd mcp/mcp-devops
npm install
npm run start
```

The server reads the repository `.env` plus the env vars documented below. By default it binds to `0.0.0.0:8320`.

### Suggested env vars

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEV_HOST_BASE_URL` | `http://dev-host.pc1:3000` | Local preview base for `/test/*` routes. |
| `DEV_HOST_PC2_BASE_URL` | `http://dev-host.pc2:3000` | PC2 proxy base, used by the VAJA preview workflow. |
| `A1_DEPLOY_SSH_USER` | `chaba` | Remote SSH user for production deploys. |
| `A1_DEPLOY_SSH_HOST` | `a1.idc-1.surf-thailand.com` | Remote host for deploys. |
| `A1_DEPLOY_REMOTE_BASE` | `/www/a1.idc-1.surf-thailand.com` | Remote releases root. |
| `A1_DEPLOY_SSH_KEY_PATH` | `<repo>/.secrets/dev-host/.ssh/chaba_ed25519` | Private key used during deploy (read from Windows side). |
| `A1_DEPLOY_ENV_DIR` | `<repo>/.secrets/dev-host` | Location of `.env` bundles pushed to the server. |
| `MCP_DEVOPS_PORT` | `8320` | HTTP port for the MCP server. |
| `MCP_DEVOPS_POWERSHELL` | _(auto)_ | Override the PowerShell executable (defaults to `powershell.exe` on Windows / `pwsh` elsewhere). |

Copy `.env.example` to `.env` inside `mcp-devops` if you want repo-local overrides:

```bash
cp .env.example .env
```

## MCP tools

| Tool | Description |
| --- | --- |
| `list_workflows` | Returns id/label/description/tags/output hints for every registered workflow. |
| `run_workflow` | Executes a workflow by id, optionally in `dry_run` mode and with extra params. Returns logs, exit code, and preview URL hints. |

### Imagen GPU preview workflow

The Imagen stack now lives under `stacks/pc2-worker` and can be brought up (plus smoke-tested) with the `scripts/preview-imagen.ps1` runner. This workflow:

1. Ensures Docker Desktop is available, then runs `docker compose --profile mcp-suite up -d dev-proxy mcp-imagen-gpu`.
2. Waits for `http://127.0.0.1:8001/health` to return `status: ok`.
3. Issues a low-cost `/generate` POST (default: 256×256, 6 steps) to catch regressions before touching the UI.

Manual usage:

```powershell
pwsh ./scripts/preview-imagen.ps1 `
  -DevHostBaseUrl http://dev-host.pc1/test/imagen `
  -ImagenHealthUrl http://127.0.0.1:8001/health `
  -ImagenGenerateUrl http://127.0.0.1:8001/generate
```

Through MCP, call `run_workflow` with `workflow_id: "preview-imagen"` (see `src/workflowCatalog.js`). On success, the workflow returns the health URL plus the dev-host target (`http://dev-host.pc1/test/imagen/` once the UI is deployed under `/www/test/imagen`).

### PC2 Docker control (native WSL engine)

The pc2 stack workflows (`pc2-stack-status`, `pc2-stack-up`, `pc2-stack-down`) now assume the Docker daemon inside the PC2 WSL distro is exposed via `unix:///var/run/docker.sock`. Make sure the native Docker Engine is installed and running _inside_ that distro (not via Docker Desktop sockets). A good reference is [How to install Docker in WSL without Docker Desktop](https://daniel.es/blog/how-to-install-docker-in-wsl-without-docker-desktop/).

Required env entries (repo `.env` or process env) so MCP DevOps can SSH + talk to that socket:

| Variable | Purpose | Example |
| --- | --- | --- |
| `PC2_SSH_HOST` | Hostname/IP of the physical PC2 box. | `pc2` (hosts entry pointing to `192.168.1.43`) |
| `PC2_SSH_USER` | SSH user on PC2. | `chaba` |
| `PC2_SSH_KEY_PATH` | Path (WSL format) to the private key used for SSH. | `/home/tonezzz/.ssh/chaba_ed25519` |
| `PC2_STACKS_DIR` | Absolute path to the folder containing `pc2-worker`. | `/home/chaba/chaba/stacks` |
| `PC2_WORKER_DIR` | Directory name under `PC2_STACKS_DIR`. | `pc2-worker` |
| `PC2_DOCKER_HOST` | Docker socket to export before running compose commands. | `unix:///var/run/docker.sock` |

If `docker info` works via `ssh chaba@pc2 'DOCKER_HOST=unix:///var/run/docker.sock docker info'`, the workflows can run Docker Compose remotely.

### Example payloads

**List workflows**

```json
{ "tool": "list_workflows", "arguments": {} }
```

**Run detects preview**

```json
{
  "tool": "run_workflow",
  "arguments": {
    "workflow_id": "preview-detects"
  }
}
```

**Dry-run deploy**

```json
{
  "tool": "run_workflow",
  "arguments": {
    "workflow_id": "deploy-a1-idc1",
    "dry_run": true
  }
}
```

## Adding new workflows

1. Update `src/workflowCatalog.js` with a new entry (id, runner, script path, args, env).  
2. Restart the server (or run in watch mode via `npm run dev`).  
3. Use `list_workflows` to confirm metadata shows up, then `run_workflow` to test.

Each workflow entry keeps script knowledge centralized so new previews (agents-only, MCP stacks, etc.) can be added without more PowerShell wrappers.
