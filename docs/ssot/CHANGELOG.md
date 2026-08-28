# SSOT Change Log

This file tracks significant changes to SSOT files for audit trail and rollback capability.

## Format
- Date: YYYY-MM-DD
- File: Path to SSOT file
- Change Type: major|minor|patch
- Description: Brief description of change
- Impact: Files or systems affected
- Rollback: Git commit hash for rollback if needed

## Recent Changes

### 2026-08-18
- **File**: docs/ssot/ssot.terminology.yml
- **Change Type**: minor
- **Description**: Created canonical terminology SSOT defining assistant context, rules, memories, SSOT, KB, and focus/decision vocabulary; also lists recent ambiguous terms and recommended corrections.
- **Impact**: Provides a shared vocabulary for decision-tree optimization and reduces terminology drift in sessions.
- **Rollback**: Delete docs/ssot/ssot.terminology.yml and remove its index entry.

- **File**: docs/ssot/ssot.index.yml
- **Change Type**: patch
- **Description**: Added ssot.terminology.yml to the Core / Cross-Project section.
- **Impact**: Index now reflects the new terminology SSOT.
- **Rollback**: Revert the ssot.index.yml addition.

### 2026-08-12
- **File**: docs/ssot/ssot.mysystem.home.yml
- **Change Type**: minor
- **Description**: Added hardware specifications section with CPU (Intel i7-9750H @ 2.60GHz max, 800MHz min), GPU, and memory details. Added CPU frequency monitoring status.
- **Impact**: SSOT now documents system hardware specifications and CPU monitoring capabilities
- **Rollback**: Remove hardware specifications section

- **File**: scripts/health-monitor.sh
- **Change Type**: minor
- **Description**: Enhanced with CPU frequency and throttling detection. Added checks for current vs max frequency, thermal throttling under load, CPU governor state, and minimum frequency detection.
- **Impact**: Health monitoring now detects CPU throttling and performance limitations with alerting
- **Rollback**: Revert to previous health-monitor.sh version

- **File**: docs/ssot/infrastructure/ssot.health.yml
- **Change Type**: minor
- **Description**: Enhanced chaba-health-monitor-timer with CPU frequency verification and recovery actions. Added system service group for CPU monitoring. Updated service criticality to include cpu-frequency-monitor as optional.
- **Impact**: Health check configuration now includes CPU frequency monitoring with troubleshooting guidance
- **Rollback**: Remove CPU frequency monitoring enhancements

- **File**: docs/ssot/ssot.improvements.yml
- **Change Type**: minor
- **Description**: Added CPU Frequency Monitoring improvement entry with completion status and technical details. Updated completed work timeline to include CPU monitoring.
- **Impact**: SSOT improvements now document CPU frequency monitoring implementation
- **Rollback**: Remove CPU Frequency Monitoring improvement entry

- **File**: docs/kb/health-check.md
- **Change Type**: minor
- **Description**: Added CPU frequency monitoring section with specifications, monitoring capabilities, alert conditions, recovery actions, and verification commands. Updated frontmatter with CPU-related tags.
- **Impact**: Health check KB now includes comprehensive CPU monitoring documentation
- **Rollback**: Remove CPU frequency monitoring section

- **File**: docs/ssot/ssot.index.yml
- **Change Type**: patch
- **Description**: Updated ssot.mysystem.home.yml description to include hardware specifications. Updated infrastructure/ssot.health.yml description to mention CPU frequency monitoring.
- **Impact**: SSOT index now reflects hardware documentation and CPU monitoring capabilities
- **Rollback**: Revert index descriptions

### 2026-08-12
- **File**: docs/ssot/infrastructure/ssot.mcp.yml
- **Change Type**: minor
- **Description**: Added mddb MCP server entry with configuration details, updated mcp-health notes to include Phase 4 completion and new tools
- **Impact**: SSOT now documents mddb MCP server configuration and mcp-health Phase 4 enhancements
- **Rollback**: Remove mddb entry and revert mcp-health notes

