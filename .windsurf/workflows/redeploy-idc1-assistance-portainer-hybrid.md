---
description: Portainer-first redeploy + host verification
---

# Goal
Redeploy the `idc1-assistance` stack using Portainer as the *control plane*, while using minimal host-side Docker commands only for fast verification (image digest, start time) and log tailing.

# Preconditions
- You have access to Portainer (UI) on the target host.
- You know the **Stack name** in Portainer (e.g. `idc1-assistance`).
- Images are built/published elsewhere (e.g. GHCR) and Portainer pulls them.

# Step 1: Redeploy via Portainer (UI)
1. Open **Portainer**.
2. Go to:
   - **Stacks**
   - Select stack: `idc1-assistance`
3. Click **Pull and redeploy** (or the equivalent action in your Portainer version).
4. Wait until the stack redeploy finishes.

# Step 2: Verify containers are up (UI)
1. Go to **Containers**.
2. Confirm these are running/healthy (names may vary):
   - `idc1-assistance-jarvis-backend-1`
   - `idc1-assistance-jarvis-frontend-1`
   - `idc1-assistance-weaviate-1`
   - `idc1-assistance-mcp-bundle-1`

# Step 3: Verify the new image is actually running (host)
Run on the host:

```bash
docker inspect -f 'started={{.State.StartedAt}} image={{.Config.Image}} digest={{.Image}}' idc1-assistance-jarvis-backend-1
```

What you want:
- `started=` is recent (matches your redeploy time)
- `digest=` changed compared to the previous deployment when you were diagnosing a bug

# Step 4: Tail backend logs around Gemini Live / WS (host)
```bash
docker logs --since 20m --tail 400 idc1-assistance-jarvis-backend-1 | egrep -i 'ws/live|gemini_|1007|1008|model=|Exception in ASGI application|Traceback' || true
```

# Step 5: Functional smoke check (UI)
- Open Jarvis UI and press **Initialize**.
- Speak or send a short text.

Expected:
- WS stays connected.
- No recurring `1008 Requested entity was not found`.

# When Portainer-only is enough (no host CLI)
Portainer UI alone is usually sufficient for:
- Pull/redeploy stack
- View container logs
- Restart containers
- `Exec` into a container

# When host CLI is still useful
Host CLI is typically faster/clearer for:
- Grep/filter logs
- Compare image digests across redeploys
- Quick one-liners for env inspection

# Common pitfalls
- Portainer may redeploy without pulling if the tag is unchanged and pull is not forced.
- Compose defaults do not override stack env values configured in Portainer.
