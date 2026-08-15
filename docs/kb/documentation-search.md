---
title: Documentation Search Methods
description: Comprehensive guide to unified MDDB search for Chaba documentation with SSOT-MDDB integration policy
tags: [search, documentation, MDDB, ssot, semantic-search, ollama, auto-sync]
created: 2026-08-06
updated: 2026-08-15
category: operations
related: [mddb-implementation-complete.md, ssot-documentation-standards.md, ssot-mddb-integration-assessment.md]
search_keywords: [documentation search, MDDB search, semantic search, SSOT auto-sync, Ollama embeddings]
---

# Documentation Search Methods
## What it is

**Abstract**: Comprehensive guide to unified MDDB search for Chaba infrastructure documentation with SSOT-MDDB integration policy - direct YAML editing preserved with automatic sync to MDDB for semantic search across 154+ documents.
## Context/Background

Created 2026-08-06 as part of Chaba infrastructure documentation.


## Overview

Chaba infrastructure provides two complementary search methods for finding information across SSOT configurations, knowledge base entries, and project documentation. Each method serves different use cases and search patterns.

## Purpose

Enables efficient information retrieval across Chaba documentation through dual search approaches - exact pattern matching for SSOT configurations and full-text search with relevance ranking for broader documentation discovery.

## Search Methods Overview

### 1. ssot-search Skill (SSOT YAML Only)

**Purpose**: Exact pattern matching across SSOT YAML configuration files

**Best for**:
- Finding specific SSOT configuration values
- Exact YAML structure queries
- Quick SSOT-specific searches
- When you know the exact term to search for
- SSOT validation and structure queries

**Search scope**: `docs/ssot/**/*.yml` (40+ SSOT YAML files)

**How to use**:
```
Invoke ssot-search skill
Provide search term
Choose "SSOT YAML only" when prompted
```

**Example searches**:
- "GPU memory" - finds GPU-related SSOT configurations
- "health check" - finds health check definitions
- "postgres" - finds database configurations

**Output format**:
- Grouped by SSOT file
- Line context (2 lines before/after matches)
- Match counts per file
- Total files searched and matches found

**Performance**: Fast semantic search (88-550ms response times)

### 2. SSOT Search via MDDB

**Purpose**: Semantic search across SSOT YAML configuration files with automatic sync

**Best for**:
- Semantic search across SSOT YAML configuration files
- Finding related SSOT configurations when you don't know exact file names
- AI assistant queries about infrastructure configuration
- Browsing SSOT structure and relationships
- When you want ranked results with semantic understanding

**Search scope**: `docs/ssot/` directory (40 SSOT YAML files, auto-synced to MDDB)

**How to use**:
```
Access MDDB Panel: http://tony-omen.local:3002/
Use semantic search: "mcp infrastructure configuration"
Filter by collection: ssot-infrastructure, ssot-apps, ssot-general
```

**Or use MCP tools directly**:
```
mcp_call_tool mddb vector_search "query" 5 "ssot-infrastructure"
mcp_call_tool mddb get_document "infrastructure-ssot.mcp"
mcp_call_tool mddb list_collections
```

**Example searches**:
- "mcp infrastructure configuration" - finds SSOT MCP configuration files
- "health check GPU" - finds health check configuration for GPU services
- "services configuration" - finds service definitions and dependencies

**Output format**:
- Ranked by semantic relevance (0.45-0.80 scores)
- Document metadata with file paths
- Collection information for filtering
- Optional full document retrieval

**Performance**: Fast semantic search (110-143ms response times)

