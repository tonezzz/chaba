---
category: operations
---

# SSOT-MDDB Integration Assessment

**Date**: 2026-08-12
**Purpose**: Assess options for using MDDB for SSOT search while keeping direct YAML editing

## Current State

**SSOT YAML Files**: Direct edit, traditional search (grep, ssot-search)
**MDDB KB Content**: Migrated KB articles, semantic search
**Integration**: None - separate systems with different purposes

## Assessment Criteria

1. **Search Quality**: Semantic search vs traditional pattern matching
2. **Edit Workflow**: Preserve direct YAML editing
3. **Consistency**: Keep YAML and MDDB in sync
4. **Maintenance**: Minimal overhead for sync mechanism
5. **Implementation**: Technical complexity and reliability

## Option 1: SSOT YAML → MDDB Sync (Recommended)

### Architecture
```
SSOT YAML Files (Direct Edit)
    ↓ (sync mechanism)
MDDB Collections (SSOT Search)
```

### Implementation
- **Sync Script**: Monitor SSOT YAML files, convert to MDDB format
- **Collection**: `ssot-infrastructure`, `ssot-apps`, `ssot-kb`, etc.
- **Metadata**: `source: ssot`, `original_path: rel_path`, `type: yaml`
- **Trigger**: Manual sync or file watcher

### Conversion Strategy
```python
# YAML → MDDB document
def convert_yaml_to_mddb(yaml_path):
    with open(yaml_path) as f:
        yaml_content = f.read()
    
    return {
        "collection": get_ssot_collection(yaml_path),
        "key": yaml_path.replace('/', '-'),
        "content_md": f"# {yaml_path}\n\n```yaml\n{yaml_content}\n```",
        "meta": {
            "title": yaml_path,
            "source": "ssot",
            "original_path": yaml_path,
            "type": "yaml"
        }
    }
```

### Benefits
- ✅ Preserves direct YAML editing workflow
- ✅ Enables semantic search across SSOT
- ✅ YAML remains source of truth
- ✅ Minimal implementation complexity
- ✅ Can sync on-demand or automated

### Challenges
- ⚠️ Requires sync mechanism maintenance
- ⚠️ Potential sync lag (YAML vs MDDB)
- ⚠️ YAML syntax in Markdown may affect search quality
- ⚠️ Need to handle YAML structure in search

### Implementation Complexity: Medium

## Option 2: SSOT Documentation in MDDB

### Architecture
```
SSOT YAML Files (Direct Edit - Config Only)
SSOT Documentation (MDDB - Search Only)
```

### Implementation
- **SSOT YAML**: Keep for actual configuration values
- **SSOT Documentation**: Create MDDB entries with SSOT descriptions
- **Metadata**: Link to YAML files for reference
- **Content**: Human-readable SSOT descriptions, not raw YAML

### Example Structure
```markdown
# SSOT: MCP Infrastructure Configuration

## Overview
Single source of truth for MCP server configuration...

## Server Definitions
### github
- Name: GitHub Integration
- Description: GitHub API integration for workflow automation
- Implementation: docker ghcr.io/github/github-mcp-server:latest

## Related Files
- docs/ssot/infrastructure/ssot.mcp.yml
- ~/.config/devin/mcp_config.json
```

### Benefits
- ✅ Preserves direct YAML editing
- ✅ High-quality semantic search (human-readable content)
- ✅ Clean separation of config vs documentation
- ✅ No sync mechanism needed
- ✅ Better search relevance

### Challenges
- ⚠️ Requires maintaining documentation separately from YAML
- ⚠️ Potential duplication between YAML and documentation
- ⚠️ Documentation may become outdated
- ⚠️ Higher maintenance overhead

### Implementation Complexity: Low

## Option 3: SSOT YAML with Frontmatter Metadata

### Architecture
```
SSOT YAML Files (Direct Edit)
    ↓ (frontmatter extraction)
MDDB Collections (Search + Metadata)
```

### Implementation
- **SSOT YAML**: Add frontmatter metadata to YAML files
- **Extraction**: Parse frontmatter for search indexing
- **Content**: YAML content + frontmatter in MDDB
- **Metadata**: Extracted from frontmatter for better search

