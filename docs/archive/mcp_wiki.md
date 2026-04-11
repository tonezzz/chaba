# MCP Wiki

SQLite-backed knowledge base MCP server for team documentation.

**Status**: ✅ Operational on pc1 at http://localhost:3008

## Overview

`mcp-wiki` provides a minimal, SQLite-based wiki accessible via:
- **HTTP (web UI)** — for human team members via browser at `http://localhost:3008`
- **MCP (stdio)** — for AI agents and MCP clients (Windsurf, Claude Desktop)

## Architecture

```
                    ┌─────────────────┐
  Browser           │  mcp-wiki       │
  (HTTP 3008) ──────│  ┌───────────┐  │──────┐
                    │  │  SQLite   │  │      │
  MCP Client ───────│  │  /data/   │  │      ▼
  (optional)        │  │  wiki.db  │  │   /api/*
                    │  └───────────┘  │      │
                    └─────────────────┘      ▼
                                          JSON API
```

## Current Deployment (pc1)

| Component | Value |
|-----------|-------|
| Stack | `stacks/pc1-wiki/` |
| Container | `mcp-wiki` |
| Host Port | `3008` → Container `8080` |
| Data Volume | `pc1-wiki_wiki-data` |
| Database | `/data/wiki.db` (SQLite) |

### Quick Access

- **Web UI**: http://localhost:3008
- **API**: http://localhost:3008/api/articles
- **Health**: http://localhost:3008/health

### Commands

```powershell
# View logs
docker-compose -f C:\chaba\stacks\pc1-wiki\docker-compose.yml logs -f mcp-wiki

# Stop
docker-compose -f C:\chaba\stacks\pc1-wiki\docker-compose.yml down

# Restart/rebuild
docker-compose -f C:\chaba\stacks\pc1-wiki\docker-compose.yml up -d --build
```

## Web UI (HTTP)

| Endpoint | Description |
|----------|-------------|
| `GET /` | Home page with article list + search |
| `GET /search?q=query` | Search results |
| `GET /article/:title` | View article |
| `GET /new` | Create article form |
| `POST /create` | Submit new article |
| `GET /edit/:title` | Edit article form |
| `POST /update` | Submit article update |
| `GET /api/articles` | List articles (JSON) |
| `GET /api/articles/:title` | Get article (JSON) |
| `GET /health` | Health check |

## Tools (MCP)

| Tool | Description |
|------|-------------|
| `wiki_search` | Search articles by title or content |
| `wiki_get` | Retrieve article content by title |
| `wiki_create` | Create new article |
| `wiki_update` | Update existing article |
| `wiki_list` | List recent articles |

### MCP Client Configuration (Windsurf)

```json
{
  "mcpServers": {
    "wiki": {
      "command": "docker",
      "args": ["exec", "-i", "mcp-wiki", "node", "/app/index.js"],
      "env": {
        "MCP_STDIO": "1"
      }
    }
  }
}
```

Or for local development:

```json
{
  "mcpServers": {
    "wiki": {
      "command": "node",
      "args": ["c:/chaba/mcp/mcp-wiki/index.js"],
      "env": {
        "WIKI_DB_PATH": "c:/chaba/data/wiki.db",
        "WIKI_HTTP_PORT": "8080",
        "MCP_STDIO": "1"
      }
    }
  }
}
```

## Usage Examples

### Via Web UI

1. Open http://localhost:3008
2. Click "New Article" to create documentation
3. Use search box to find existing articles
4. Edit articles inline

### Via MCP (Agent)

```javascript
// Create an article
wiki_create({
  title: "Deployment Runbook",
  content: "# Deployment Steps\n\n1. Run tests\n2. Build containers\n3. Deploy to idc1",
  tags: ["devops", "deployment"]
})

// Search articles
wiki_search({ query: "deployment", limit: 5 })

// Get article
wiki_get({ title: "Deployment Runbook" })
```

### Via REST API

```bash
# List articles
curl http://localhost:3008/api/articles

# Get specific article
curl http://localhost:3008/api/articles/Deployment%20Runbook
```

## Migration to Full Wiki

When the team outgrows SQLite:

1. Export: Use `/api/articles` + `/api/articles/:title` to extract all articles
2. Import into Wiki.js/BookStack via their APIs
3. Update `mcp-wiki` to proxy to new backend instead of SQLite

## Related

- [MCP SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [SQLite3 Node.js](https://github.com/TryGhost/node-sqlite3)
- [Express.js](https://expressjs.com/)
- Location: `c:/chaba/mcp/mcp-wiki/`
- Source: `c:/chaba/mcp/mcp-wiki/index.js`
- Docs: `c:/chaba/docs/mcp_wiki.md`
