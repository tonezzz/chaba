---
category: operations
---

# Implementation

### Configuration Management
Centralized configuration in `config.py`:
```python
# Search Configuration
SEARCH_SOURCES = [...]
SEARCH_INDEX_PATH = "/home/tony/.cache/mcp-kbman/search_index"
SEARCH_CACHE_TTL_HOURS = 24

# Task Configuration
FILE_INDEX_INTERVAL_SECONDS = 60
SEARCH_INDEX_INTERVAL_SECONDS = 300
CACHE_CLEANUP_INTERVAL_SECONDS = 3600
```

### Error Handling
- **Index Corruption**: Automatic rebuild on detection
- **Source Unavailable**: Graceful degradation
- **Cache Errors**: Fallback to direct search
- **File Access Errors**: Skip problematic files

### Source Mapping
- **Path Normalization**: Resolves relative vs absolute paths
- **Source Tagging**: Each result tagged with source name
- **Deduplication**: Removes duplicate results across sources
- **Fallback**: "Unknown" source for unmapped paths

## Usage/Commands

### Search Operations
```python
from search.manager import SearchManager

manager = SearchManager()

# Basic search
results = manager.search("query", limit=10)

# Search with source filter
results = manager.search("query", limit=10, source="Personal KB")

# Force cache bypass
results = manager.search("query", limit=10, use_cache=False)
```

### Index Management
```python
# Rebuild index
manager.rebuild_index()

# Get index status
status = manager.get_index_status()

# Clear cache
manager.clear_cache()
```

### MCP Tool Integration
```python
# Through mcp-kbman server
mcp_call_tool("mcp-kbman", "search_kb", {"query": "hardware", "limit": 10})
mcp_call_tool("mcp-kbman", "rebuild_index", {})
mcp_call_tool("mcp-kbman", "get_index_status", {})
mcp_call_tool("mcp-kbman", "clear_search_cache", {})
```

