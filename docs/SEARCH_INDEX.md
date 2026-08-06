---
title: Documentation Search Index
description: Comprehensive index of all Chaba documentation with search keywords, relationships, and common search patterns for efficient information retrieval
tags: [index, search, documentation, cross-reference]
created: 2026-08-06
updated: 2026-08-06
category: operations
related: [ssot.index.yml, documentation-search.md, ssot-search skill]
search_keywords: [documentation index, search patterns, cross-reference, quick reference]
---

# Documentation Search Index

**Abstract**: Comprehensive search index for all Chaba documentation providing quick reference by category, common search patterns, cross-reference mapping, and efficient information retrieval strategies using both ssot-search and MCP docs server methods.

## Quick Reference by Category

### Operations & Monitoring
- **Health Check Dashboard** - Real-time system monitoring with GPU, Yomi, and service status
  - Keywords: health monitoring, GPU status, service health, dashboard, auto-refresh
  - File: `kb/health-check.md`
  - SSOT: `ssot.health.yml`, `ssot.health.home.yml`
  - Search: "health check", "GPU monitoring", "service status"

- **GPU Embedding Service** - GPU-accelerated text embeddings with 34x performance improvement
  - Keywords: GPU, embeddings, vector generation, sentence-transformers, CUDA
  - File: `kb/gpu-embedding-service.md`
  - SSOT: `ssot.gpu.yml`
  - Search: "GPU embeddings", "vector generation", "sentence-transformers"

- **System Automation** - Automated monitoring and maintenance scripts
  - Keywords: automation, monitoring, maintenance, cron jobs, GPU monitoring
  - File: `kb/system-automation.md`
  - SSOT: `ssot.automation.yml`
  - Search: "system automation", "GPU monitoring", "maintenance scripts"

- **Overnight Assessment** - Automated comprehensive system assessment
  - Keywords: overnight assessment, health checks, security scanning, disk usage
  - File: `kb/overnight-assessment.md`
  - SSOT: `ssot.automation.yml`
  - Search: "overnight assessment", "security scan", "disk usage"

### Architecture & Design
- **Yomi Architecture** - LINE web app two-stage pipeline architecture
  - Keywords: Yomi, LINE, architecture, pipeline, two-stage
  - File: `architecture/yomi-architecture-separation.md`
  - SSOT: `ssot.docs.yml`
  - Search: "Yomi architecture", "LINE pipeline", "two-stage"

- **Yomi Summarization Improvements** - Yomi summarization service enhancements
  - Keywords: Yomi, summarization, improvements, quality, Gemini
  - File: `architecture/yomi-summarization-improvements.md`
  - SSOT: `ssot.docs.yml`
  - Search: "Yomi summarization", "Gemini integration", "summary quality"

- **Wireguard Architecture** - VPN architecture and configuration
  - Keywords: Wireguard, VPN, architecture, networking, security
  - File: `architecture/wireguard-architecture.md`
  - SSOT: `ssot.mysystem.home.yml`
  - Search: "Wireguard", "VPN architecture", "networking"

### Implementation & Integration
- **MCP Config Sync** - MCP configuration synchronization implementation
  - Keywords: MCP, configuration, synchronization, implementation
  - File: `implementation/mcp-config-sync-implementation.md`
  - SSOT: `ssot.devin.tools.yml`
  - Search: "MCP config", "configuration sync", "MCP server"

- **SSOT Config Manager** - SSOT configuration manager implementation
  - Keywords: SSOT, configuration manager, implementation, validation
  - File: `overview/ssot-config-manager-implementation.md`
  - SSOT: `ssot.validation-patterns.yml`
  - Search: "SSOT manager", "configuration validation", "SSOT implementation"

### Documentation & Standards
- **Documentation Search** - Dual search methods guide (ssot-search + MCP docs server)
  - Keywords: documentation search, MCP, ssot-search, Flexsearch, grep
  - File: `kb/documentation-search.md`
  - SSOT: `ssot.index.yml`
  - Search: "documentation search", "MCP docs", "search methods"

- **Documentation Maintenance Standards** - Documentation creation and maintenance guidelines
  - Keywords: documentation standards, maintenance, KB entries, templates
  - File: `kb/documentation-maintenance-standards.md`
  - SSOT: `ssot.index.yml`
  - Search: "documentation standards", "KB maintenance", "templates"

- **SSOT Documentation Standards** - SSOT file structure and validation patterns
  - Keywords: SSOT, documentation standards, validation, structure
  - File: `kb/ssot-documentation-standards.md`
  - SSOT: `ssot.validation-patterns.yml`
  - Search: "SSOT standards", "validation patterns", "SSOT structure"

### GPU & AI Services
- **GPU Queue Monitoring** - GPU queue job monitoring and backpressure system
  - Keywords: GPU queue, monitoring, backpressure, job types, priorities
  - File: `kb/gpu-embedding-service.md` (GPU Queue section)
  - SSOT: `ssot.gpu.yml`
  - Search: "GPU queue", "backpressure", "job monitoring"

