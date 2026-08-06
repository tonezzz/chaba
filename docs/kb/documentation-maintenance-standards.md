# Documentation Maintenance Standards

## What it is

Systematic approach to documentation maintenance that prevents bloat, reduces redundancy, and ensures long-term maintainability while preserving essential operational information and historical context.

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

## Implementation

### Documentation Audit Process

1. **Identify Bloat**:
   - Files with excessive detail (>300 lines for operational guides)
   - Multiple files covering the same topic
   - Completed implementation plans still in active docs
   - Assessment documents for finished work

2. **Identify Redundancy**:
   - Duplicate content across multiple files
   - Same information in different locations
   - SKILL.md files duplicating KB entries
   - Cross-references that create content overlap

3. **Identify Obsolete Content**:
   - Temporary workarounds that have been resolved
   - Outdated procedures replaced by new approaches
   - Historical audits without status updates
   - Planning documents with stale references

### Consolidation Process

1. **Create Consolidated File**:
   - Merge essential information from multiple files
   - Structure as operational guide (current status, procedures, troubleshooting)
   - Keep length to 150-300 lines for maintainability
   - Include links to archived detailed documents

2. **Archive Original Files**:
   - Add historical notes with dates
   - Fix compliance issues (hostnames, standards)
   - Move to appropriate archived/ directory
   - Update cross-references

3. **Update Cross-References**:
   - Update links in other documentation
   - Update SSOT files if they reference moved documents
   - Verify no broken references remain

### Quality Criteria

**Operational Guides Should**:
- Focus on current status and procedures
- Include essential monitoring and troubleshooting
- Be 150-300 lines for maintainability
- Link to archived detailed documents when needed
- Follow standard KB entry template

**Archived Documents Should**:
- Have prominent historical notes
- Be fixed for current standards compliance
- Preserve decision history and context
- Be properly categorized in archived/ directories

## Configuration

### Archive Directory Structure
```bash
docs/kb/archived/                    # Archived KB entries
docs/assessments/gpu-embedding/archived/  # Archived GPU assessments
docs/archive/                        # Historical planning documents
```

### Standard Historical Note Template
```markdown
> **Historical Document**: This document was created on [DATE] 
> and reflects the state of the project at that time. Some 
> information may be outdated. Current status should be verified 
> in [CURRENT_DOCUMENTATION].
```

## Technical Details

### Documentation Reduction Metrics

**Session Results (2026-08-06)**:
- **Files Archived**: 10 files
- **Files Removed**: 4 files
- **Files Consolidated**: 8 files → 3 files
- **Lines Reduced**: ~2,400+ lines of excessive detail
- **Overall Reduction**: 40-50% while maintaining essential information

### Consolidation Impact Examples

**Token Optimization**:
- Before: 4 files (1,022 lines)
- After: 1 operational guide (187 lines) + 3 archived files
- Reduction: 82% in active documentation

**GPU Embedding**:
- Before: 6 files (1,300+ lines)
- After: 1 service doc (155 lines) + 5 archived files
- Reduction: 88% in active documentation

**SSOT Standards**:
- Before: 3 files (657 lines)
- After: 1 operational guide (228 lines)
- Reduction: 65% in active documentation

## Verification

### Documentation Quality Checklist
- [ ] No duplicate content across active files
- [ ] Operational guides are 150-300 lines
- [ ] SKILL.md files are concise (20-80 lines)
- [ ] Historical documents have prominent notes
- [ ] Archived files are in proper directories
- [ ] Cross-references are updated
- [ ] No broken links to moved files
- [ ] Hostname compliance (.local not IPs)

### Bloat Detection Indicators
- Files >300 lines for operational guides
- Multiple files covering identical topics
- Implementation plans for completed work
- Assessment documents without archival
- Detailed procedures in SKILL.md files

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

- `docs/kb/ssot-documentation-standards.md` - SSOT file standards
- `docs/kb/token-optimization.md` - Consolidated operational guide example
- `docs/kb/gpu-embedding-service.md` - Consolidated service documentation example
- `.windsurf/workflows/auto-kb-creation.md` - KB entry creation workflow

## Tags

documentation, maintenance, consolidation, archive, standards, bloat-reduction, redundancy, operational-excellence, knowledge-management