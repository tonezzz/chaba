---
category: operations
---

# MDDB Search Tools

### semantic_search
**Purpose**: Semantic search across MDDB collections by meaning

**Parameters**:
- `query`: Natural language search query
- `collection`: Specific collection to search (required)
- `top_k`: Maximum number of results to return (default: 10)
- `fields`: Restrict returned metadata keys
- `filter_meta`: Optional metadata filter object
- `include_content`: Include the document body in results

**Usage**:
```
mcp_call_tool mddb semantic_search "mcp infrastructure" "ssot-infrastructure" 5
```

### search_documents
**Purpose**: Filter and sort documents by metadata

**Parameters**:
- `collection`: Required collection name
- `filter_meta`: Metadata filter object
- `limit`, `offset`, `sort`: Pagination and sorting options
- `include_content`: Include the document body

**Usage**:
```
mcp_call_tool mddb search_documents "ssot-infrastructure"
```

### get_stats
**Purpose**: Get MDDB server statistics and available collections

**Usage**:
```
mcp_call_tool mddb get_stats
```

### aggregate
**Purpose**: Compute metadata facets and date histograms

**Parameters**:
- `collection`: Required collection name
- `facets`: Fields to compute value counts
- `histograms`: Date histograms to compute
- `filter_meta`: Optional pre-filter

**Usage**:
```
mcp_call_tool mddb aggregate "ssot-infrastructure"
```

## Search Performance and Quality

**MDDB Semantic Search**:
- **Relevance Scores**: 0.45-0.80 (high quality semantic understanding)
- **Response Times**: 88-550ms (fast real-time search)
- **Collections**: 20 collections (340+ documents)
- **Embeddings**: Ollama nomic-embed-text (768 dimensions)
- **Algorithm**: Flat with cosine distance metric

## Search Strategy Guide

### When to use MDDB semantic search
- You need semantic understanding of content
- You don't know exact file names or structure
- You want ranked results by relevance
- You're searching across multiple collections
- You need AI-native search capabilities

### When to use SSOT pattern matching (if needed)
- You need exact SSOT configuration values
- You know the exact YAML structure you're looking for
- You need to validate SSOT file structure
- You're performing SSOT maintenance tasks

### Search Workflow Recommendations

**Primary**: Use MDDB semantic search
- Most documentation queries
- Cross-collection searches
- AI assistant queries
- Browsing and exploration

**Secondary**: Use SSOT pattern matching (via ssot-search skill)
- Exact configuration value searches
- SSOT structure validation
- Maintenance and debugging tasks

## Migration History

**2026-08-12**: Migrated to MDDB as the primary search method
- MDDB semantic search is the first choice for documentation and SSOT queries
- SSOT pattern matching (ssot-search skill) retained for exact YAML queries
- docs MCP server retained as a fallback when MDDB is unavailable
- Removed mcp-kbman (archived as obsolete)
- All documentation now searchable via MDDB
- SSOT YAML files auto-synced to MDDB for search
- Direct YAML editing preserved as critical workflow

