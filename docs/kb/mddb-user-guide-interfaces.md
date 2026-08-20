---
category: operations
---

# Web UI: Open browser and use search interface
# MCP Integration: Use via AI assistants
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"mcp infrastructure configuration","limit":5,"collection":"ssot-infrastructure"}'
```

## MDDB Search Usage

### Web Interface

**Access**: http://tony-omen.local:3002/

**Features**:
- Collection filtering
- Semantic search with relevance ranking
- Document preview and full content view
- Metadata display (source, collection, timestamps)

**Best For**:
- Browsing documentation structure
- Exploring related content
- Visual search interface
- Quick lookups

### MCP Integration

**Server**: mddb (http://localhost:9001)

**Tools Available**:
- `vector_search`: Semantic search across collections
- `get_document`: Retrieve full document content
- `list_collections`: List all available collections
- `vector_stats`: Get search subsystem statistics

**Usage Examples**:
```javascript
// Semantic search
mcp_call_tool("mddb", "vector_search", {
  "query": "GPU memory management",
  "limit": 5,
  "collection": "kb-features"
})

// Get specific document
mcp_call_tool("mddb", "get_document", {
  "key": "infrastructure-ssot.health",
  "collection": "ssot-infrastructure"
})

// List collections
mcp_call_tool("mddb", "list_collections", {})
```

**Best For**:
- AI assistant queries
- Programmatic access
- Integration with workflows
- Automated searches

### REST API

**Endpoint**: http://tony-omen.local:11023/

**Key Endpoints**:
- `/health`: System health check
- `/v1/stats`: Database statistics
- `/v1/vector-stats`: Search subsystem statistics
- `/v1/vector-search`: Semantic search
- `/v1/vector-reindex`: Reindex collections

**Usage Examples**:
```bash
