# Documentation Index

This index provides an overview of the documentation structure and quick access to all major sections.

## Documentation Structure

```
docs/
├── architecture/          # System architecture documentation
├── archive/               # Archived historical documents
├── assessments/           # Technology assessments and planning
├── implementation/        # Implementation guides and reports
├── kb/                    # Knowledge Base (how-to guides)
├── overview/              # Project-specific configurations
├── reports/               # System assessment and status reports
├── sessions/              # Development session archives
└── ssot/                  # Single Source of Truth configurations
```

## Quick Navigation

### Knowledge Base (`docs/kb/`)
Comprehensive guides for systems and workflows:

- **[caddyfile-syntax-errors.md](kb/caddyfile-syntax-errors.md)** - Caddyfile syntax error patterns and fixes
- **[dependency-management.md](kb/dependency-management.md)** - Dependency management system for improvements
- **[dns-resolution-libvirt-dnsmasq.md](kb/dns-resolution-libvirt-dnsmasq.md)** - DNS resolution fix: Avahi restricted to wlo1, tony-omen.local → 192.168.1.48 (resolved 2026-08-05)
- **[e2e-test-automation-patterns.md](kb/e2e-test-automation-patterns.md)** - E2E testing patterns using Playwright
- **[h3-pages.md](kb/h3-pages.md)** - chaba.h3 static pages deployment patterns
- **[gpu-embedding-service.md](kb/gpu-embedding-service.md)** - GPU embedding service architecture and implementation
- **[health-check.md](kb/health-check.md)** - Health check dashboard documentation
- **[impact-scoring-system.md](kb/impact-scoring-system.md)** - Impact scoring system for improvements
- **[mcp-server-audit.md](kb/mcp-server-audit.md)** - MCP server audit and optimization
- **[mcp-tools.md](kb/mcp-tools.md)** - MCP server inventory and maintenance
- **[overnight-assessment.md](kb/overnight-assessment.md)** - Automated overnight system assessment
- **[playlive-authentication.md](kb/playlive-authentication.md)** - PlayLive authentication troubleshooting
- **[playwright-vs-playlive.md](kb/playwright-vs-playlive.md)** - Playwright vs PlayLive comparison
- **[raceman-worktree-scope.md](kb/raceman-worktree-scope.md)** - Raceman worktree scope and refactoring
- **[subagent-implementation-strategy.md](kb/subagent-implementation-strategy.md)** - Subagent creation and management patterns
- **[token-optimization-summary.md](kb/token-optimization-summary.md)** - Token optimization implementation overview
- **[token-optimization-monitoring-guide.md](kb/token-optimization-monitoring-guide.md)** - Token optimization monitoring procedures
- **[token-optimization-runbook.md](kb/token-optimization-runbook.md)** - Token optimization operational procedures
- **[token-optimization-testing.md](kb/token-optimization-testing.md)** - Token optimization testing procedures
- **[headroom-integration-monitoring-summary.md](kb/headroom-integration-monitoring-summary.md)** - Headroom proxy integration monitoring
- **[headroom-test-results.md](kb/headroom-test-results.md)** - Headroom proxy test results
- **[weaviate.md](kb/weaviate.md)** - Weaviate vector database and Chonkie chunking
- **[weaviate-rest-api-fix.md](kb/weaviate-rest-api-fix.md)** - Weaviate REST API implementation details
- **[yaml-syntax-error-patterns.md](kb/yaml-syntax-error-patterns.md)** - Common YAML syntax errors and prevention
- **[yomi-daily2-calendar.md](kb/yomi-daily2-calendar.md)** - Yomi daily calendar integration
- **[yomi-summary-corruption.md](kb/yomi-summary-corruption.md)** - Yomi summary corruption prevention and detection
- **[yomi.md](kb/yomi.md)** - Yomi LINE web app comprehensive documentation

### Architecture (`docs/architecture/`)
System architecture and design documentation:

- **[wireguard-architecture.md](architecture/wireguard-architecture.md)** - VPN architecture
- **[yomi-architecture-separation.md](architecture/yomi-architecture-separation.md)** - Yomi two-stage pipeline architecture
- **[yomi-summarization-improvements.md](architecture/yomi-summarization-improvements.md)** - Yomi summarization enhancements

### Assessments (`docs/assessments/`)
Technology evaluations and planning documents:

- **[weaviate-assessment.md](assessments/weaviate-assessment.md)** - Weaviate vector database evaluation
- **[mdns-assessment.md](assessments/mdns-assessment.md)** - mDNS evaluation
- **[github-mcp-model-assessment.md](assessments/github-mcp-model-assessment.md)** - GitHub MCP evaluation
- **[hostname-enforcement-strategy.md](assessments/hostname-enforcement-strategy.md)** - Hostname usage standards
- **[gpu-embedding/](assessments/gpu-embedding/)** - GPU embedding planning documents
  - gpu-embedding-action-plan.md
  - gpu-embedding-feasibility-assessment.md
  - gpu-embedding-gap-analysis.md
  - gpu-embedding-revised-plan.md
  - gpu-sharing-data-collection.md

### Implementation (`docs/implementation/`)
Implementation guides and technical documentation:

- **[mcp-config-sync-implementation.md](implementation/mcp-config-sync-implementation.md)** - MCP configuration synchronization implementation guide
- **[ssot-config-manager-implementation.md](implementation/ssot-config-manager-implementation.md)** - SSOT configuration manager implementation report