- **Thai Legal Model** - Thai legal document processing with GPU acceleration
  - Keywords: Thai legal, GPU, LLM, document processing, Gemma
  - File: `kb/gpu-embedding-service.md` (references)
  - SSOT: `ssot.gpu.yml`
  - Search: "Thai legal", "Gemma model", "document processing"

### Yomi System
- **Yomi LINE Web App** - Comprehensive Yomi system documentation
  - Keywords: Yomi, LINE, web app, conversations, summarization
  - File: `kb/yomi.md`
  - SSOT: `ssot.docs.yml`
  - Search: "Yomi", "LINE web app", "conversations"

- **Yomi Daily Calendar** - Yomi daily summary calendar integration
  - Keywords: Yomi, daily calendar, summarization, Thailand timezone
  - File: `kb/yomi-daily2-calendar.md`
  - SSOT: `ssot.docs.yml`
  - Search: "Yomi daily", "calendar integration", "Thailand timezone"

- **Yomi Commercial Filtering** - Commercial message filtering for Yomi
  - Keywords: Yomi, commercial filtering, pattern-based, summarization
  - File: `kb/yomi-commercial-filtering.md`
  - SSOT: `ssot.docs.yml`
  - Search: "commercial filtering", "Yomi patterns", "message filtering"

### Infrastructure & Services
- **Weaviate Vector Database** - Weaviate setup and Chonkie chunking
  - Keywords: Weaviate, vector database, embeddings, Chonkie, chunking
  - File: `kb/weaviate.md`
  - SSOT: `ssot.test.weaviate.yml`
  - Search: "Weaviate", "vector database", "Chonkie chunking"

- **Trade API Integration** - Trading API integration details
  - Keywords: trade API, integration, trading, endpoints
  - File: `kb/trade-api-integration.md`
  - SSOT: `ssot.apps.trade-api.yml`
  - Search: "trade API", "trading integration", "API endpoints"

- **Disk Space Management** - Disk usage monitoring and cleanup procedures
  - Keywords: disk space, management, cleanup, monitoring, Docker
  - File: `kb/disk-space-management.md`
  - SSOT: `ssot.mysystem.home.yml`
  - Search: "disk space", "cleanup", "Docker cleanup"

### Troubleshooting & Issues
- **Caddyfile Syntax Errors** - Caddyfile syntax error patterns and fixes
  - Keywords: Caddyfile, syntax errors, troubleshooting, reverse proxy
  - File: `kb/caddyfile-syntax-errors.md`
  - SSOT: `ssot.services.yml`
  - Search: "Caddyfile", "syntax errors", "reverse proxy"

- **YAML Syntax Error Patterns** - Common YAML syntax errors and prevention
  - Keywords: YAML, syntax errors, patterns, validation, troubleshooting
  - File: `kb/yaml-syntax-error-patterns.md`
  - SSOT: `ssot.validation-patterns.yml`
  - Search: "YAML errors", "syntax patterns", "validation"

- **DNS Resolution Issues** - DNS resolution fix for libvirt dnsmasq
  - Keywords: DNS, resolution, libvirt, dnsmasq, Avahi
  - File: `kb/dns-resolution-libvirt-dnsmasq.md`
  - SSOT: `ssot.mysystem.home.yml`
  - Search: "DNS resolution", "libvirt", "dnsmasq"

## Common Search Patterns

### GPU-Related Searches
- **"GPU memory"** → `gpu-embedding-service.md`, `health-check.md`, `ssot.gpu.yml`
- **"GPU monitoring"** → `health-check.md`, `system-automation.md`, `ssot.gpu.yml`
- **"GPU queue"** → `gpu-embedding-service.md`, `ssot.gpu.yml`, `health-check.md`
- **"GPU backpressure"** → `gpu-embedding-service.md`, `ssot.gpu.yml`
- **"GPU VRAM"** → `gpu-embedding-service.md`, `ssot.gpu.yml`, `health-check.md`

### Yomi-Related Searches
- **"Yomi summarization"** → `yomi-architecture-separation.md`, `yomi-summarization-improvements.md`, `yomi.md`
- **"Yomi API"** → `health-check.md`, `yomi.md`, `ssot.docs.yml`
- **"Daily summaries"** → `yomi-daily2-calendar.md`, `yomi.md`, `yomi-summarization-improvements.md`
- **"Yomi Gemini"** → `yomi-summarization-improvements.md`, `architecture/yomi-summarization-improvements.md`

### Health & Monitoring Searches
- **"Health check"** → `health-check.md`, `ssot.health.yml`, `ssot.health.home.yml`
- **"Service status"** → `health-check.md`, `ssot.health.yml`, `overnight-assessment.md`
- **"System monitoring"** → `system-automation.md`, `health-check.md`, `overnight-assessment.md`
- **"Auto-refresh"** → `health-check.md`, `system-automation.md`

### Configuration & SSOT Searches
- **"SSOT configuration"** → `ssot.index.yml`, `ssot-validation-patterns.yml`, `ssot-documentation-standards.md`
- **"Service configuration"** → `ssot.health.yml`, `ssot.services.yml`, `ssot.apps.yml`
- **"GPU configuration"** → `ssot.gpu.yml`, `gpu-embedding-service.md`, `ssot-summaries/ssot.gpu-summary.md`
- **"Health configuration"** → `ssot.health.yml`, `health-check.md`, `ssot-summaries/ssot.health-summary.md`

