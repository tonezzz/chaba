# Assistance stack config (idc1-assistance)

This file documents **effective runtime configuration** for the `idc1-assistance` stack (Jarvis frontend+backend+Weaviate) on the Docker host.

Rules:

- No secrets in this file.
- Prefer documenting **actual bind ports/URLs** that operators use.
- Compose defaults do not override values configured in **Portainer stack env**.

## Host endpoints (effective)

- Jarvis UI:
  - `http://127.0.0.1:18080/jarvis/`
- Jarvis backend health:
  - `http://127.0.0.1:18018/health`
- Reminders API:
  - `http://127.0.0.1:18018/reminders`
- Weaviate (internal to stack network):
  - `http://weaviate:8080`

## Ports (host binds)

- `127.0.0.1:18080` -> Jarvis frontend
- `127.0.0.1:18018` -> Jarvis backend

## Source-of-truth locations

- Stack compose:
  - `stacks/idc1-assistance/docker-compose.yml`
- Stack env template:
  - `stacks/idc1-assistance/.env.example`
- Portainer control-plane + MCP config:
  - `stacks/idc1-portainer/docs/CONFIG.md`

## Environment variables (non-secret overview)

These are set via compose defaults and/or Portainer stack env:

- `WEAVIATE_URL`
  - example: `http://weaviate:8080`
- `GEMINI_LIVE_MODEL`
  - example: `gemini-2.5-flash-native-audio-preview-12-2025`

Secrets (must be provided via Portainer stack env or host env, never committed):

- `GEMINI_API_KEY`

## Deploy (hands-off)

Canonical flow on the Docker host:

- `./scripts/deploy-idc1-assistance.sh`

This script:

- waits for latest successful GH Actions publish run
- pulls images
- redeploys via Portainer CE HTTP API when digests changed
- verifies image digests and health

## Verification checklist (post-redeploy)

- Backend health:
  - `curl -fsS http://127.0.0.1:18018/health`
- Reminders list:
  - `curl -fsS 'http://127.0.0.1:18018/reminders?status=pending&limit=5'`
- Backend logs (recent):
  - `docker logs --since 15m --tail 400 idc1-assistance-jarvis-backend-1`
