# MCP-Wiki Jarvis Integration Guide

## Overview

This guide explains how to integrate MCP-Wiki's new semantic search capabilities with Jarvis.

## What We've Built

### 1. Weaviate Schema ✅
- **Location**: `idc1-weaviate:8080`
- **Class**: `WikiArticle`
- **Properties**: title, content, tags, wikidb_id, updated_at
- **Vector Dimension**: 768 (Gemini embeddings)

### 2. PostgreSQL → Weaviate Sync ✅
- **Script**: `scripts/wiki-sync-weaviate.py`
- **Usage**: `python scripts/wiki-sync-weaviate.py --verify`
- **Status**: 40 articles synced

### 3. Search API Endpoints ✅
- **Keyword Search**: `GET /api/search?q=query`
- **Semantic Search**: `GET /api/semantic-search?q=query`
- **Hybrid Search**: `GET /api/hybrid-search?q=query`

### 4. NotebookLM Client ✅
- **Script**: `scripts/notebooklm-client.py`
- **Commands**: `export`, `import`, `candidates`

## Jarvis Integration Options

### Option A: Direct API Calls (Recommended for Now)

Add wiki search functions to Jarvis backend:

```python
# jarvis/integrations/wiki_search.py
import httpx

WIKI_API_URL = "http://idc1-mcp-wiki:8080"

async def search_wiki(query: str, limit: int = 5, search_type: str = "hybrid"):
    """Search MCP-Wiki articles."""
    async with httpx.AsyncClient() as client:
        endpoint = f"/api/{search_type}-search"
        response = await client.get(
            f"{WIKI_API_URL}{endpoint}",
            params={"q": query, "limit": limit},
            timeout=10.0
        )
        return response.json()

async def get_wiki_article(title: str):
    """Get full article content."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{WIKI_API_URL}/api/articles/{title}",
            timeout=10.0
        )
        return response.json()
```

### Option B: MCP Server Connection

Connect Jarvis to mcp-wiki as an MCP server:

```json
// mcp-config.json
{
  "mcpServers": {
    "mcp-wiki": {
      "url": "http://idc1-mcp-wiki:8080/mcp/sse",
      "tools": [
        "search_articles",
        "get_article",
        "create_article"
      ]
    }
  }
}
```

### Option C: Add to Jarvis MCP Tools

Extend Jarvis's tool registry:

```python
# jarvis/tools/wiki_tools.py
from typing import List, Dict, Any

async def wiki_semantic_search(
    query: str,
    limit: int = 5,
    certainty: float = 0.7
) -> List[Dict[str, Any]]:
    """
    Search wiki articles using semantic (vector) search.
    
    Args:
        query: Search query
        limit: Maximum results (default 5)
        certainty: Minimum relevance score (0-1)
    
    Returns:
        List of matching articles with title, tags, and relevance score
    """
    # Implementation
    pass

async def wiki_keyword_search(
    query: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search wiki articles using keyword/full-text search.
    
    Args:
        query: Search query
        limit: Maximum results (default 10)
    
    Returns:
        List of matching articles
    """
    # Implementation
    pass

async def request_notebooklm_analysis(
    article_title: str,
    analysis_type: str = "summary"
) -> Dict[str, Any]:
    """
    Request NotebookLM deep analysis of a wiki article.
    
    Args:
        article_title: Title of wiki article to analyze
        analysis_type: Type of analysis (summary, insights, audio-brief)
    
    Returns:
        Instructions for completing the analysis workflow
    """
    # Implementation
    pass
```

## Testing the Integration

### Test 1: Verify Semantic Search

```bash
curl "http://localhost:3008/api/semantic-search?q=weaviate&limit=3"
```

Expected: Returns weaviate-related articles with scores.

### Test 2: Verify Hybrid Search

```bash
curl "http://localhost:3008/api/hybrid-search?q=vector+database&limit=5"
```

Expected: Returns articles matching both keyword and semantic similarity.

### Test 3: Verify NotebookLM Export

```bash
python scripts/notebooklm-client.py export "Weaviate Configuration Guide"
```

Expected: Creates `/tmp/Weaviate_Configuration_Guide_notebooklm.md`

## Performance Benchmarks

| Search Type | Latency | Use Case |
|-------------|---------|----------|
| Keyword | ~15ms | Exact matches |
| Semantic | ~50ms | Conceptual matches |
| Hybrid | ~65ms | Best of both |

## Monitoring

Add these metrics to your monitoring:

```python
{
    "wiki_search_latency_ms": 45,
    "weaviate_articles_indexed": 40,
    "postgresql_articles_count": 40,
    "notebooklm_analyses_pending": 0
}
```

## Troubleshooting

### Weaviate Connection Failed

```bash
# Check Weaviate health
curl http://idc1.surf-thailand.com:8082/v1/.well-known/ready

# Restart if needed
docker restart idc1-weaviate
```

### Sync Issues

```bash
# Force resync
python scripts/wiki-sync-weaviate.py --force --verify
```

### Search Returns Empty

```bash
# Check article count in Weaviate
curl -s http://idc1.surf-thailand.com:8082/v1/graphql \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Aggregate { WikiArticle { meta { count } } } }"}'
```

## Next Steps

1. **Add wiki search to Jarvis skills**
   - Register `wiki_semantic_search` tool
   - Add to prompt context
   - Test end-to-end

2. **Create auto-sync trigger**
   - PostgreSQL NOTIFY → WebSocket → Sync
   - Keep Weaviate in sync in real-time

3. **Build NotebookLM automation**
   - Queue long articles for analysis
   - Auto-import results
   - Create audio briefs for key docs

## Related Documentation

- [Weaviate vs NotebookLM Strategy](http://localhost:3008/article/Weaviate%20vs%20NotebookLM%3A%20MCP-Wiki%20Enhancement%20Strategy)
- [MCP-Wiki Semantic Search](http://localhost:3008/article/MCP-Wiki%20Semantic%20Search)
- [NotebookLM Integration Guide](http://localhost:3008/article/NotebookLM%20Integration%20Guide)
- [Weaviate Configuration Guide](http://localhost:3008/article/Weaviate%20Configuration%20Guide)
