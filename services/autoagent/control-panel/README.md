# AutoAgent Control Panel

Web-based control panel for AutoAgent with research capabilities.

## Features

- **Control Panel** (`/`): Environment overview, workspace browser, system metrics
- **Runner Panel** (`/runner`): Web UI for executing AutoAgent commands
  - Smart Research: LLM-powered KB search with caching
  - Free Models: Direct API calls using free models
  - Paid Models: Via AutoAgent CLI with LiteLLM
- **API Endpoints**:
  - `GET /api/health` - Health check
  - `POST /api/execute` - Execute commands
  - `GET /api/output/{session_id}` - Get command output
  - `POST /api/stop/{session_id}` - Stop running command

## Research Scripts

Included in `/workspace/`:

- `free-research.py` - Direct API calls using free models (nvidia/minimax)
- `smart-research.py` - LLM-powered KB search with PostgreSQL caching
- `wiki-knowledge.py` - Browse and search wiki articles
- `postgres_kb.py` - PostgreSQL knowledge base interface

## Usage

```bash
# Via control panel runner
curl http://idc1.surf-thailand.com:8059/runner

# Via API
curl -X POST http://idc1.surf-thailand.com:8059/api/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "python /workspace/free-research.py \"your question\""}'
```

## Build

Image is built automatically via GitHub Actions on push to `idc1-db` branch.

```bash
# Manual build
docker build -t ghcr.io/tonezzz/autoagent-control-panel:idc1-db .
```

## Deploy

Used by `stacks/idc1-db/docker-compose.yml`.

```yaml
services:
  autoagent:
    image: ghcr.io/tonezzz/autoagent-control-panel:idc1-db
    ports:
      - "8059:8080"
```