- **File**: mcp-servers/mcp-health/server.js
- **Change Type**: major
- **Description**: Added 8 new MCP health server tools for streamlined health monitoring: quick_health (pass/fail for critical services), check_group (group-based checks), reload_config (YAML config reload), get_health_score (overall system metric 0-100), batch_check (parallel service checks), set_auto_recovery (automated recovery policies), get_service_template (service templates), sync_to_mddb (health history integration)
- **Impact**: Health monitoring now provides quick status checks, group-based operations, config reload without restart, health scoring, parallel processing, auto-recovery, service templates, and mddb integration
- **Rollback**: Revert to previous server.js version

- **File**: docs/ssot/ssot.improvements.yml
- **Change Type**: minor
- **Description**: Added MCP Health Server Phase 4 - Predictive Analytics as future enhancement with ML-based failure prediction, advanced alerting, webhook notifications, and integration with monitoring services
- **Impact**: Documents future roadmap for predictive health monitoring and advanced alerting capabilities
- **Rollback**: Remove Phase 4 improvement entry

- **File**: docs/ssot/infrastructure/ssot.health.yml
- **Change Type**: minor
- **Description**: Added mddb-mcp health check endpoint to monitor MCP server connectivity, added to ssot-sync service group for dependency tracking
- **Impact**: Health monitoring now includes mddb MCP endpoint with recovery actions for configuration issues
- **Rollback**: Remove mddb-mcp health check entry

- **File**: docs/kb/mddb-mcp-configuration.md
- **Change Type**: major
- **Description**: Created comprehensive KB entry for mddb MCP server configuration including port mapping, path requirements, troubleshooting, and health monitoring integration
- **Impact**: Documents correct mddb MCP configuration and provides troubleshooting guidance for future issues
- **Rollback**: Delete KB entry

### 2026-08-12
- **File**: docs/ssot/infrastructure/ssot.health.yml
- **Change Type**: minor
- **Description**: Added playlived service to health monitoring with browser installation verification, updated service criticality to include playlived as important service, added automation service group
- **Impact**: Health monitoring now includes playlived service with specific recovery actions for Playwright browser issues
- **Rollback**: Remove playlived service entry from health config

- **File**: docs/ssot/infrastructure/ssot.health.yml
- **Change Type**: patch
- **Description**: Fixed duplicate playlived_browsers_missing key in recovery_actions section
- **Impact**: YAML syntax error resolved, health config now valid
- **Rollback**: Revert duplicate key removal

- **File**: docs/ssot/infrastructure/ssot.mcp.yml
- **Change Type**: major
- **Description**: Updated MCP health server status to Phase 3 complete with enhanced monitoring capabilities, added new tools (check_port_conflicts, validate_proxy_config, restart_service, get_troubleshooting_info)
- **Impact**: MCP health server now provides advanced monitoring with port conflict detection, proxy validation, automated recovery, and enhanced troubleshooting
- **Rollback**: Revert to previous MCP health server status

- **File**: docs/ssot/ssot.improvements.yml
- **Change Type**: major
- **Description**: Marked MCP Health Server Phase 3 Enhanced Monitoring as completed, added Playlive Service Reliability Enhancement as completed
- **Impact**: Accurate tracking of completed infrastructure improvements with detailed implementation notes
- **Rollback**: Revert improvement entries to previous status

- **File**: .agents/skills/health-check/SKILL.md
- **Change Type**: major
- **Description**: Deprecated old health-check skill in favor of MCP health server tools, added migration guide and deprecation notice
- **Impact**: Health monitoring now uses MCP tools as authoritative interface, old skill maintained for backward compatibility
- **Rollback**: Restore original skill implementation

- **File**: docs/kb/mcp-health-vs-old-skill-comparison.md
- **Change Type**: major
- **Description**: Created comprehensive feature comparison between MCP health server and old health-check skill with parity assessment and migration benefits
- **Impact**: Complete analysis of MCP health server capabilities and migration justification
- **Rollback**: Delete comparison document

