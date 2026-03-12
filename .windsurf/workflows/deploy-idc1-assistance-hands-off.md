---
description: Hands-off-ish deploy loop (push -> wait CI -> redeploy -> verify)
---

# Goal
Deploy changes to `idc1-assistance` with minimal manual steps:

- push code
- wait for GH Actions to publish images
- redeploy the stack (preferred: host-side script; alternative: Portainer MCP)
- verify digest + health

# Preconditions
- `gh` is installed and authenticated (`gh auth status`).
- Portainer MCP is reachable and **write-enabled** (`PORTAINER_READ_ONLY=0`).
- You know the Portainer Environment ID (commonly `2` for local).
- Stack name is `idc1-assistance`.

# Step 1: Commit + push (local)
Run locally:

```bash
git status --porcelain
# add files
git add -A
git commit -m "fix: jarvis reminders + live model"
git push
```

If you need to trigger CI without changes:

```bash
git commit --allow-empty -m "ci: trigger rebuild"
git push
```

# Step 2: Wait for GH Actions publish workflow (local)
1. List latest runs for the publish workflow:

```bash
gh run list --repo tonezzz/chaba --workflow "Publish (idc1-assistance)" --limit 10
```

2. Watch the newest run until it finishes:

```bash
gh run watch <RUN_ID> --repo tonezzz/chaba --exit-status
```

If it fails:

```bash
gh run view <RUN_ID> --repo tonezzz/chaba --log-failed
```

# Step 3: Redeploy via Portainer MCP (Windsurf Tools)
Preferred when you are on the Docker host:

- Use: `.windsurf/workflows/run-deploy-idc1-assistance-script.md`

Alternative when you are not on the Docker host:

## 3.1 Find the stack id
- Tool: `portainer_1mcp_listLocalStacks`
- Args:
  - `environmentId`: `2`

Find the stack with `Name` == `idc1-assistance` and copy its `Id`.

## 3.2 Update/redeploy the stack
Preferred (applies compose/env changes + redeploys):
- Tool: `portainer_1mcp_updateLocalStack`
- Args:
  - `environmentId`: `2`
  - `stackId`: `<STACK_ID>`
  - `pullImage`: `true`

Fallback (bounce only):
- Tool: `portainer_1mcp_stopLocalStack` then `portainer_1mcp_startLocalStack`

# Step 4: Verify digest + health (local)
## 4.1 Verify backend digest changed
```bash
docker inspect -f 'started={{.State.StartedAt}} image={{.Config.Image}} digest={{.Image}}' idc1-assistance-jarvis-backend-1
```

## 4.2 Verify backend health
```bash
curl -fsS http://127.0.0.1:18018/health
```

## 4.3 Tail backend logs for regressions
```bash
docker logs --since 15m --tail 400 idc1-assistance-jarvis-backend-1 | egrep -i 'weaviate|reminder|gemini_live_|model_not_found|Traceback|Exception| 5.. ' || true
```

# Suggested functional smoke checks
- Create reminder (WS helper): `reminder add: test`
- List reminders: `reminder list pending`
- Restart backend container, list again
