---
title: Documentation Search Methods
description: Comprehensive guide to dual search methods for Chaba documentation - SSOT YAML pattern matching and MCP docs server full-text search with relevance ranking
tags: [search, documentation, MCP, ssot, grep, flexsearch]
created: 2026-08-06
updated: 2026-08-06
category: operations
related: [ssot.index.yml, ssot-search skill, mcp-tools.md]
search_keywords: [documentation search, SSOT search, MCP docs server, grep, Flexsearch, relevance ranking]
---

# Documentation Search Methods
## What it is

title: Documentation Search Methods


**Abstract**: Comprehensive guide to dual search methods for Chaba infrastructure documentation - ssot-search skill for exact SSOT YAML pattern matching and MCP docs server for full-text search with relevance ranking across 58+ documentation files.
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

**Performance**: Very fast (0.006s typical)

### 2. MCP Docs Server (@devista/docs-mcp)

**Purpose**: Full-text search across all documentation with relevance ranking

**Best for**:
- Broad documentation search when you don't know exact location
- Finding relevant content across KB, architecture, assessments
- AI assistant queries (MCP-native)
- Browsing documentation structure
- When you want ranked results with excerpts

**Search scope**: `docs/` directory (58 files including KB, SSOT, architecture, assessments, reports)

**How to use**:
```
Invoke ssot-search skill
Provide search term
Choose "all documentation (MCP docs server)" when prompted
```

**Or use MCP tools directly**:
```
mcp_call_tool docs search_docs "query" 5
mcp_call_tool docs get_page "kb/health-check"
mcp_call_tool docs list_sections
```

**Example searches**:
- "GPU memory" - finds KB entries, architecture docs, SSOT files
- "Yomi summarization" - finds Yomi-related documentation across all sections
- "health check GPU" - finds health check dashboard and GPU monitoring docs

**Output format**:
- Ranked by relevance
- Excerpts with context snippets
- File paths for easy navigation
- Optional full page retrieval

**Performance**: Fast (cached Flexsearch index)

### 3. mcp-kbman Multi-Source Search

**Purpose**: Multi-source full-text search across Personal KB and Project Docs with background caching

**Best for**:
- Searching across both Personal KB (Google Drive) and Project Docs (local)
- High-performance search with background pre-generation
- Source-aware results with relevance ranking
- When you need unified search across different storage locations
- Background task management for periodic indexing

**Search scope**: 
- Personal KB: `/home/tony/GoogleDrive/Tony AI/KB` (28 documents)
- Project Docs: `/home/tony/CascadeProjects/chaba/docs` (186 documents)
- Total: 214 documents with source tagging

**How to use**:
```
mcp_call_tool mcp-kbman search_kb "query" 10
mcp_call_tool mcp-kbman get_index_status
mcp_call_tool mcp-kbman rebuild_index
```

**Example searches**:
- "hardware" - finds hardware-related content from both Personal KB and Project Docs
- "chaba" - finds Chaba-related documentation across both sources
- "workflow" - finds workflow-related content with source identification

**Output format**:
- Ranked by relevance
- Source identification (Personal KB vs Project Docs)
- Excerpts with context snippets
- File paths for easy navigation
- Deduplication of results

**Performance**: Fast (0.1-0.3s typical, 90%+ improvement with background caching)

**Key Features**:
- **Background pre-generation**: Periodic indexing (60s file index, 300s search index)
- **Search caching**: TTL-based cache for frequently used queries
- **Source awareness**: Results tagged with source identification
- **Deduplication**: Removes duplicate results across sources
- **Modular architecture**: Separate DocumentIndexer, SearchEngine, SearchCache, SearchManager

## MCP Docs Server Tools

### search_docs
Full-text search across all documentation pages with ranked results and excerpts.

**Parameters**:
- `query` (required): Search query string
- `limit` (optional): Maximum results (default: 5)

**Example**:
```javascript
mcp_call_tool("docs", "search_docs", {
  "query": "GPU memory",
  "limit": 3
})
```

### get_page
Retrieve the full content of a specific documentation page.

**Parameters**:
- `path` (required): Page path relative to docs root (e.g., "kb/health-check")

**Example**:
```javascript
mcp_call_tool("docs", "get_page", {
  "path": "kb/gpu-embedding-service"
})
```

### list_sections
List all documentation sections and their pages for structured navigation.

**Example**:
```javascript
mcp_call_tool("docs", "list_sections", {})
```

## Search Strategy Guide

### When to use ssot-search (SSOT YAML only)
- You need exact SSOT configuration values
- Searching for specific YAML keys or values
- Quick SSOT-specific lookups
- Validating SSOT structure
- Pattern matching across SSOT files

