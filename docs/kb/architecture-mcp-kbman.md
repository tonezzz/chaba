---
title: mcp-kbman Architecture
description: Modular search architecture for mcp-kbman with separate DocumentIndexer, SearchEngine (Whoosh), SearchCache, and SearchManager components for maintainability and performance
tags: [mcp-kbman, architecture, search, whoosh, modular, performance]
created: 2026-08-11
updated: 2026-08-11
category: operations
related: [../../CascadeProjects/chaba/docs/kb/mcp-tools.md, ../../CascadeProjects/chaba/docs/kb/documentation-search.md, background-task-caching.md]
search_keywords: [mcp-kbman architecture, search engine, whoosh, modular design, document indexer]
---

# mcp-kbman Architecture

## What it is

Modular search architecture for mcp-kbman MCP server providing multi-source full-text search across Personal KB and Project Docs with background caching and performance optimization through component separation.

## Context/Background

Implemented on 2026-08-11 as part of mcp-kbman development to address the need for high-performance, maintainable search across multiple documentation sources while following modular design principles for easy maintenance and extensibility.

## Key Details

### Technical Details
- **Search Engine**: Whoosh (Python full-text search library)
- **Architecture Pattern**: Modular component separation
- **Index Location**: Local filesystem `/home/tony/.cache/mcp-kbman/search_index` (moved from GDrive mount for performance)
- **Cache Strategy**: TTL-based search cache with background pre-generation
- **Performance**: 0.1-0.3s search time, 90%+ improvement with caching

### Component Architecture

#### 1. DocumentIndexer (`search/indexer.py`)
**Purpose**: Scans configured source directories and extracts document contents

**Responsibilities**:
- Directory scanning for configured sources
- Content extraction from various file formats (Markdown, text, JSON, YAML)
- Source tagging for multi-source identification
- File metadata collection (size, modification time, MIME type)

**Key Methods**:
- `scan_directory(source_path, source_name)` - Scan a source directory
- `extract_content(file_path)` - Extract text content from files
- `detect_mime_type(file_path)` - Detect file MIME type

**Configuration**:
```python
SOURCES = [
    {"name": "Personal KB", "path": "/home/tony/GoogleDrive/Tony AI/KB"},
    {"name": "Project Docs", "path": "/home/tony/CascadeProjects/chaba/docs"}
]
```

#### 2. SearchEngine (`search/engine.py`)
**Purpose**: Whoosh-based full-text indexing and querying

**Responsibilities**:
- Whoosh index creation and management
- Document indexing with source tagging
- Query processing with relevance ranking
- Excerpt generation for search results
- Result deduplication

**Key Methods**:
- `create_index(index_path)` - Create new Whoosh index
- `add_document(doc_id, title, content, source, path)` - Index a document
- `search(query, limit)` - Search with relevance ranking
- `get_excerpt(content, query)` - Generate context excerpts
- `rebuild_index()` - Rebuild entire index

**Whoosh Schema**:
```python
schema = Schema(
    doc_id=ID(stored=True, unique=True),
    title=TEXT(stored=True),
    content=TEXT,
    source=TEXT(stored=True),
    path=TEXT(stored=True),
    modified=DATETIME(stored=True)
)
```

#### 3. SearchCache (`search/cache.py`)
**Purpose**: TTL-based caching for search results

**Responsibilities**:
- Search result caching with TTL
- Cache key generation from query parameters
- Cache expiration and cleanup
- Cache statistics tracking

**Key Methods**:
- `get(cache_key)` - Retrieve cached result
- `set(cache_key, result, ttl)` - Cache result with TTL
- `clear()` - Clear all cache
- `get_stats()` - Get cache statistics

**Configuration**:
```python
SEARCH_CACHE_TTL_HOURS = 24
MAX_CACHE_SIZE_MB = 100
```

#### 4. SearchManager (`search/manager.py`)
**Purpose**: Coordinates indexing, searching, and caching

**Responsibilities**:
- Component coordination (Indexer + Engine + Cache)
- Multi-source search orchestration
- Index status tracking
- Source path normalization
- Result aggregation and formatting

**Key Methods**:
- `search(query, limit, use_cache)` - Unified search interface
- `rebuild_index()` - Rebuild search index
- `get_index_status()` - Get index statistics
- `clear_cache()` - Clear search cache

**Search Flow**:
1. Check cache for existing results
2. If cache miss, query SearchEngine
3. Apply source filtering if specified
4. Deduplicate results
5. Cache results for future queries
6. Return formatted results with source tags

### Performance Architecture

#### Background Pre-Generation
- **File Index**: Every 60 seconds
- **Search Index**: Every 300 seconds
- **Cache Cleanup**: Every 3600 seconds
- **Performance**: 90%+ improvement through pre-generation

#### Caching Strategy
- **Search Cache**: TTL-based (24 hours default)
- **Pre-Generated Data**: File indexes, search indexes
- **Cache Size Limit**: 100MB default
- **Cache Cleanup**: Automatic expiration

#### Index Performance
- **Index Build**: ~0.15s for 214 documents
- **Search Query**: ~0.1-0.3s typical
- **Cached Query**: ~0.004s (90% faster)

## Implementation

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

## Troubleshooting

### Index Corruption
**Issue**: Whoosh index segment files missing or corrupted
**Solution**: 
- Clear index directory: `rm -rf /home/tony/.cache/mcp-kbman/search_index/`
- Rebuild index: `manager.rebuild_index()`
- Index is now on local filesystem for better performance

### Slow Search Performance
**Issue**: Search queries taking longer than expected
**Solution**:
- Check if cache is enabled
- Verify background tasks are running
- Consider increasing cache TTL
- Index is now on local filesystem for better performance

### Source Mapping Issues
**Issue**: Results showing "Unknown" source
**Solution**:
- Check source path configuration
- Verify path normalization logic
- Ensure source paths are absolute
- Check for symbolic links or mount points

### Memory Usage
**Issue**: High memory usage from large indexes
**Solution**:
- Reduce cache size limit
- Increase cache cleanup frequency
- Consider index partitioning by source
- Monitor memory usage with `get_index_status()`

## Related Documentation

- **[mcp-tools.md](../../CascadeProjects/chaba/docs/kb/mcp-tools.md)** - MCP server inventory including mcp-kbman
- **[documentation-search.md](../../CascadeProjects/chaba/docs/kb/documentation-search.md)** - Multi-source search comparison
- **[background-task-caching.md](meta/background-task-caching.md)** - Background task system details
- **[kb-workflow-integration.md](meta/kb-workflow-integration.md)** - KB workflow compliance

## Tags

- **mcp-kbman**: MCP knowledge base management server
- **architecture**: System architecture and design
- **search**: Full-text search implementation
- **whoosh**: Python search engine library
- **modular**: Component-based design
- **performance**: Performance optimization
- **caching**: Cache strategy and implementation