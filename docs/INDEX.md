# Documentation Index

This index provides an overview of the documentation structure and quick access to all major sections.

## Documentation Structure

```
docs/
├── architecture/          # System architecture documentation
├── archive/               # Archived historical documents
├── assessments/           # Technology assessments and planning
├── kb/                    # Knowledge Base (how-to guides)
├── overview/              # Project-specific configurations
├── sessions/              # Development session archives
└── ssot/                  # Single Source of Truth configurations
```

## Quick Navigation

### Knowledge Base (`docs/kb/`)
Comprehensive guides for systems and workflows:

- **[caddyfile-syntax-errors.md](kb/caddyfile-syntax-errors.md)** - Caddyfile syntax error troubleshooting and fixes
- **[dependency-management.md](kb/dependency-management.md)** - Dependency management system for improvements
- **[gemini-api-limits.md](kb/gemini-api-limits.md)** - Gemini API free tier limits and model specifications
- **[h3-pages.md](kb/h3-pages.md)** - chaba.h3 static pages deployment patterns
- **[health-check.md](kb/health-check.md)** - Health check dashboard documentation
- **[llm-container-configuration.md](kb/llm-container-configuration.md)** - LLM container configuration and deployment
- **[mcp-tools.md](kb/mcp-tools.md)** - MCP server inventory and maintenance
- **[overnight-assessment.md](kb/overnight-assessment.md)** - Automated overnight system assessment
- **[playlive-authentication.md](kb/playlive-authentication.md)** - PlayLive basic authentication implementation
- **[playlive-daily2-testing.md](kb/playlive-daily2-testing.md)** - PlayLive browser automation testing for daily2 interface
- **[weaviate.md](kb/weaviate.md)** - Weaviate vector database and Chonkie chunking
- **[weaviate-rest-api-fix.md](kb/weaviate-rest-api-fix.md)** - Weaviate REST API implementation details
- **[yomi-daily-calendar-timezone.md](kb/yomi-daily-calendar-timezone.md)** - Thailand timezone handling in Yomi daily calendar
- **[yomi-media-analysis-http500.md](kb/yomi-media-analysis-http500.md)** - Fixing HTTP 500 errors in daily2 media analysis (missing GEMINI_API_KEY)
- **[yomi-summary-corruption.md](kb/yomi-summary-corruption.md)** - Yomi summary corruption prevention and detection
- **[yomi-thai-language-default.md](kb/yomi-thai-language-default.md)** - Defaulting Yomi language detection to Thai instead of English
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

### SSOT (`docs/ssot/`)
Single Source of Truth configurations:

- **[template.yml](ssot/template.yml)** - Template for new SSOT files
- **[ssot.improvements.yml](ssot/ssot.improvements.yml)** - System improvements tracking
- **[apps/](ssot/apps/)** - Application-specific SSOT files
  - ssot.apps.yml (central app registry)
  - ssot.apps.aihub.yml, ssot.apps.cams.yml, ssot.apps.chaba.yml, etc.
- **[infrastructure/](ssot/infrastructure/)** - Infrastructure configurations
  - ssot.health.yml, ssot.health.home.yml, ssot.health.mobile.yml
  - ssot.gpu.yml, ssot.services.yml
- **Domain-specific SSOT files**
  - ssot.devin.tools.yml, ssot.diagrams.yml, ssot.docs.yml
  - ssot.libs.yml, ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
  - ssot.test.weaviate.yml, ssot.ui.yml

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

## Key Documentation Patterns

### KB Entry Structure
- Overview section explaining the system
- Key files table with file purposes
- Architecture and implementation details
- Troubleshooting section with common issues
- Cross-references to related SSOT files

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

Last updated: 2026-08-08
Documentation restructuring completed