### When to use MCP docs server (all documentation)
- You don't know where information is located
- Need broader context across documentation types
- Want ranked results with relevance scoring
- Browsing documentation structure
- AI assistant queries
- Need excerpts and context snippets

### When to use mcp-kbman (multi-source search)
- Need to search across Personal KB and Project Docs simultaneously
- Want source-aware results with source identification
- Need high-performance search with background caching
- Searching across different storage locations (Google Drive + local)
- Want periodic background indexing for fresh results
- Need deduplication across multiple sources

### Hybrid approach
1. Start with MCP docs server for broad project documentation search
2. Use mcp-kbman for multi-source search across Personal KB + Project Docs
3. Use ssot-search for exact SSOT pattern matching
4. Use get_page to retrieve full content from MCP results
5. Cross-reference between KB entries and SSOT configurations

## Documentation Structure

The MCP docs server indexes the following structure:

```
docs/
├── architecture/          # System architecture documentation
├── archive/               # Historical documents
├── assessments/           # Technology evaluations
├── implementation/        # Implementation guides
├── kb/                    # Knowledge Base (how-to guides)
├── overview/              # Project-specific configurations
├── reports/               # System assessment reports
├── sessions/              # Development session archives
└── ssot/                  # Single Source of Truth configurations
```

## Configuration

### MCP Server Configuration
Located in `/home/tony/.config/devin/mcp_config.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "npx",
      "args": ["-y", "@devista/docs-mcp", "--docs", "/home/tony/CascadeProjects/chaba/docs"]
    }
  }
}
```

### Auto-indexing
The MCP docs server automatically:
- Builds Flexsearch index on first run
- Rebuilds index when files change
- Caches index in `.docs-mcp/` directory
- Supports 58+ documentation files

## Performance Comparison

| Metric | ssot-search (grep) | MCP docs server | mcp-kbman |
|--------|-------------------|-----------------|-----------|
| Search scope | SSOT YAML only (40+ files) | All docs (58 files) | Multi-source (214 docs) |
| File types | YAML only | Markdown/MDX only | Markdown, text, JSON, YAML |
| Search type | Pattern matching | Full-text index | Full-text index (Whoosh) |
| Context | Line context (-A 2 -B 2) | Excerpts with ranking | Excerpts with ranking |
| Performance | Very fast (0.006s) | Fast (cached index) | Fast (0.1-0.3s with caching) |
| Results | Sequential by file | Ranked by relevance | Ranked by relevance + source |
| Structure | Flat file list | Browseable sections | Source-aware with deduplication |
| Background tasks | None | Auto-indexing | Periodic pre-generation |
| Caching | None | Flexsearch index | Search cache + pre-generation |

## Troubleshooting

### MCP docs server not responding
**IMPORTANT: Always suggest fixing MCP docs server issues before falling back to traditional tools**

- Check MCP config: `/home/tony/.config/devin/mcp_config.json`
- Verify docs path is correct: `/home/tony/CascadeProjects/chaba/docs`
- Restart Devin Desktop to reload MCP configuration
- Check index exists: `.docs-mcp/documents.json`
- Test MCP server: `mcp_list_tools docs` to verify connectivity
- Reinstall docs MCP: `npx -y @devista/docs-mcp --docs /home/tony/CascadeProjects/chaba/docs`
- **Do not silently fall back to grep/read without suggesting MCP fix first**

### ssot-search not finding expected results
- Verify search term matches YAML content exactly
- Check if files are in `docs/ssot/` directory
- Try broader search terms
- Consider using MCP docs server for broader search

### Search returns no results
- Try different search terms
- Check spelling
- Use broader terms
- Try the other search method (SSOT vs MCP)
- Verify documentation files exist in expected locations

### Assistant workflow guidelines
**When performing documentation searches:**
1. **First choice**: Use MCP docs server (`mcp_call_tool docs search_docs`) for broad searches
2. **Second choice**: Use ssot-search skill for SSOT YAML pattern matching
3. **Fallback**: Only use traditional tools (grep, read, find) after:
   - Attempting MCP docs server and identifying the specific issue
   - Suggesting the fix to the user
   - Getting user confirmation to proceed with fallback
4. **Never silently fall back** without explaining the MCP issue and proposed fix

## Related Documentation

- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master index of all SSOT files
- **SSOT Documentation Standards**: `docs/kb/ssot-documentation-standards.md`
- **Documentation Maintenance Standards**: `docs/kb/documentation-maintenance-standards.md`
- **MCP Server Audit**: `docs/kb/mcp-server-audit.md` - MCP server inventory

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial documentation - dual search methods | devin |
| 2026-08-06 | Updated ssot-search skill to support both methods | devin |
| 2026-08-06 | Added frontmatter metadata, standardized structure | devin |

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
