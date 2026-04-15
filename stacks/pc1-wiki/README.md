# pc1-wiki Stack

MCP Wiki - PostgreSQL-backed team knowledge base with full-text search.

## Access

- Web UI: http://localhost:3008
- MCP SSE: http://localhost:3008/mcp/sse
- API: http://localhost:3008/api/articles

## Commands

```bash
# Start
docker-compose up -d --build

# Stop
docker-compose down

# View logs
docker-compose logs -f mcp-wiki
```

## Data

PostgreSQL with pgvector extension for future embedding support.
- Database: `chaba`
- User: `chaba`
- Port: `5433` (mapped from container 5432)
