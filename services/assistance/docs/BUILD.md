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
- Run `./scripts/deploy-idc1-assistance.sh` (handles Portainer redeploy automatically).
- Verify the running container uses a new **IMAGE ID**.

Notes:

- GitHub Actions publishes images **selectively** (only the images whose inputs changed).
- **Portainer is authoritative** for stack environment variables (secrets, runtime config).
- **Git** controls compose structure and default values.
- The deploy script syncs: `git` → Portainer API → containers (preserving Portainer env).

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
- `stacks/idc1-assistance-*/`

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

### 3) Wait for GitHub Actions

Expected:
- CI builds and pushes updated `:idc1-assistance` images to GHCR.

If the build fails:
- fix CI first; redeploying won’t change anything.

### 4) Redeploy via Portainer

### A) Confirm IMAGE ID changed (digest-level)

On the host (or wherever Docker CLI is available):

```bash
bash scripts/idc1-assistance-smoke.sh
```

You want to see:
- `IMAGE ID` changed for the service you rebuilt (e.g. `jarvis-frontend`, `jarvis-backend`).

### A.1) Git-backed Portainer stack vs local Docker Compose

If `idc1-assistance` is deployed as a **Portainer git-backed stack**, treat Portainer as authoritative for:
- Stack file content
- Stack environment variables (secrets like OAuth client IDs)

Common trap:
- Running local `docker compose ... up` can create containers that look identical but do **not** include the Portainer stack env.
- You can end up with multiple `mcp-bundle` containers (example: `idc1-assistance-mcp-mcp-bundle-1` plus a separate `idc1-portainer-mcp-bundle-1`).

When debugging "missing env":

```bash
docker ps --format '{{.Names}}' | grep -E 'mcp-bundle' || true
```

### A.2) Managing Environment Variable Drift

**Problem:** Portainer stack env and git `.env.example` can drift, causing confusion when:
- Local `docker compose up` uses different env than Portainer
- New env vars are added to code but not Portainer
- Secrets exist in Portainer but are missing from documentation

**Solution - Check drift:**

```bash
# List all env vars currently in Portainer stack
curl -s "http://127.0.0.1:9000/api/stacks/<stack_id>" \
  -H "X-API-Key: $PORTAINER_TOKEN" | \
  jq -r '.Env[] | "\(.name)"' | sort

# Compare with .env.example
diff <(curl -s ... | jq -r ...) <(cat stacks/idc1-assistance/.env.example | grep -E "^[A-Z]" | cut -d= -f1 | sort)
```

**Current drift status (as of last update):**

| Category | Variables |
|----------|-----------|
| **In Portainer only** (secrets/config) | `GEMINI_API_KEY`, `GITHUB_*`, `GOOGLE_CLIENT_*`, `JARVIS_ADMIN_TOKEN`, `PORTAINER_TOKEN`, `_GEMINI_LIVE_MODEL` |
| **In .env.example only** (structure) | `GOOGLE_DRIVE_MCP_BASE_URL`, `JARVIS_RECENT_DIALOG_*`, `REDIS_URL` |

**Action:** If variables are missing in Portainer, add them via Portainer UI → Stacks → `idc1-assistance-core` → Editor → Environment Variables.

### B) Confirm frontend bundle contains the fix you expect

When debugging “frontend still old”, it’s often easier to grep the served JS bundle than to guess.

```bash
docker compose -f stacks/idc1-assistance-core/docker-compose.yml exec -T jarvis-frontend sh -lc 'ls -1 /usr/share/nginx/html/assets | head'
docker compose -f stacks/idc1-assistance-core/docker-compose.yml exec -T jarvis-frontend sh -lc 'grep -R "Do not treat these as transport disconnects" -n /usr/share/nginx/html 2>/dev/null | head'
```

If grep returns nothing:
- Portainer likely didn’t pull the new digest, or CI didn’t publish a new image.

### C) Backend health

```bash
curl -sS http://127.0.0.1:18018/health
docker compose -f stacks/idc1-assistance-core/docker-compose.yml logs --tail=200 jarvis-backend
```

### D) Manual redeploy with Portainer env (when not using deploy script)

If you need to redeploy manually and want to use Portainer's env vars (not shell env):

```bash
# Export Portainer stack env vars first
export PORTAINER_TOKEN="ptr_..."
export PORTAINER_STACK_NAME="idc1-assistance-core"

# Get stack ID
stack_id=$(curl -s "http://127.0.0.1:9000/api/stacks" \
  -H "X-API-Key: $PORTAINER_TOKEN" | \
  jq -r ".[] | select(.Name==\"$PORTAINER_STACK_NAME\") | .Id")

# Export all Portainer env vars (excluding secrets)
eval $(curl -s "http://127.0.0.1:9000/api/stacks/$stack_id" \
  -H "X-API-Key: $PORTAINER_TOKEN" | \
  jq -r '.Env[] | "export \(.name)=\(.value|@sh)"' | \
  grep -vE "(SECRET|PASSWORD|TOKEN|API_KEY|CLIENT_SECRET)")

# Now redeploy with correct env
docker compose -f stacks/idc1-assistance-core/docker-compose.yml up -d --force-recreate jarvis-backend
```

**Better alternative:** Use the deploy script which handles this automatically:
```bash
./scripts/deploy-idc1-assistance.sh
```

### E) Collect debug evidence (recommended)

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
