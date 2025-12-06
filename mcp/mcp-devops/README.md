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
