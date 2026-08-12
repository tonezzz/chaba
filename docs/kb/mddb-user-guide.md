---
title: MDDB User Guide
description: Comprehensive user guide for MDDB documentation system including SSOT integration, search usage, and operational procedures
tags: [MDDB, documentation, search, SSOT, user-guide, operations]
created: 2026-08-12
updated: 2026-08-12
category: operations
related: [mddb-implementation-complete.md, ssot-mddb-integration-assessment.md, ssot-documentation-standards.md]
search_keywords: [MDDB usage, documentation search, SSOT editing, auto-sync, semantic search]
---

# MDDB User Guide

## What it is

**Abstract**: Comprehensive user guide for the MDDB documentation system, including SSOT-MDDB integration policy, search usage, operational procedures, and troubleshooting. This guide covers the complete workflow from SSOT YAML editing to MDDB semantic search.

## Context/Background

Implemented on 2026-08-12 as part of the complete migration from legacy documentation systems to a unified MDDB platform. The system provides semantic search across 154+ documents while preserving direct YAML editing as the primary workflow.

## System Overview

**Primary Components**:
- **MDDB Server**: Containerized knowledge base with semantic search
- **SSOT YAML Files**: Directly editable configuration files (source of truth)
- **File Watcher**: Automatic sync service for SSOT changes
- **Web UI**: Browser-based interface at http://tony-omen.local:3002/
- **MCP Integration**: AI-native search via mddb MCP server
- **Health Monitoring**: mcp-health monitoring for reliability

**Document Collections** (13 total):
- Chaba KB: kb-system, kb-development, kb-operations, kb-features
- Trade KB: trade-kb-system, trade-kb-development, trade-kb-operations, trade-kb-features
- SSOT: ssot-infrastructure, ssot-apps, ssot-general
- Chaba Docs: chaba-architecture, chaba-assessments, chaba-reports, chaba-implementation, chaba-general

## SSOT-MDDB Integration Policy (CRITICAL)

### Primary Workflow: Direct YAML Editing

**Policy**: SSOT YAML files are edited directly as the primary workflow

**Why This Matters**:
- YAML is the source of truth for system configuration
- Direct editing is familiar and efficient for infrastructure management
- Preserves existing operational workflows
- No special tools or interfaces required

**How to Edit SSOT**:
1. Navigate to SSOT directory: `/home/tony/CascadeProjects/chaba/docs/ssot/`
2. Edit YAML files directly with your preferred editor
3. Save changes normally
4. File watcher automatically syncs to MDDB within 2 seconds
5. Changes become searchable via MDDB immediately

**Example Workflow**:
```bash
# Edit SSOT configuration
vim /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml

# Make changes and save
# File watcher detects change within 2 seconds
# Sync script updates MDDB automatically
# Changes are now searchable via MDDB
```

### Automatic MDDB Sync

**Mechanism**: File watcher (`watch-ssot-sync.py`) monitors SSOT directory

**Service**: `ssot-sync.service` (systemd background service)

**Trigger**: YAML file modifications trigger sync within 2 seconds

**Transparency**: Sync is automatic and transparent to editing workflow

**Verification**:
```bash
# Check service status
systemctl status ssot-sync.service

# View recent sync activity
journalctl -xeu ssot-sync.service -n 20

# Manual sync test
cd /home/tony/CascadeProjects/chaba-kbman
python3 scripts/sync-ssot-to-mddb.py
```

### MDDB Search Interface

**Purpose**: MDDB provides semantic search across SSOT content

**Benefits**:
- AI-powered search with Ollama embeddings (nomic-embed-text)
- Semantic understanding of content (not just keyword matching)
- High relevance scores (0.45-0.80)
- Fast response times (88-550ms)

