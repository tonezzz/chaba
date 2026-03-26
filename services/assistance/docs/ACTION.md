# ACTION — assistance stack operator runbook

> **Authoritative location**: this file is the SSOT for operating the `idc1-assistance` stack.
> For dev/feature work, see the [GitHub Issues tracker](https://github.com/tonezzz/chaba/issues).

## Overview

The assistance stack runs two containers on idc1:

| Container | Image tag | Host port |
|-----------|-----------|-----------|
| `jarvis-backend` | `ghcr.io/tonezzz/chaba/jarvis-backend:idc1-assistance` | `127.0.0.1:18018` |
| `jarvis-frontend` | `ghcr.io/tonezzz/chaba/jarvis-frontend:idc1-assistance` | `127.0.0.1:18080` |

Both containers share `idc1-stack-net` and are managed by the compose file at:

```
stacks/idc1-assistance/docker-compose.yml
```

## Environment setup

1. Copy the template and fill in secrets:

```bash
cp stacks/idc1-assistance/.env.example stacks/idc1-assistance/.env
# edit .env: set GEMINI_API_KEY and any optional overrides
```

Key variables (see `.env.example` for the full list):

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | yes | Gemini Developer API key |
| `GEMINI_LIVE_MODEL` | no | Override default model |
| `GITHUB_PERSONAL_TOKEN_RW` | gated | Enables GitHub Issues write endpoints (see below) |

## Start / stop / restart

```bash
cd stacks/idc1-assistance

# Start (or recreate)
docker compose up -d

# Stop
docker compose down

# Pull latest images and recreate
docker compose pull && docker compose up -d --force-recreate

# Tail logs
docker compose logs -f
```

## Health checks

```bash
# Backend health (expect {"status":"ok",...})
curl -sf http://127.0.0.1:18018/health

# Frontend (expect HTTP 200)
curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:18080/
```

## API endpoints

The backend exposes a self-documenting OpenAPI spec:

```
GET http://127.0.0.1:18018/openapi.json
```

### GitHub Issues endpoints (gated feature)

These endpoints are disabled by default. Enable with the `github.issues.write.enabled` system key (`TRUE`/`true`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/github/issues/search` | Search issues |
| `POST` | `/github/issues/create` | Create an issue |
| `POST` | `/github/issues/comment` | Add a comment to an issue |

RW operations require `GITHUB_PERSONAL_TOKEN_RW` to be set in the stack `.env` (passed through from Portainer stack env at runtime).

## Caddy ingress (idc1)

Host Caddy should route the public hostname to the containers:

```
/jarvis/*    -> http://127.0.0.1:18080
/jarvis/ws/* -> http://127.0.0.1:18018
```

Refer to `sites/a1-idc1/config/Caddyfile` for the live ingress config and `docs/stacks.md` → idc1 section for the broader network topology.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Backend container exits immediately | `docker compose logs jarvis-backend` — likely missing `GEMINI_API_KEY` |
| Frontend returns 502 | Verify backend is healthy: `curl http://127.0.0.1:18018/health` |
| GitHub Issues endpoints return 403 | Check `github.issues.write.enabled` gate and `GITHUB_PERSONAL_TOKEN_RW` env var |
| `idc1-stack-net` not found | The external network must exist: `docker network create idc1-stack-net` |
