# pc1-wiki Stack

MCP Wiki - SQLite-backed team knowledge base.

## Access

- Web UI: http://localhost:3008 (or via Caddy: `wiki.pc1.vpn`)
- API: http://localhost:3008/api/articles

## Commands

```powershell
# Start
docker-compose up -d --build

# Stop
docker-compose down

# View logs
docker-compose logs -f mcp-wiki
```

## Data

SQLite database persisted in Docker volume `wiki-data` at `/data/wiki.db`.
