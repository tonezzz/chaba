# idc1-skill-creator

Skill Creator UI deployed on idc1 host, following the same pattern as mcp-wiki.

## Overview

- **Container**: `skill-creator`
- **Host Port**: `8090`
- **Container Port**: `8080`
- **URL**: `http://idc1.surf-thailand.com:8090` (or via Caddy reverse proxy)

## Deployment

### 1. Configure Environment

```bash
cd /home/chaba/chaba/stacks/idc1-skill-creator

# Copy and edit .env
cp .env .env.local
nano .env.local
```

### 2. Deploy Stack

```bash
# Via Portainer (recommended for idc1)
# - Log into Portainer at https://idc1.surf-thailand.com:9443
# - Go to Stacks → Add Stack
# - Upload docker-compose.yml
# - Set environment variables
# - Deploy

# Or via Docker CLI
docker compose -f docker-compose.yml --env-file .env.local up -d
```

### 3. Verify Deployment

```bash
# Check container is running
docker ps | grep skill-creator

# Check logs
docker logs skill-creator

# Test locally
curl http://localhost:8090/skills
```

## Caddy Integration

Add to `/etc/caddy/Caddyfile`:

```caddy
assistance.idc1.surf-thailand.com {
    # ... existing config ...
    
    # Skill Creator UI
    handle_path /skills/* {
        reverse_proxy skill-creator:8080
    }
    
    handle /skills {
        redir /skills/ 308
    }
    
    # Skill Creator API
    handle_path /api/skills/* {
        reverse_proxy skill-creator:8080
    }
}
```

Then reload Caddy:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│   User Browser  │────▶│  Caddy (443) │────▶│ skill-creator   │
│                 │     │              │     │   (port 8090)   │
└─────────────────┘     └──────────────┘     └─────────────────┘
                                                    │
                                                    ▼
                                              ┌──────────────┐
                                              │  mcp-wiki    │
                                              │  (port 3008) │
                                              └──────────────┘
```

## Features

- 🇹🇭 Thai Language Support
- 📋 Review/Approval Workflow
- 🎯 LLM Interpretation via OpenRouter
- 💾 Wiki Integration
- 🔧 Text-driven Skill Development

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Stack definition |
| `.env` | Environment template |
| `README.md` | This file |

## Troubleshooting

### Container won't start
```bash
docker logs skill-creator
docker inspect skill-creator
```

### Can't reach wiki
```bash
# Test wiki connectivity from container
docker exec skill-creator curl http://mcp-wiki:8080/api/articles
```

### Port already in use
```bash
# Check what's using port 8090
sudo lsof -i :8090

# Change port in .env.local
SKILL_CREATOR_HOST_PORT=8091
```

## Related Stacks

- `pc1-wiki` - MCP Wiki (similar pattern)
- `idc1-assistance` - Jarvis backend
