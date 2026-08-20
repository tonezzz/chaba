---
category: operations
---

# Key Details

### SSOT Locations
- **Primary Source**: `docs/ssot/` - authoritative SSOT files
- **Public Documentation**: `public/docs/overview/` - public-facing documentation
- **Web Stack**: `stacks/web/web/public/` - web application public files

### Directory Structure
```
docs/ssot/
├── ssot.validation-patterns.yml    # Validation rules and patterns
├── ssot.devin.tools.yml             # MCP server configurations
├── ssot.docs.yml                    # Documentation structure
├── ssot.libs.yml                    # Library dependencies
├── ssot.ui.yml                      # UI components and patterns
├── ssot.diagrams.yml                # System diagrams
├── ssot.improvements.yml            # System improvements tracking
├── ssot.kb.yml                      # Knowledge base session memories
├── ssot.focus.yml                   # Strategic focus management
├── template.yml                     # Template for new SSOT files
├── infrastructure/
│   ├── ssot.gpu.yml                 # GPU configuration
│   ├── ssot.health.yml              # Health check configuration
│   ├── ssot.health.home.yml        # Home network health checks
│   ├── ssot.health.mobile.yml       # Mobile network health checks
│   └── ssot.services.yml            # Service definitions
└── apps/
    ├── ssot.apps.yml                # Master apps configuration
    ├── ssot.apps.aihub.yml          # AI Hub app
    ├── ssot.apps.cams.yml           # Cams app
    ├── ssot.apps.chaba.yml          # Chaba app
    └── ... (other app configs)
```

### File Naming Conventions
- **Prefix**: All SSOT files must start with `ssot.`
- **Format**: Use kebab-case (e.g., `ssot.devin.tools.yml`)
- **Descriptive**: Names should clearly indicate the file's purpose
- **Consistent**: Follow established patterns for similar files

### SSOT-MDDB Integration Policy (CRITICAL)

**Primary Workflow**: Direct YAML Editing
- **Policy**: SSOT YAML files are edited directly as the primary workflow
- **Reason**: YAML is the source of truth, direct editing is familiar and efficient
- **Tools**: Text editors, IDEs, direct file manipulation
- **Location**: `docs/ssot/` directory
- **Importance**: This policy is critical and must be preserved

**Automatic MDDB Sync**
- **Policy**: SSOT YAML files are automatically synced to MDDB for semantic search
- **Mechanism**: File watcher (`watch-ssot-sync.py`) monitors `docs/ssot/` directory
- **Trigger**: YAML file modifications trigger sync within 2 seconds
- **Service**: `ssot-sync.service` (systemd background service)
- **Transparency**: Sync is automatic and transparent to editing workflow
- **Importance**: Enables semantic search without disrupting editing workflow

**MDDB Search Interface**
- **Purpose**: MDDB provides semantic search across SSOT content
- **Benefit**: AI-powered search with Ollama embeddings (nomic-embed-text)
- **Collections**: `ssot-infrastructure`, `ssot-apps`, `ssot-general`
- **Access**: Web UI (http://tony-omen.local:3002/), MCP integration, REST API
- **Performance**: 0.54-0.72 relevance scores, 110-143ms response times
- **Importance**: Provides enhanced search capabilities while preserving direct editing

**Workflow Summary**
```
Direct YAML Editing (docs/ssot/*.yml)
    ↓ (automatic, 2-second delay)
File Watcher Detection
    ↓ (triggers sync script)
MDDB Sync (sync-ssot-to-mddb.py)
    ↓ (updates MDDB collections)
Semantic Search (via MDDB)
```

**Monitoring and Recovery**
- **Health Monitoring**: mcp-health monitors file watcher and MDDB health
- **Service Status**: `ssot-sync.service` monitored as "important" service
- **Recovery**: File watcher restart, manual sync, YAML validation
- **Dependencies**: ssot-sync-watcher → mddb-api dependency tracking
- **Alerts**: Configured for service failures and sync issues

**Policy Rationale**
- **Preserves Familiar Workflow**: Direct YAML editing remains unchanged
- **Enables Enhanced Search**: MDDB provides semantic search without workflow disruption
- **Automatic Sync**: Transparent synchronization eliminates manual steps
- **Source of Truth**: YAML files remain authoritative
- **Rollback Capability**: Original YAML files always available
- **Health Monitoring**: Comprehensive monitoring ensures reliability

### Cross-Reference Standards
- **SSOT to KB**: Each SSOT file should reference related KB entries
- **KB to SSOT**: Each KB entry should reference related SSOT files
- **Related Documentation**: Include links to related documentation in both directions
- **SSOT Index**: All new SSOT files must be registered in ssot.index.yml
- **Consistent Format**: Use standardized related documentation section format