### 2026-08-12 (Earlier)
- **File**: docs/ssot/ssot.index.yml
- **Change Type**: patch
- **Description**: Fixed index inconsistencies - removed references to non-existent ssot.health.home.yml and ssot.health.mobile.yml, added mcp-health server documentation, added ssot.maintenance.yml reference
- **Impact**: Index now accurately reflects actual SSOT file structure
- **Rollback**: Previous commit before index updates

- **File**: docs/ssot/ssot.maintenance.yml
- **Change Type**: major
- **Description**: Created comprehensive SSOT maintenance framework with daily/weekly/monthly/quarterly schedules, quality metrics, change tracking procedures, and automation tools documentation
- **Impact**: New systematic approach to SSOT maintenance and quality assurance
- **Rollback**: Delete ssot.maintenance.yml to revert

- **File**: docs/ssot/CHANGELOG.md
- **Change Type**: major
- **Description**: Created SSOT change log for tracking significant changes, audit trail, and rollback capability
- **Impact**: Systematic change tracking for all SSOT modifications
- **Rollback**: Delete CHANGELOG.md to revert

- **File**: .git/hooks/pre-commit
- **Change Type**: major
- **Description**: Implemented automated SSOT validation pre-commit hook with YAML syntax validation, hostname compliance checking, URL placeholder validation, and required fields verification
- **Impact**: All SSOT commits now pass automated validation before acceptance
- **Rollback**: Remove .git/hooks/pre-commit file

- **File**: docs/ssot/infrastructure/ssot.health.yml
- **Change Type**: patch
- **Description**: Fixed YAML syntax by quoting URL placeholders to prevent parsing errors
- **Impact**: Resolved "Unexpected scalar" errors in health configuration
- **Rollback**: Revert URL placeholder quoting changes

- **File**: docs/ssot/infrastructure/ssot.mcp.yml
- **Change Type**: major
- **Description**: Added mcp-health server with operational status and completed phase documentation
- **Impact**: New centralized health monitoring capability via MCP
- **Rollback**: Remove mcp-health server entry from MCP config

- **File**: docs/ssot/ssot.improvements.yml
- **Change Type**: major
- **Description**: Updated MCP health server implementation status to completed with detailed feature list and gap fixes including expected status/state validation
- **Impact**: Accurate tracking of completed infrastructure improvements
- **Rollback**: Revert improvement entry to previous status

- **File**: docs/ssot/infrastructure/ssot.services.yml
- **Change Type**: minor
- **Description**: Added MDDB services (mddb and mddb-panel containers) with configuration details, ports, container IPs, and routing information
- **Impact**: SSOT now documents MDDB Personal Knowledge Base system
- **Rollback**: Remove mddb and mddb-panel entries from services config

- **File**: docs/ssot/infrastructure/ssot.health.yml
- **Change Type**: minor
- **Description**: Added MDDB API and MDDB Panel health check endpoints, updated service groups to include MDDB services
- **Impact**: Health monitoring now includes MDDB services
- **Rollback**: Remove mddb-api and mddb-panel health check entries

## Change Categories

### Major Changes
- New SSOT files created
- Significant structural changes to existing files
- New maintenance frameworks or processes
- Major configuration changes affecting multiple systems

### Minor Changes
- New sections or fields added to existing files
- Updated documentation or descriptions
- Process improvements or tool additions

### Patch Changes
- Bug fixes and corrections
- Syntax fixes (YAML, formatting)
- Index updates and consistency fixes
- Minor documentation updates

## Rollback Guidelines

1. **Identify the change** in this changelog
2. **Check the rollback commit** if provided
3. **Assess impact** on dependent files and systems
4. **Execute rollback** using git revert or manual changes
5. **Validate** the rollback with SSOT validation tools
6. **Document** the rollback in this changelog

## Maintenance Notes

- This changelog should be updated for all major and minor SSOT changes
- Patch changes can be grouped and updated weekly
- Include git commit hashes for easy rollback reference
- Document dependencies between SSOT file changes
- Review and archive old entries quarterly
