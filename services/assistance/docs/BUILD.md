 # BUILD / DEPLOY (Single Source of Truth)

This file is the single source of truth for how we:
- trigger **GHCR auto rebuilds** from this repo
- **redeploy** the `idc1-assistance` stack via **Portainer**
- verify we are actually running the **latest image digest** (not just the tag)
- debug the common "I redeployed but it’s still old" failure mode

See also:
- `WINDSURF_PLAYBOOK.md` (repo working conventions, diagnostics, workflows)

## TL;DR

- Push to branch `idc1-assistance`.
- Wait for GitHub Actions to publish new GHCR images.
- In Portainer, redeploy the stack with **pull latest images** enabled.
- Verify the running container uses a new **IMAGE ID**.

Notes:

- GitHub Actions publishes images **selectively** (only the images whose inputs changed).

## Copy/paste message template (improved)

Use this message when you want the “push -> auto rebuild -> redeploy” loop:

```text
Please push the latest changes to branch `idc1-assistance` to trigger the GHCR auto rebuild.

After the GH Actions build completes, redeploy the stack in Portainer with “always pull latest image / re-pull image” enabled.

Finally verify the running containers are using the new image digest (IMAGE ID changed), not just the same tag.
```

## Repo + branch conventions

- Deployment branch: `idc1-assistance`
- Images are published to GHCR (examples):
  - `ghcr.io/tonezzz/chaba/jarvis-backend:idc1-assistance`
  - `ghcr.io/tonezzz/chaba/jarvis-frontend:idc1-assistance`

Operational rule:
- **A Portainer redeploy must pull the latest digest.** If it doesn’t, you’ll keep running old code.

## Workflow: change -> rebuild -> redeploy

### 1) Make code changes

Application code lives under:
- `services/assistance/jarvis-backend/`
- `services/assistance/jarvis-frontend/`
- `services/assistance/mcp-*`

Deployment configuration lives under:
- `stacks/idc1-assistance/`

### 2) Commit + push to `idc1-assistance`

```bash
git checkout idc1-assistance
git status --porcelain
git add <files>
git commit -m "<message>"
git push
```

### 2.1) Forcing a rebuild

Important:

- CI now builds/pushes images **only when their inputs change**.
- An empty commit (`git commit --allow-empty ...`) typically produces **no changed files**, so it will usually **not** rebuild any images.

If you need to force a rebuild (without functional code changes), use one of these:

- Touch a file inside the service context you want to rebuild (preferred):

```bash
date > services/assistance/jarvis-backend/.ci-rebuild
git add services/assistance/jarvis-backend/.ci-rebuild
git commit -m "ci: force jarvis-backend rebuild"
git push
```

- Or modify the workflow file to force rebuild-all (heavier):
  - `.github/workflows/publish-idc1-assistance.yml`

Current selective-build rules (high level):

- `jarvis-backend` rebuilds on changes under `services/assistance/jarvis-backend/`
- `jarvis-frontend` rebuilds on changes under `services/assistance/jarvis-frontend/`
- `web-fetcher` rebuilds on changes under `services/assistance/web-fetcher/`
- `deep-research-worker` rebuilds on changes under `services/assistance/deep-research-worker/`
- `mcp-image-pipeline` rebuilds on changes under `services/assistance/mcp-image-pipeline/`
- `mcp-bundle` rebuilds on changes under:
  - `services/assistance/mcp-bundle/`
  - `services/assistance/mcp-servers/mcp-google-sheets/server.js`

### 3) Wait for GitHub Actions

Expected:
- CI builds and pushes updated `:idc1-assistance` images to GHCR.

If the build fails:
- fix CI first; redeploying won’t change anything.

### 4) Redeploy via Portainer

### A) Confirm IMAGE ID changed (digest-level)

On the host (or wherever Docker CLI is available):

```bash
docker compose -f stacks/idc1-assistance/docker-compose.yml ps
docker compose -f stacks/idc1-assistance/docker-compose.yml images
```

You want to see:
- `IMAGE ID` changed for the service you rebuilt (e.g. `jarvis-frontend`, `jarvis-backend`).

### A.1) Git-backed Portainer stack vs local Docker Compose

If `idc1-assistance` is deployed as a **Portainer git-backed stack**, treat Portainer as authoritative for:
- Stack file content
- Stack environment variables (secrets like OAuth client IDs)

Common trap:
- Running `docker compose -f stacks/idc1-assistance/docker-compose.yml up ...` locally can create containers that look identical but do **not** include the Portainer stack env.
- You can end up with multiple `mcp-bundle` containers (example: `idc1-assistance-mcp-bundle-1` plus a separate `idc1-portainer-mcp-bundle-1`).

When debugging "missing env" (example: `missing_google_tasks_client_id`):

```bash
docker ps --format '{{.Names}}' | grep -E 'mcp-bundle' || true
docker exec -t idc1-assistance-mcp-bundle-1 sh -lc 'echo "GOOGLE_TASKS_CLIENT_ID.len=${#GOOGLE_TASKS_CLIENT_ID}"'
```

To run one-time OAuth bootstrap inside the running `mcp-bundle`:

```bash
docker exec -t idc1-assistance-mcp-bundle-1 node /app/mcp-servers/mcp-google-tasks/server.js auth
```

### B) Confirm frontend bundle contains the fix you expect

When debugging “frontend still old”, it’s often easier to grep the served JS bundle than to guess.

```bash
docker compose -f stacks/idc1-assistance/docker-compose.yml exec -T jarvis-frontend sh -lc 'ls -1 /usr/share/nginx/html/assets | head'
docker compose -f stacks/idc1-assistance/docker-compose.yml exec -T jarvis-frontend sh -lc 'grep -R "Do not treat these as transport disconnects" -n /usr/share/nginx/html 2>/dev/null | head'
```

If grep returns nothing:
- Portainer likely didn’t pull the new digest, or CI didn’t publish a new image.

### C) Backend health

```bash
curl -sS http://127.0.0.1:18018/health
docker compose -f stacks/idc1-assistance/docker-compose.yml logs --tail=200 jarvis-backend
```

### D) Collect debug evidence (recommended)

After reproducing a bug, collect a single snapshot (health, container IDs/digests, and logs):

```bash
./scripts/collect-idc1-assistance-evidence.sh
```

If you have a `trace_id` from the frontend Operation Log, filter backend logs down to that trace:

```bash
./scripts/collect-idc1-assistance-evidence.sh <trace_id>
```

## Common failure modes

### 1) "Redeployed" but still old

Symptoms:
- behavior unchanged
- `docker compose images` shows the same `IMAGE ID`

Fix:
- redeploy again with **pull latest image** enabled
- if needed, force rebuild by touching a file inside the service context (see “2.1) Forcing a rebuild”)

### 2) Frontend shows disconnected when backend emits `{type:"error"}`

Interpretation:
- Backend can emit `{type: "error"}` while keeping the WebSocket open (e.g. Gemini Live died).
- The frontend must not treat these as transport disconnects.

How to verify:
- check the deployed bundle behavior (see “Confirm frontend bundle contains the fix”).

### 3) Old Gemini Live errors stay pinned in Operation Log

Interpretation:
- The frontend Operation Log may show historical `{type:"error"}` messages.

Current behavior:
- On reconnect (state becomes `connected`) or on any subsequent normal message, the UI clears stale `gemini_live_model_not_found` error entries.

How to verify:
- Trigger a Live model failure once (expect an error entry).
- Reconnect; confirm the stale error disappears when `connected` is logged.
