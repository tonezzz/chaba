---
category: operations
---

# System Overview

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
