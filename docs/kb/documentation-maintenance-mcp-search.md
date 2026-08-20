---
category: operations
---

# Troubleshooting

### Documentation Bloat Recurrence
- Schedule quarterly documentation reviews
- Implement archive policy for completed work
- Consolidate related files during project completion
- Review new documentation against size guidelines

### Cross-Reference Breakage
- Update all references when moving files
- Use search to find all references to moved files
- Test links after consolidation
- Update SSOT files that reference documentation

### Archive Location Confusion
- Use consistent archive directory structure
- Document archive criteria in project standards
- Include dates in historical notes
- Maintain clear separation between active and archived

## Related Documentation

- **Documentation Search**: `docs/kb/documentation-search.md` - Dual search methods guide
- **Search Index**: `docs/SEARCH_INDEX.md` - Comprehensive documentation search index
- **KB Template**: `docs/kb/.template.md` - Standardized KB entry template
- **SSOT Documentation Standards**: `docs/kb/ssot-documentation-standards.md` - SSOT file standards
- **Token Optimization**: `docs/kb/token-optimization.md` - Consolidated operational guide example

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial documentation maintenance standards | devin |
| 2026-08-06 | Added MCP search optimization and template requirements | devin | example
- `docs/kb/gpu-embedding-service.md` - Consolidated service documentation example
- `.windsurf/workflows/auto-kb-creation.md` - KB entry creation workflow

## MCP Search Optimization (2026-08-06)

### Frontmatter Benefits
- **Better search relevance**: Tags and keywords improve ranking
- **Filterable metadata**: Category, date, related files for filtering
- **Consistent structure**: Standardized format for AI processing
- **Cross-reference mapping**: Related files field for context

### Search Keywords Strategy
- **Primary terms**: Main domain terms and concepts
- **Secondary terms**: Related concepts and synonyms
- **Use cases**: Common search scenarios
- **Related concepts**: Broader domain connections

### Section Standardization
- **Abstract**: 2-3 sentence summary for search excerpts
- **Overview**: What it is (2-3 sentences)
- **Purpose**: What it accomplishes
- **Consistent headings**: Standard section names across all docs

### SSOT Searchability
- **Markdown summaries**: SSOT YAML files accompanied by Markdown summaries
- **Authoritative sources**: Summaries link to YAML source files
- **Search coverage**: Makes SSOT content searchable via MCP docs server
- **Single source of truth**: YAML remains authoritative, summaries for search

## Context/Background

Implemented on 2026-08-06 during comprehensive documentation cleanup that addressed significant bloat across ~60 markdown files. The cleanup achieved 40-50% documentation reduction while maintaining all essential operational information through consolidation, archiving, and strategic removal of duplicate/obsolete content.

## Key Details

### Documentation Consolidation Strategy

**Core Principles**:
- Consolidate multiple related files into single operational guides
- Archive completed implementation plans and assessment documents
- Remove duplicate content across files
- Preserve historical context with proper marking
- Maintain separation between skill definitions and system documentation

**Consolidation Patterns**:
- **Token Optimization**: 3 files (1,022 lines) → 1 operational guide (187 lines)
  - Archived: summary, monitoring guide, runbook
  - Created: token-optimization.md (current status, procedures, troubleshooting)
- **GPU Embedding**: 5 assessment documents (1,300+ lines) → archived/
  - Consolidated service documentation (285 lines → 155 lines)
  - Retained success report as historical record
- **SSOT Standards**: 3 files (657 lines) → 1 operational guide (228 lines)
  - Merged best practices, synchronization standards, subagent strategy

### Archive Policy

**Archive Locations**:
- `docs/kb/archived/` - Archived KB entries
- `docs/assessments/*/archived/` - Archived assessment documents
- `docs/archive/` - Historical planning documents

**Archive Criteria**:
- Completed implementation plans
- Assessment documents for finished work
- Outdated planning documents with historical value
- Temporary workarounds that have been resolved
- Historical audits with implementation status updates

**Archive Process**:
1. Add prominent historical note with date and warning about stale content
2. Fix for current standards compliance (e.g., IP addresses → .local hostnames)
3. Add implementation status updates if applicable
4. Move to appropriate archived/ directory
5. Update cross-references in active documentation

### Historical Document Marking

**Standard Historical Note Format**:
```markdown
> **Note**: This is a historical planning document from [DATE]. 
> Some information may be outdated, including TODO items, branch 
> references, and infrastructure details. Current status should be 
> verified in SSOT files and recent documentation.
```

**Compliance Fixes Before Archiving**:
- Replace IP addresses with `.local` hostnames
- Update branch references if known
- Mark completed TODO items
- Add implementation status if work was completed

### Skill vs KB Documentation Separation

**SKILL.md Files** (20-80 lines):
- Focus on skill invocation and parameters
- Describe what the skill does and when to use it
- Reference comprehensive KB entries for details
- Maintain concise, actionable skill definitions

**KB Entries** (150-300 lines):
- Comprehensive system documentation
- Context/background and key details
- Implementation procedures and configuration
- Troubleshooting and related documentation
- Tags for discoverability

**Anti-Pattern to Avoid**:
- Do not duplicate comprehensive documentation in SKILL.md
- SKILL.md should reference KB entries, not repeat them
- KB entries should not contain skill invocation instructions

## Troubleshooting

### Documentation Bloat Recurrence
- Schedule quarterly documentation reviews
- Implement archive policy for completed work
- Consolidate related files during project completion
- Review new documentation against size guidelines

### Cross-Reference Breakage
- Update all references when moving files
- Use search to find all references to moved files
- Test links after consolidation
- Update SSOT files that reference documentation

### Archive Location Confusion
- Use consistent archive directory structure
- Document archive criteria in project standards
- Include dates in historical notes
- Maintain clear separation between active and archived

## Related Documentation

- **Documentation Search**: `docs/kb/documentation-search.md` - Dual search methods guide
- **Search Index**: `docs/SEARCH_INDEX.md` - Comprehensive documentation search index
- **KB Template**: `docs/kb/.template.md` - Standardized KB entry template
- **SSOT Documentation Standards**: `docs/kb/ssot-documentation-standards.md` - SSOT file standards
- **Token Optimization**: `docs/kb/token-optimization.md` - Consolidated operational guide example

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial documentation maintenance standards | devin |
| 2026-08-06 | Added MCP search optimization and template requirements | devin | example
- `docs/kb/gpu-embedding-service.md` - Consolidated service documentation example
- `.windsurf/workflows/auto-kb-creation.md` - KB entry creation workflow

## Tags

- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **automation**: automation
- **mcp**: mcp
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **yaml**: yaml
- **syntax**: syntax
- **2026**: 2026
