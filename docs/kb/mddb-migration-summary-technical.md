---
category: operations
---

# Technical Details

### System Architecture
```
SSOT YAML Files (docs/ssot/*.yml)
    ↓ (direct editing, primary workflow)
File Watcher (watch-ssot-sync.py)
    ↓ (auto-sync within 2 seconds)
Sync Script (sync-ssot-to-mddb.py)
    ↓ (updates MDDB collections)
MDDB Server (containerized)
    ↓ (semantic search with Ollama)
Search Interfaces (Web UI, MCP, REST API)
```

### Performance Metrics
- **MDDB Container**: 0.77% CPU, 121.9MB memory (0.39% of 30.52GB)
- **MDDB Data**: 47.2MB storage (245 documents, 277 revisions)
- **Ollama Data**: 262MB storage (nomic-embed-text model)
- **GPU Utilization**: 97% (894MB/4096MB used by embeddings)
- **Search Performance**: 88-550ms response times
- **Search Quality**: 0.45-0.80 relevance scores

### Service Dependencies
- **ssot-sync-watcher**: [mddb-api]
- **MDDB Services**: [Ollama embeddings]
- **Monitoring**: mcp-health covers all services