### Documentation Searches
- **"Documentation search"** → `documentation-search.md`, `ssot.index.yml`
- **"KB entry"** → `documentation-maintenance-standards.md`, `kb/.template.md`
- **"SSOT search"** → `documentation-search.md`, `ssot.index.yml`
- **"MCP docs"** → `documentation-search.md`, `mcp-tools.md`, `mcp-server-audit.md`

## Cross-Reference Map

### SSOT to Documentation Mapping
- `ssot.health.yml` → `health-check.md`, `ssot-summaries/ssot.health-summary.md`
- `ssot.gpu.yml` → `gpu-embedding-service.md`, `ssot-summaries/ssot.gpu-summary.md`
- `ssot.apps.yml` → `ssot-summaries/ssot.apps-summary.md`, per-app KB entries
- `ssot.docs.yml` → `documentation-search.md`, `ssot-documentation-standards.md`
- `ssot.automation.yml` → `system-automation.md`, `overnight-assessment.md`

### Documentation to SSOT Mapping
- `health-check.md` → `ssot.health.yml`, `ssot.health.home.yml`, `ssot.health.mobile.yml`
- `gpu-embedding-service.md` → `ssot.gpu.yml`, `ssot.test.weaviate.yml`
- `system-automation.md` → `ssot.automation.yml`, `ssot.health.yml`
- `documentation-search.md` → `ssot.index.yml`, `ssot.devin.tools.yml`

### Service Integration Mapping
- **Yomi System** → `yomi.md`, `yomi-architecture-separation.md`, `yomi-daily2-calendar.md`, `ssot.docs.yml`
- **GPU Services** → `gpu-embedding-service.md`, `ssot.gpu.yml`, `health-check.md`
- **Health Monitoring** → `health-check.md`, `ssot.health.yml`, `system-automation.md`
- **Documentation** → `documentation-search.md`, `documentation-maintenance-standards.md`, `ssot.index.yml`

## Search Method Selection Guide

### Use ssot-search (SSOT YAML Only) When:
- Searching for specific SSOT configuration values
- Looking for exact YAML structure or patterns
- Quick SSOT-specific lookups
- Validating SSOT structure
- Pattern matching across SSOT files

**Examples:**
- "GPU memory" in SSOT files
- "health check" endpoint definitions
- "postgres" configuration values
- "service" timeout values

### Use MCP Docs Server (All Documentation) When:
- Broad documentation search without knowing exact location
- Finding relevant content across KB, architecture, assessments
- AI assistant queries (MCP-native)
- Browsing documentation structure
- Want ranked results with excerpts

**Examples:**
- "GPU memory" across all documentation
- "Yomi summarization" improvements
- "health check" troubleshooting
- "documentation search" methods

## SSOT Summary Files

SSOT YAML files are now accompanied by Markdown summaries for MCP searchability:

- **SSOT Health Summary**: `docs/ssot-summaries/ssot.health-summary.md`
  - Source: `docs/ssot/infrastructure/ssot.health.yml`
  - Covers: Service definitions, recovery actions, location-specific config

- **SSOT GPU Summary**: `docs/ssot-summaries/ssot.gpu-summary.md`
  - Source: `docs/ssot/infrastructure/ssot.gpu.yml`
  - Covers: GPU policy, VRAM budget, queue implementation, MCP tools

- **SSOT Apps Summary**: `docs/ssot-summaries/ssot.apps-summary.md`
  - Source: `docs/ssot/apps/ssot.apps.yml`
  - Covers: Application registry, deployment mappings, service integration

## Search Performance Tips

### Fast Exact Searches
- Use ssot-search for SSOT YAML pattern matching (0.006s typical)
- Best for known configuration values and exact terms
- Direct file path access

### Broad Discovery Searches
- Use MCP docs server for full-text search with relevance ranking
- Best for discovering related content across documentation types
- Ranked results with excerpts for context

### Hybrid Approach
1. Start with MCP docs server for broad search
2. Use ssot-search for exact SSOT pattern matching
3. Use get_page to retrieve full content from MCP results
4. Cross-reference between KB entries and SSOT configurations

## Index Maintenance

### Update Triggers
- New KB entries created
- SSOT configuration changes
- New documentation added
- Search patterns identified from usage

### Update Process
1. Add new entries to appropriate category sections
2. Update search keywords and cross-references
3. Add new common search patterns
4. Update SSOT summary references
5. Validate cross-reference mappings

### Quality Checks
- Verify all file paths are correct
- Ensure search keywords are effective
- Test common search patterns
- Validate cross-reference mappings
- Check SSOT summary alignment

## Related Documentation

- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master SSOT file index
- **Documentation Search**: `docs/kb/documentation-search.md` - Dual search methods guide
- **KB Template**: `docs/kb/.template.md` - Standardized KB entry template
- **SSOT Summaries**: `docs/ssot-summaries/` - SSOT Markdown summaries for MCP search

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Created comprehensive documentation search index | devin |