### Example Structure
```yaml
---
title: MCP Infrastructure Configuration
description: Single source of truth for MCP server configuration
tags: [mcp, infrastructure, configuration]
collection: ssot-infrastructure
---

# SSOT: MCP Infrastructure Configuration
title: MCP Infrastructure Configuration
subtitle: Single source of truth for MCP server configuration
icon: 🔧
...
```

### Benefits
- ✅ Preserves direct YAML editing
- ✅ Rich metadata for better search
- ✅ Single source of truth (YAML file)
- ✅ No separate documentation needed
- ✅ Frontmatter is standard practice

### Challenges
- ⚠️ Requires modifying all SSOT YAML files
- ⚠️ Frontmatter parsing complexity
- ⚠️ YAML validation becomes more complex
- ⚠️ Frontmatter may interfere with YAML processing

### Implementation Complexity: Medium-High

## Option 4: Hybrid SSOT Search

### Architecture
```
SSOT YAML Files (Direct Edit)
    ↓ (dual indexing)
MDDB (Semantic Search) + ssot-search (Pattern Search)
```

### Implementation
- **SSOT YAML**: Keep as-is, direct edit
- **MDDB**: Sync for semantic search (Option 1)
- **ssot-search**: Keep for exact pattern matching
- **Unified Interface**: Choose search method based on query type

### Search Strategy
```python
def search_ssot(query):
    if is_semantic_query(query):
        return mddb_search(query, "ssot-*")
    else:
        return ssot_search(query, "ssot/*.yml")
```

### Benefits
- ✅ Best of both worlds (semantic + pattern search)
- ✅ Preserves direct YAML editing
- ✅ No single point of failure
- ✅ Flexible search capabilities

### Challenges
- ⚠️ Requires maintaining two search systems
- ⚠️ Search method selection complexity
- ⚠️ Higher infrastructure overhead
- ⚠️ User confusion about which search to use

### Implementation Complexity: Medium

## Recommendation

### Option 1 (SSOT YAML → MDDB Sync) - Recommended

**Rationale**:
- Preserves direct YAML editing workflow
- Enables semantic search across SSOT
- Reasonable implementation complexity
- YAML remains source of truth
- Can implement incremental sync

**Implementation Plan**:
1. Create sync script for SSOT YAML → MDDB
2. Add SSOT-specific collections to MDDB
3. Implement manual sync command
4. Add file watcher for automated sync (optional)
5. Test search quality with YAML content

**Pilot Implementation**:
- Start with `docs/ssot/infrastructure/ssot.mcp.yml`
- Create `ssot-infrastructure` collection
- Test semantic search quality
- Evaluate sync mechanism reliability

### Alternative: Option 2 (SSOT Documentation in MDDB)

**Use Case**: If semantic search quality with YAML content is poor
- Create human-readable SSOT documentation in MDDB
- Link to YAML files for reference
- Maintain documentation separately from config
- Better search relevance, higher maintenance

## Technical Considerations

### YAML Content in MDDB
**Challenge**: YAML syntax may affect semantic search quality
**Solution**: Format as Markdown code blocks with descriptive headers
**Example**:
```markdown
# MCP Infrastructure Configuration

## Server: github
- Name: GitHub Integration
- Description: GitHub API integration
- Implementation: docker ghcr.io/github/github-mcp-server:latest

## YAML Content
```yaml
github:
  name: GitHub Integration
  description: GitHub API integration for workflow automation
  implementation: docker ghcr.io/github/github-mcp-server:latest
```
```

### Sync Mechanism
**Approach**: Manual sync command + optional file watcher
**Command**: `scripts/sync-ssot-to-mddb.py`
**Trigger**: Manual after SSOT changes, or automated via inotify
**Validation**: Check YAML syntax before sync

### Collection Structure
**Proposed Collections**:
- `ssot-infrastructure`: Infrastructure SSOT files
- `ssot-apps`: Application SSOT files
- `ssot-kb`: Knowledge base SSOT files
- `ssot-health`: Health check SSOT files

