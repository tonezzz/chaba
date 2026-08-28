---
category: operations
---

# Search Methods Overview

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

