---
category: operations
---

# SSOT Documentation Standards

## What it is

Comprehensive standards and operational procedures for maintaining Single Source of Truth (SSOT) YAML files across the chaba project ecosystem, ensuring consistency across multiple documentation locations and maintaining documentation quality through systematic validation.

## Context/Background

Implemented on 2026-08-05 to address significant SSOT drift where 10+ files had diverged from source across three locations (docs/ssot/, public/docs/overview/, stacks/web/web/public/). This drift created inconsistency risks and potential operational confusion.

## Key Details

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

## SSOT File Structure

### Standard SSOT File Template
```yaml
title: Descriptive Title
subtitle: Brief description or context
icon: 🎯

# Ideas and notes about this SSOT file
ideas:
  - Purpose of this SSOT file
  - Key concepts or relationships
  - Future improvements or changes needed

# Main content sections
sections:
  - title: Section Name
    icon: 🎯
    layout: list  # Options: list, grid, timeline
    items:
      - label: Item Label
        text: Detailed description or content
        # Optional fields:
        status: active | completed | planned
        priority: high | medium | low
        tags: [tag1, tag2]
        url: https://example.com

# Configuration and metadata (optional)
config:
  version: 1
  last_updated: 2026-08-05
  maintainer: your-name
  related_files:
    - ssot.related-file.yml
    - docs/related-documentation.md
```

### Cross-Reference Requirements

**SSOT Files**:
- Must include `related_files` in config section when applicable
- Should reference related SSOT files and KB entries
- Use relative paths from docs/ root

**KB Entries**:
- Must include `related` field in frontmatter
- Should reference related SSOT files and documentation
- Use markdown link format for external resources

**SSOT Index**:
- All new SSOT files must be registered in ssot.index.yml
- Include descriptive text for discoverability
- Use appropriate section grouping

**App SSOT Standards**:
- Follow `docs/ssot/apps/template.app.yml` structure
- Use standardized section icons and naming
- Include required sections: Core Features, Technical Architecture, Files & Modules, Deployment
- Reference `docs/kb/app-ssot-standards.md` for detailed guidelines

### Configuration-Type Files
Files like `ssot.health.yml`, `ssot.gpu.yml`, `ssot.services.yml` have flexible structures relevant to their specific domain.

### Apps Data Files
Files in the `apps/` subdirectory contain simple data structures for app configurations.

## Validation Rules

### Required Fields
- **Standard SSOT**: Must have `title` field
- **Sections**: Must have `title`, `icon`, and `layout` fields
- **Items**: Must have `label` and `text` fields

### YAML Syntax
- Use consistent 2-space indentation
- No trailing whitespace
- Valid YAML syntax (proper quoting, colons, nesting)
- Use `#` for comments

### Content Consistency
- No duplicate section titles within a file
- No duplicate item labels within a section
- Cross-references must be valid
- Tags should be consistent across similar items

### Hostname Compliance
- **Rule**: Use `.local` hostnames instead of IP addresses
- **Format**: `hostname.local` (e.g., `tony-omen.local`)
- **Exceptions**: Health check configs, network documentation
- **Examples**:
  - ✅ `tony-omen.local`
  - ✅ `tony-dell.local`
  - ❌ `192.168.1.42`
  - ❌ `10.0.0.5`

## Field Types and Values

### Status Field
- `active`: Currently being worked on
- `completed`: Finished work
- `pending`: Planned but not started
- `planned`: Future consideration

### Priority Field
- `high`: Critical or urgent
- `medium`: Normal priority
- `low`: Nice to have

### Layout Field
- `list`: Vertical list of items
- `grid`: Grid layout for items
- `timeline`: Chronological timeline

### Tags Field
- Use kebab-case for tag names
- Be consistent with tag terminology
- Use descriptive tags (e.g., `infrastructure`, `automation`, `shared`)

## Synchronization Process

### Consistency Check Process
1. Compare SSOT files across all three locations
2. Identify diverged files using content comparison
3. Sync from primary source (docs/ssot/) to downstream locations
4. Verify missing files and add to all locations
5. Validate critical documentation cross-location consistency

