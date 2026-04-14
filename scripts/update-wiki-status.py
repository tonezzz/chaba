#!/usr/bin/env python3
"""Update wiki articles with current mcp-wiki deployment status."""

import requests
import json
from datetime import datetime

WIKI_URL = "http://idc1.surf-thailand.com:3008"
API_KEY = "9cad60d2f82db9af44d31dac4330f7d69c5b87637019130017a64ee27e4659d2"

def update_article(title, content, tags):
    """Create or update a wiki article."""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    
    # Try to create first
    resp = requests.post(
        f"{WIKI_URL}/api/articles",
        headers=headers,
        json={"title": title, "content": content, "tags": tags}
    )
    
    if resp.status_code == 409 or "already exists" in resp.text:
        # Update existing
        resp = requests.put(
            f"{WIKI_URL}/api/articles/{requests.utils.quote(title)}",
            headers=headers,
            json={"content": content, "tags": tags}
        )
    
    return resp.status_code in (200, 201)

# Update MCP Wiki Server Architecture article
architecture_content = f"""# MCP Wiki Server Architecture

## Overview
The MCP Wiki Server provides semantic knowledge management with multiple search capabilities.

## Deployment Status (Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')})

| Component | Status | Details |
|-----------|--------|---------|
| Container | ✅ Healthy | `idc1-mcp-wiki` running on idc1 |
| Database | ✅ PostgreSQL | Connected to shared idc1-db |
| HTTP API | ✅ Active | Port 3008, HTTP-only mode |
| Healthcheck | ✅ Working | `/health` endpoint verifies DB connectivity |
| Vector Search | ✅ Ready | GEMINI_API_KEY configured |
| Image | ✅ Latest | `ghcr.io/tonezzz/mcp-wiki:latest` |

## Recent Fixes (April 14, 2026)

### 1. Healthcheck Endpoint
- Added Docker healthcheck using wget
- `/health` now verifies actual database connectivity
- Returns DB type, status, and timestamp

### 2. GEMINI_API_KEY Integration
- Vector search now functional via Gemini embeddings
- WEAVIATE_URL configured for semantic search
- API key passed from stack environment

### 3. HTTP-Only Mode
- Container runs in HTTP-only mode (no stdio)
- Better compatibility with Portainer deployment
- SSE transport available at `/mcp/sse`

## Architecture Components

### 1. Storage Layer
- **PostgreSQL**: Shared database in idc1-db stack
- **Weaviate**: Vector database for semantic search

### 2. API Endpoints
- `GET /api/articles` - List articles
- `GET /api/articles/:title` - Get specific article
- `POST /api/articles` - Create article (auth required)
- `PUT /api/articles/:title` - Update article (auth required)
- `GET /api/search?q=query` - Search articles
- `GET /health` - Health check with DB verification

### 3. MCP Integration
- SSE transport: `/mcp/sse`
- Tools: `wiki_search`, `wiki_get`, `wiki_create`, `wiki_update`, `wiki_delete`
- Semantic search: `wiki_semantic_search`, `wiki_vector_search`

## Configuration

```yaml
environment:
  WIKI_USE_POSTGRES: '1'
  DATABASE_URL: postgresql://chaba:changeme@postgres:5432/chaba
  GEMINI_API_KEY: "${{GEMINI_API_KEY}}"
  WEAVIATE_URL: http://weaviate:8080
  WIKI_API_KEY: "${{WIKI_API_KEY}}"
  MCP_STDIO: '0'  # HTTP-only mode
```

## Access
- **Web UI**: http://idc1.surf-thailand.com:3008
- **API**: http://idc1.surf-thailand.com:3008/api
- **Health**: http://idc1.surf-thailand.com:3008/health

## Related
- [[IDC1-DB Stack Overview]]
- [[MCP Wiki Manual]]
- [[Reference: MCP Wiki Usage]]
"""

# Update Reference: Mcp Wiki article
reference_content = f"""# Reference: MCP Wiki Usage

Quick reference for the MCP Wiki service on idc1.

## Status: ✅ Operational ({datetime.now().strftime('%Y-%m-%d')})

- **URL**: http://idc1.surf-thailand.com:3008
- **Container**: `idc1-mcp-wiki` (healthy)
- **Database**: PostgreSQL (shared with idc1-db stack)

## API Quick Reference

### List Articles
```bash
curl http://idc1.surf-thailand.com:3008/api/articles?limit=10
```

### Get Article
```bash
curl "http://idc1.surf-thailand.com:3008/api/articles/MCP%20Wiki%20Server%20Architecture"
```

### Create Article (authenticated)
```bash
curl -X POST http://idc1.surf-thailand.com:3008/api/articles \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: $WIKI_API_KEY" \\
  -d '{{"title": "New Article", "content": "...", "tags": ["doc"]}}'
```

### Health Check
```bash
curl http://idc1.surf-thailand.com:3008/health
```

## Recent Changes

| Date | Change |
|------|--------|
| 2026-04-14 | Added healthcheck endpoint with DB verification |
| 2026-04-14 | Fixed GEMINI_API_KEY for vector search |
| 2026-04-14 | Switched to HTTP-only mode for Portainer compatibility |

## Tags
reference, mcp, wiki, api, idc1
"""

if __name__ == "__main__":
    print("Updating wiki articles...")
    
    result1 = update_article(
        "MCP Wiki Server Architecture",
        architecture_content,
        ["mcp", "wiki", "architecture", "deployment", "idc1"]
    )
    print(f"Architecture article: {'✅' if result1 else '❌'}")
    
    result2 = update_article(
        "Reference: Mcp Wiki",
        reference_content,
        ["reference", "mcp", "wiki", "api", "idc1"]
    )
    print(f"Reference article: {'✅' if result2 else '❌'}")
    
    print("Done!")
