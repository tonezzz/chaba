---
description: Run hands-off deploy script (whole stack, redeploy only if digest changed)
---

# Goal
Run a single command on the Docker host that:

- waits for the latest successful GH Actions publish run (`Publish (idc1-assistance)`)
- pulls stack images
- compares pulled image IDs vs running container image IDs
- redeploys only services whose image changed (min downtime)
- verifies digests + health

# Preconditions
- `gh` is installed and authenticated (`gh auth status`).
- You are on the Docker host that runs the `idc1-assistance` stack.
- Script exists: `scripts/deploy-idc1-assistance.sh`

# One-time setup
Make the script executable:

```bash
chmod +x scripts/deploy-idc1-assistance.sh
```

# Run
```bash
./scripts/deploy-idc1-assistance.sh
```

# Optional tuning (env vars)
- `WAIT_TIMEOUT_SECONDS` (default `1800`)
- `POLL_SECONDS` (default `10`)
- `HEALTH_WINDOW_SECONDS` (default `120`)

Example:

```bash
WAIT_TIMEOUT_SECONDS=3600 POLL_SECONDS=15 ./scripts/deploy-idc1-assistance.sh
```