### Reports (`docs/reports/`)
System assessment and status reports:

- **[mcp-config-status-report.md](reports/mcp-config-status-report.md)** - MCP configuration status report
- **[overnight-assessment-2026-08-04.md](reports/overnight-assessment-2026-08-04.md)** - Comprehensive overnight system assessment

### SSOT (`docs/ssot/`)
Single Source of Truth configurations — see **[ssot.index.yml](ssot/ssot.index.yml)** for the master index:

- **[ssot.index.yml](ssot/ssot.index.yml)** - **Master index** of all 30 SSOT files with descriptions
- **[template.yml](ssot/template.yml)** - Template for new SSOT files
- **[ssot.improvements.yml](ssot/ssot.improvements.yml)** - Active system improvements tracking (pending/in-progress only)
- **[ssot.improvements.archive.yml](ssot/ssot.improvements.archive.yml)** - Completed improvements archive
- **[ssot.focus.yml](ssot/ssot.focus.yml)** - Strategic focus areas and history
- **[ssot.token-optimization.yml](ssot/ssot.token-optimization.yml)** - Token optimization strategy and implementation
- **[apps/](ssot/apps/)** - Application-specific SSOT files (ssot.apps.yml + per-app files)
- **[infrastructure/](ssot/infrastructure/)** - Infrastructure configurations
  - ssot.health.yml, ssot.health.home.yml, ssot.health.mobile.yml
  - ssot.gpu.yml, ssot.services.yml
- **Domain-specific SSOT files**
  - ssot.devin.tools.yml, ssot.diagrams.yml, ssot.docs.yml
  - ssot.libs.yml, ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
  - ssot.test.weaviate.yml, ssot.ui.yml, ssot.validation-patterns.yml

### Sessions (`docs/sessions/`)
Development session archives (timestamped YAML files):

- Session summaries with key decisions and discoveries
- Work completed and next steps
- Chronological organization by timestamp

### Archive (`docs/archive/`)
Historical and superseded documents:

- **[plan-brief.md](archive/plan-brief.md)** - Historical project planning brief

### Overview (`docs/overview/`)
Project-specific configurations (not moved during restructuring):

- apps.yomi.yml - Yomi-specific app configuration
- audit.ssot.yml - SSOT audit documentation
- hosts.*.yml - Host configuration files
- lab.plan-brief.yml - Lab planning brief
- sso.apps.dev.yml - SSO configuration
- ssot.token-optimization.yml - Token optimization strategy (served copy)

## Key Documentation Patterns

### KB Entry Structure
- Overview section explaining the system
- Key files table with file purposes
- Architecture and implementation details
- Troubleshooting section with common issues
- Cross-references to related SSOT files
- Tags and metadata for categorization

### SSOT File Structure
- Title, subtitle, and icon fields
- Ideas section for notes and context
- Sections with title, icon, layout, and items
- Consistent YAML formatting
- Template-driven approach

### Session Archive Format
- ISO timestamp naming (YYYY-MM-DDTHH-MM-SS.yml)
- Title, date, summary, project fields
- Sections for work completed and next steps
- Links to project roots and types

## Documentation Workflows

### Adding New KB Entries
1. Create file in `docs/kb/` with descriptive name
2. Follow existing KB structure (overview, key files, troubleshooting)
3. Add cross-references to related SSOT files
4. Update this INDEX.md with new entry

### Adding New SSOT Files
1. Copy `docs/ssot/template.yml` as starting point
2. Place in appropriate subdirectory (apps/, infrastructure/, or root)
3. Follow SSOT structure conventions
4. Validate with ssot-validate skill

### Archiving Sessions
1. Create session file in `docs/sessions/` with timestamp
2. Include key decisions, discoveries, and next steps
3. Link to relevant project and files
4. Update session index if needed

## Related Resources

### Skills
- **ssot-search** - Search across SSOT files
- **ssot-validate** - Validate SSOT file syntax and structure
- **health-check** - Check health of services defined in SSOT

### Scripts
- **scripts/overnight-assessment.mjs** - Automated system assessment
- **scripts/dependency-graph.mjs** - Generate dependency graphs
- **scripts/dependency-resolver.mjs** - Analyze dependencies
- **scripts/generate-mcp-configs.py** - MCP configuration synchronization
- **scripts/validate-configs.sh** - SSOT configuration validation

### Configuration
- **.windsurfrules** - Project rules and conventions
- **.windsurf/workflows/** - Workflow documentation

## Maintenance

### Regular Updates
- Review and update KB entries as systems evolve
- Archive outdated documents to `docs/archive/`
- Update cross-references when files move
- Keep INDEX.md synchronized with structure changes

### Validation
- Run ssot-validate skill to check SSOT files
- Test documentation links resolve correctly
- Verify scripts use correct file paths
- Check for broken cross-references

## Getting Started

For new contributors:
1. Read relevant KB entries for your area
2. Review SSOT files for system configuration
3. Check recent session archives for context
4. Follow documentation patterns when adding new content
5. Validate changes with available skills

---

Last updated: 2026-08-05
- Added token optimization documentation (6 new KB entries)
- Updated SSOT section with token optimization configuration
- Added new KB entries for GPU embedding, impact scoring, MCP audit
- Updated KB index with recent additions