**Access Methods**:
1. **Web UI**: http://tony-omen.local:3002/
2. **MCP Integration**: mddb server (http://localhost:9001)
3. **REST API**: http://tony-omen.local:11023/

**Search Usage**:
```bash
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
# Health check
curl -s http://tony-omen.local:11023/health

# Vector search
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check configuration","limit":3}'

# Get statistics
curl -s http://tony-omen.local:11023/v1/vector-stats
```

**Best For**:
- Scripting and automation
- Integration with external tools
- Health monitoring
- Administrative operations

## Operational Procedures

### Adding New Documentation

**SSOT Configuration**:
1. Create new YAML file in appropriate SSOT directory
2. Follow SSOT documentation standards
3. File watcher automatically syncs to MDDB
4. Document becomes searchable immediately

**KB Entries**:
1. Create KB entry in `docs/kb/` directory
2. Follow KB template and standards
3. Run manual sync or wait for periodic sync
4. Document becomes searchable via MDDB

**General Documentation**:
1. Add documentation to appropriate directory
2. Follow project documentation standards
3. Run migration script if needed
4. Document becomes searchable via MDDB

### Updating Existing Documentation

**SSOT Updates**:
1. Edit YAML file directly
2. Save changes
3. File watcher syncs automatically
4. Changes reflected in search immediately

**KB Updates**:
1. Edit KB entry directly
2. Save changes
3. Run manual sync or wait for periodic sync
4. Changes reflected in search

**General Documentation Updates**:
1. Edit documentation file directly
2. Save changes
3. Run migration script if needed
4. Changes reflected in search

### Troubleshooting

**MDDB Not Responding**:
```bash
# Check container status
docker ps | grep mddb

# Check container logs
docker logs mddb -n 50

# Restart container
cd /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb
docker compose restart mddb

# Check health endpoint
curl -s http://tony-omen.local:11023/health
```

**SSOT Auto-Sync Not Working**:
```bash
# Check service status
systemctl status ssot-sync.service

# Check service logs
journalctl -xeu ssot-sync.service -n 50

# Restart service
systemctl restart ssot-sync.service

# Manual sync test
cd /home/tony/CascadeProjects/chaba-kbman
python3 scripts/sync-ssot-to-mddb.py
```

**Search Not Finding Content**:
```bash
# Check SSOT files exist
find /home/tony/CascadeProjects/chaba/docs/ssot -name '*.yml'

# Check MDDB collections
curl -s http://tony-omen.local:11023/v1/vector-stats

# Reindex specific collection
curl -X POST http://tony-omen.local:11023/v1/vector-reindex \
  -H "Content-Type: application/json" \
  -d '{"collection":"ssot-infrastructure","force":true}'
```

## Performance and Quality

**Search Performance**:
- **Relevance Scores**: 0.45-0.80 (high quality semantic understanding)
- **Response Times**: 88-550ms (fast real-time search)
- **Collections**: 13 collections (154+ documents)
- **Embeddings**: Ollama nomic-embed-text (768 dimensions)
- **Algorithm**: Flat with cosine distance metric

**System Resources**:
- **Database Size**: ~50MB (245 documents, 277 revisions)
- **Memory Usage**: 3.5M for file watcher service
- **CPU Usage**: Minimal for search operations
- **Disk Usage**: Efficient storage with indexing

## Best Practices

### SSOT Editing
- **Always edit YAML directly** - this is the primary workflow
- **Follow SSOT documentation standards** for consistency
- **Test changes in staging if available** before production
- **Monitor sync service** to ensure changes propagate
- **Keep YAML structure clean** and well-formatted

### Search Usage
- **Use semantic search** for broad queries and exploration
- **Filter by collection** for targeted searches
- **Use specific terms** for better relevance
- **Check metadata** for source and collection information
- **Leverage MCP integration** for AI-assisted searches

### System Maintenance
- **Monitor health status** via mcp-health
- **Check service logs** regularly for issues
- **Update documentation** as system evolves
- **Backup configuration** and SSOT files regularly
- **Test sync functionality** after changes

## Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Multi-Project Implementation**: docs/kb/mddb-multi-project-implementation.md
- **SSOT-MDDB Integration**: docs/kb/ssot-mddb-integration-assessment.md
- **SSOT Documentation Standards**: docs/kb/ssot-documentation-standards.md
- **Documentation Search**: docs/kb/documentation-search.md

## Support and Escalation

**Common Issues**:
- MDDB container not running
- SSOT sync service not active
- Search not finding expected content
- Performance degradation

**Escalation Path**:
1. Check troubleshooting section above
2. Review system logs and health status
3. Check related documentation
4. Contact system administrator if issues persist

**System Administrator Contact**:
- Monitor health status via mcp-health
- Check system logs for detailed error information
- Review SSOT and MDDB configuration files
- Verify service dependencies and requirements