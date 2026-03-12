---
description: Redeploy idc1-assistance (Portainer-first)
---

# Goal
Redeploy `idc1-assistance` safely and verify you’re running the intended image digest.

# Preconditions
- You have access to Portainer on the target host.
- CI/build has already published the new images to the registry (e.g. GHCR).

# Step 1: Redeploy via Portainer
1. Open **Portainer**.
2. Go to **Stacks**.
3. Select stack: `idc1-assistance`.
4. Click **Pull and redeploy**.
5. Ensure the redeploy action is configured to **pull latest**.

# Step 2: Verify key containers are running
In Portainer:
- `idc1-assistance-jarvis-backend-1`
- `idc1-assistance-jarvis-frontend-1`
- `idc1-assistance-weaviate-1`

# Step 3: Verify digest (host CLI, fastest)
Run on host:

```bash
docker inspect -f 'started={{.State.StartedAt}} image={{.Config.Image}} digest={{.Image}}' idc1-assistance-jarvis-backend-1
```

# Step 4: Functional smoke check
- Open Jarvis UI.
- Initialize.
- Run one golden-path action (for this repo: create a reminder, then list reminders).

# Common pitfalls
- Portainer redeploy without pulling (tag unchanged).
- Stack env in Portainer overriding compose defaults.