**SSOT Integration Policy**:
- **Primary Workflow**: Direct YAML editing (docs/ssot/*.yml)
- **Auto-Sync**: File watcher automatically syncs changes to MDDB within 2 seconds
- **Search Interface**: MDDB provides semantic search across SSOT content
- **Importance**: Direct YAML editing preserved as critical workflow

## MDDB Search Tools

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

## Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Multi-Project Implementation**: docs/kb/mddb-multi-project-implementation.md
- **SSOT-MDDB Integration**: docs/kb/ssot-mddb-integration-assessment.md
- **SSOT Documentation Standards**: docs/kb/ssot-documentation-standards.md
└── ssot/                  # Single Source of Truth configurations
```

## Configuration

### MDDB Configuration
Located in `stacks/web/mddb/docker-compose.yml` and accessed via:
- **Web UI**: http://tony-omen.local:3002/
- **MCP Integration**: mddb server (http://localhost:9001)
- **REST API**: http://tony-omen.local:11023/

### SSOT Auto-Sync Configuration
Located in `/home/tony/CascadeProjects/chaba-kbman/scripts/`:
- **File Watcher**: watch-ssot-sync.py (monitors docs/ssot/ directory)
- **Sync Script**: sync-ssot-to-mddb.py (syncs YAML to MDDB)
- **Systemd Service**: ssot-sync.service (background auto-sync)

## Performance

**MDDB Semantic Search**:
- **Relevance Scores**: 0.45-0.80 (high quality semantic understanding)
- **Response Times**: 88-550ms (fast real-time search)
- **Collections**: 20 collections (340+ documents)
- **Embeddings**: Ollama nomic-embed-text (768 dimensions)
- **Algorithm**: Flat with cosine distance metric

## Troubleshooting

### MDDB not responding
**Check MDDB container status**:
```bash
docker ps | grep mddb
docker logs mddb -n 50
```

**Check MDDB health endpoint**:
```bash
curl -s http://tony-omen.local:11023/health
```

**Restart MDDB if needed**:
```bash
cd /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb
docker compose restart mddb
```

### SSOT auto-sync not working
**Check file watcher service**:
```bash
systemctl --user status ssot-sync.service
```

**Check service logs**:
```bash
journalctl --user -xeu ssot-sync.service -n 50
```

**Restart file watcher**:
```bash
systemctl --user restart ssot-sync.service
```

**Manual sync test**:
```bash
cd /home/tony/CascadeProjects/chaba-kbman
python3 scripts/sync-ssot-to-mddb.py
```

### Search not finding SSOT content
**Check SSOT files exist**:
```bash
find /home/tony/CascadeProjects/chaba/docs/ssot -name '*.yml'
```

**Check MDDB SSOT collections**:
```bash
curl -s http://tony-omen.local:11023/v1/vector-stats
```

**Reindex SSOT collections**:
```bash
curl -X POST http://tony-omen.local:11023/v1/vector-reindex \
  -H "Content-Type: application/json" \
  -d '{"collection":"ssot-infrastructure","force":true}'
```

### Assistant workflow guidelines
**When performing documentation searches:**
1. **Primary choice**: Use MDDB semantic search via MCP (`mcp_call_tool mddb semantic_search`)
2. **Secondary choice**: Use SSOT pattern matching (via ssot-search skill) for exact YAML searches
3. **Tertiary choice**: Fall back to the MCP docs server (`@devista/docs-mcp`) only if MDDB is unavailable or fails, with user confirmation per Service Failure and Fallback Procedures
4. **Traditional tools**: Only use grep/read/find after attempting the above and identifying the specific issue
5. **Never silently fall back** without explaining the issue and proposed fix

## Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Multi-Project Implementation**: docs/kb/mddb-multi-project-implementation.md
- **SSOT-MDDB Integration**: docs/kb/ssot-mddb-integration-assessment.md
- **SSOT Documentation Standards**: docs/kb/ssot-documentation-standards.md
- **Documentation Maintenance Standards**: docs/kb/documentation-maintenance-standards.md

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial dual search methods documentation | devin |
| 2026-08-12 | Migrated to unified MDDB search, removed mcp-kbman references | devin |
| 2026-08-15 | Aligned with .windsurfrules: MDDB primary, ssot-search for exact YAML, docs MCP fallback | devin |

## Tags

- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **database**: database
- **postgres**: postgres
- **redis**: redis
- **mongodb**: mongodb
- **sql**: sql
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **automation**: automation
- **mcp**: mcp
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