### Synchronization Strategy
- **Primary Source**: `docs/ssot/` is always the authoritative source
- **Downstream Sync**: Changes propagate to public and web locations
- **Validation**: Cross-location verification for critical documentation
- **Archive Policy**: Completed implementation plans moved to archived/

### Cross-File Consistency
- SSOT files in `docs/ssot/` are the source of truth
- Served copies in `stacks/web/public/` should match
- Public copies in `public/docs/overview/` should match
- Run validation to check for differences

## Maintenance Workflow

### Before Making Changes
1. **Run validation**: `bash scripts/validate-configs.sh`
2. **Check for duplicates**: Review existing similar entries
3. **Consider impact**: Which files/deps will be affected?
4. **Backup current**: Ensure you can revert if needed

### Making Changes
1. **Update SSOT file**: Make your changes following the structure
2. **Run validation**: Ensure no new validation errors
3. **Test affected systems**: Run related scripts/tools
4. **Update related files**: Update documentation, configs, etc.

### After Making Changes
1. **Run full validation**: `bash scripts/validate-configs.sh`
2. **Commit with clear message**: Use conventional commit format
3. **Update served copies**: If applicable, sync to public/served directories
4. **Document changes**: Update relevant documentation

## Tools and Automation

### Validation Scripts
- **SSOT Validation**: `bash scripts/validate-configs.sh`
- **Focus Validation**: `node scripts/validate-focus.mjs`
- **MCP Config Generation**: `python3 scripts/generate-mcp-configs.py`

### Documentation Search Standards
**IMPORTANT: Assistant workflow for documentation searches**

1. **Primary Method**: Use MCP docs server for all documentation searches
   - `mcp_call_tool docs search_docs "query" limit` for broad searches
   - `mcp_call_tool docs get_page "path"` for specific page retrieval
   - `mcp_call_tool docs list_sections` for browsing structure

2. **Secondary Method**: Use ssot-search skill for SSOT YAML pattern matching
   - Exact YAML structure queries
   - SSOT-specific searches
   - When you know exact terms to search for

3. **Fallback Guidelines**: Only use traditional tools (grep, read, find) after:
   - Attempting MCP docs server and identifying specific issue
   - Suggesting the fix to the user (e.g., reinstall MCP server, check config)
   - Getting user confirmation to proceed with fallback
   - **Never silently fall back** without explaining the issue and proposed fix

4. **MCP Troubleshooting**: When MCP docs server fails:
   - Check MCP config: `/home/tony/.config/devin/mcp_config.json`
   - Test connectivity: `mcp_list_tools mddb`
   - Suggest specific fix based on error
   - Reinstall if needed: restart MDDB container

**Reference**: See `docs/kb/documentation-search.md` for comprehensive search methods guide

### Automation Integration
- Consider git hooks for pre-commit validation
- CI/CD integration for automated validation
- Scheduled validation for consistency checks

## Troubleshooting

### Common Validation Errors
- **Missing title field**: Add `title:` to the SSOT file
- **Invalid YAML**: Check indentation, quotes, colons
- **Duplicate entries**: Rename or remove duplicates
- **Hostname violations**: Replace IPs with `.local` hostnames

### SSOT Drift Recurrence
- If drift recurs, identify source of changes in downstream locations
- Establish change control process for downstream locations
- Consider automated synchronization for frequently changed files
- Review access permissions to prevent unauthorized modifications

### Cross-Reference Issues
- **Invalid reference**: Check if referenced file/section exists
- **Broken links**: Update references when files move
- **Circular dependencies**: Restructure to remove cycles

## Related Documentation

- `docs/ssot/` - Primary SSOT file location
- `public/docs/overview/` - Public documentation location
- `stacks/web/web/public/` - Web stack public files
- `docs/kb/subagent-implementation-strategy.md` - Subagent implementation patterns

## Tags

- **ssot**: Single source of truth configuration
- **documentation**: Documentation standards and procedures
- **synchronization**: File synchronization across locations
- **standards**: Documentation quality standards
- **validation**: SSOT validation procedures
- **consistency**: Maintaining consistency across locations
- **quality-control**: Documentation quality control
- **infrastructure**: Infrastructure documentation
- **maintenance**: Documentation maintenance procedures
- **yaml**: YAML configuration files
- **configuration**: Configuration management
- **2026**: Year tag