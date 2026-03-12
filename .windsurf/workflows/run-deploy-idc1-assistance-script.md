---
description: Run hands-off deploy script (whole stack, redeploy only if digest changed)
---

# Goal
Run a single command on the Docker host that:

- waits for the latest successful GH Actions publish run (`Publish (idc1-assistance)`)
- pulls stack images
- compares pulled image IDs vs running container image IDs
- triggers a Portainer-authoritative stack redeploy via Portainer HTTP API (CE compatible)
- verifies digests + health

# Preconditions
- `gh` is installed and authenticated (`gh auth status`).
- You are on the Docker host that runs the `idc1-assistance` stack.
- Script exists: `scripts/deploy-idc1-assistance.sh`
- Portainer API is reachable from the host (commonly `http://127.0.0.1:9000`).
- Portainer API auth is available via `PORTAINER_API_KEY` (or `PORTAINER_TOKEN`).

# One-time setup
Make the script executable:

```bash
chmod +x scripts/deploy-idc1-assistance.sh
```

# Run
```bash
./scripts/deploy-idc1-assistance.sh
```

# Portainer API configuration
Set on the Docker host (do not commit):

```bash
export PORTAINER_URL='http://127.0.0.1:9000'
export PORTAINER_API_KEY='ptr_...'
export PORTAINER_ENDPOINT_ID='2'
export PORTAINER_STACK_NAME='idc1-assistance'
```

# Optional tuning (env vars)
- `WAIT_TIMEOUT_SECONDS` (default `1800`)
- `POLL_SECONDS` (default `10`)
- `HEALTH_WINDOW_SECONDS` (default `120`)

Example:

```bash
WAIT_TIMEOUT_SECONDS=3600 POLL_SECONDS=15 ./scripts/deploy-idc1-assistance.sh
```
