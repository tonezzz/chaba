# Windsurf Playbook (this repo)

## Goals

- **Minimize time-to-signal**
  - Get from symptom to actionable evidence (logs, config, reproduction) fast.
- **Keep changes safe**
  - Small edits, reversible deploy actions, no secrets in code or chat.
- **Make knowledge durable**
  - Convert repeated steps into workflows and a small set of stable memories.

## Operating rules (how we work)

- **Start with acceptance criteria**
  - Define what “fixed” means as observable behavior.
- **Search before edit**
  - Use `code_search` for broad exploration.
  - Use `grep_search` for targeted symbol/string hits.
  - Use `read_file` to confirm before patching.
- **Prefer narrow patches**
  - Small `apply_patch` hunks that only touch necessary lines.
- **Single source of truth for “live config”**
  - Document effective ports/URLs/env vars in stack docs.
  - Avoid duplicating conflicting instructions.
- **No secrets**
  - Don’t store tokens/keys in workflows, docs, patches, or memories.

## Tooling map (what to use for what)

- **Code exploration**
  - `code_search`: find the right files/entrypoints.
  - `grep_search`: confirm exact strings, env var names, endpoints.
  - `read_file`: validate the current state.
- **Edits**
  - `apply_patch`: modify existing files.
  - `write_to_file`: create new docs/workflows (only when file doesn’t exist).
- **Runtime verification**
  - Prefer **Portainer MCP** for container/stack operations.
  - Prefer `dockerProxy` for logs when direct shell access isn’t needed.

## Skills (repeatable playbooks)

### 1) Fetch container logs via Portainer MCP

- **When**
  - Any runtime bug, 5xx, timeouts, crashes.
- **Inputs**
  - `environmentId` (local commonly `2`)
  - container name (or stack prefix)
  - tail count (e.g. 200/1000)
- **Outputs**
  - Timestamped logs (stdout+stderr)
  - Extracted “error clusters” with request context.

### 2) Redeploy stack safely

- **Stop/Start** (bounce)
  - Use for transient recovery or “apply runtime-only changes”.
- **Update stack** (apply compose/env changes)
  - Use for any compose edit or `.env` changes.
- **Always verify**
  - Service startup logs.
  - One golden-path request.

### 3) Weaviate + reminders triage

- **Checklist**
  - Weaviate container up/healthy.
  - Backend has correct `WEAVIATE_URL`.
  - Backend errors classify:
    - Weaviate unreachable vs schema vs embedding provider failure.
- **Golden path**
  - Create reminder.
  - List reminders.
  - Confirm persistence after restart.

### 4) Config sanity check (ports, URLs, env)

- **Goal**
  - Prevent “it works locally but not in stack” and avoid port conflicts.
- **Run**
  - Read stack compose + `.env` + docs.
  - Confirm published ports don’t collide.

### 5) GitHub Actions / CI status (preferred: `gh`)

- **Goal**
  - Track build status, pull failure logs, and confirm images were published before redeploy.
- **Rules**
  - Prefer `gh` over the web UI (faster + scriptable).
  - Never store PATs in repo files; authenticate locally via `gh auth login`.
- **Workflow**
  - Use: `.windsurf/workflows/check-github-actions-status.md`
- **Quick commands**
  - `gh run list --repo tonezzz/chaba --workflow "Publish (idc1-assistance)" --limit 10`
  - `gh run view <RUN_ID> --repo tonezzz/chaba --log-failed`

### 6) Hands-off deploy loop (whole stack, min downtime)

- **Goal**
  - Deploy with one command:
    - wait for CI publish
    - pull images
    - redeploy via Portainer (authoritative env), only when image IDs changed
    - verify health
- **Rules**
  - Prefer the host-side script when you are on the Docker host.
  - Portainer stack env is authoritative; do not expect host `docker compose up` to apply Portainer-only env.
  - Portainer CE HTTP API is commonly `http://127.0.0.1:9000` on the host (different from MCP bundle URL).
  - Redeploy only when image IDs changed (min downtime).
- **Workflow**
  - Use: `.windsurf/workflows/run-deploy-idc1-assistance-script.md`
- **Script**
  - `scripts/deploy-idc1-assistance.sh`

## Diagnostics standards (make failures cheap)

- **Structured logging fields (recommended)**
  - `request_id`, `user_id`, `tool_name`, `duration_ms`
  - `weaviate_status`, `weaviate_error`
  - `embedding_provider`, `embedding_status`
- **Health endpoints (recommended)**
  - `/healthz`: process is alive
  - `/readyz`: dependencies reachable (Weaviate, etc.)

## Workflows (what we should codify)

Create workflows only for repeatable operations that:

- take <2 minutes,
- have clear verification steps,
- avoid secrets.

Suggested workflows:

- **`/logs-idc1-assistance-backend`**
  - Fetch backend logs (last N lines).
- **`/redeploy-idc1-assistance`**
  - Update stack or restart, then verify.
- **`/run-deploy-idc1-assistance-script`**
  - True hands-off deploy loop on the Docker host (CI wait + pull + redeploy-only-if-changed + verify).
- **`/triage-reminders-weaviate`**
  - Collect backend + weaviate logs and run golden-path checks.
- **`/validate-portainer-mcp`**
  - Confirm `listLocalStacks` and (if enabled) one write operation.

## Memories (what to save)

Only persist stable facts:

- **Good**
  - Known endpoints/ports (non-secret), stack naming conventions, common gotchas.
- **Avoid**
  - Tokens/keys, container IDs, one-off debugging output.

## “Definition of done” templates

### Portainer MCP integration

- `listLocalStacks` works reliably.
- Read tools always available.
- Write tools enabled only when intended (e.g. `PORTAINER_READ_ONLY=0`).
- Redeploy workflow documented and repeatable.

### Reminders

- Creating a reminder succeeds.
- Listing reminders returns expected results.
- No Weaviate 5xx under normal load.
- Restart/redeploy does not lose reminders.