### Metadata Schema
```json
{
  "meta": {
    "title": "ssot/infrastructure/ssot.mcp.yml",
    "source": "ssot",
    "original_path": "ssot/infrastructure/ssot.mcp.yml",
    "type": "yaml",
    "collection": "ssot-infrastructure",
    "last_synced": "2026-08-12T16:00:00Z"
  }
}
```

## Next Steps

1. **Pilot Test**: Sync one SSOT file to MDDB, test search quality
2. **Evaluate Results**: Assess semantic search relevance with YAML content
3. **Decision**: Choose between Option 1 and Option 2 based on pilot
4. **Implementation**: Deploy chosen approach across all SSOT files
5. **Documentation**: Update SSOT maintenance procedures

## Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Multi-Project Implementation**: docs/kb/mddb-multi-project-implementation.md
- **SSOT Documentation**: docs/ssot/ssot.documentation-infrastructure.yml
- **SSOT Validation**: docs/ssot/ssot.validation-patterns.yml

## Implementation Status

**Status**: ✅ Completed (2026-08-12)

**Implemented**: Option 1 (SSOT YAML → MDDB Sync) with file watcher automation

**Components**:
- **Sync Script**: `scripts/sync-ssot-to-mddb.py` - Manual sync command
- **File Watcher**: `scripts/watch-ssot-sync.py` - Auto-sync on YAML changes
- **Systemd Service**: `scripts/ssot-sync.service` - Background service
- **Collections**: ssot-infrastructure (10), ssot-apps (15), ssot-general (15)

**Results**:
- **Files Synced**: 40/40 SSOT YAML files
- **Search Quality**: Excellent (0.54-0.72 relevance scores)
- **Response Time**: Fast (110-143ms)
- **Auto-Sync**: Functional with file watcher

## Health Monitoring Implementation (2026-08-12)

**Status**: ✅ Completed

**mcp-health Extension**: SSOT file watcher and MDDB monitoring integration

**Components**:
- **SSOT Health Config**: `docs/ssot/infrastructure/ssot.health.yml` - Updated with SSOT services
- **Systemd Service**: `ssot-sync.service` - Deployed to `/etc/systemd/system/`
- **Service Status**: Active and running (systemctl status ssot-sync.service)

**Health Checks Added**:
- **ssot-sync-watcher**: Systemd service monitoring for SSOT file watcher
- **mddb-api**: HTTP health endpoint (port 11023)
- **mddb-stats**: HTTP stats endpoint (port 11023/v1/stats)
- **mddb-vector-stats**: HTTP vector stats endpoint (port 11023/v1/vector-stats)
- **mddb-metrics**: HTTP metrics endpoint (port 11023/metrics)
- **mddb-container**: Container health check for MDDB service

**Service Configuration**:
- **Criticality**: ssot-sync-watcher marked as "important" service
- **Service Group**: ssot-sync group includes all SSOT and MDDB services
- **Dependencies**: ssot-sync-watcher → mddb-api dependency tracking
- **Recovery Actions**: Comprehensive recovery steps for each service

**Monitoring Results**:
- **SSOT Sync Watcher**: Active (systemd service running)
- **MDDB API**: Healthy (HTTP 200, 158ms response time)
- **MDDB Stats**: Healthy (HTTP 200, 153ms response time)
- **MDDB Vector Stats**: Healthy (HTTP 200, 148ms response time)
- **MDDB Metrics**: Healthy (HTTP 200, 158ms response time)
- **MDDB Container**: Running (docker container healthy)

**MCP Tools Integration**:
- **check_health**: Service-specific health checks
- **get_health_status**: Overall system health monitoring
- **analyze_dependencies**: Dependency analysis for ssot-sync-watcher
- **get_troubleshooting_info**: Enhanced troubleshooting for SSOT services

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-12 | Initial SSOT-MDDB integration assessment | devin |
| 2026-08-12 | Implementation completed - Option 1 with file watcher | devin |

## Tags

- ssot
- mddb
- integration
- yaml-sync
- semantic-search
- documentation-strategy
- hybrid-search