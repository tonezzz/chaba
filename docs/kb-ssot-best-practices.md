# SSOT Best Practices and Standards

## Overview
This document outlines the best practices and standards for maintaining Single Source of Truth (SSOT) YAML files across the chaba project ecosystem.

## File Structure and Organization

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

### Configuration-Type Files
Files like `ssot.health.yml`, `ssot.gpu.yml`, `ssot.services.yml` have flexible structures:
```yaml
# Configuration files can have custom structures
# relevant to their specific domain
key: value
nested:
  configuration:
    items: here
```

### Apps Data Files
Files in the `apps/` subdirectory contain simple data structures:
```yaml
app_name:
  url: https://example.com
  description: App description
  status: active
```

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

## Common Patterns

### Dependency Management
```yaml
- label: Dependent Focus
  text: Description of dependent work
  dependencies:
    - Prerequisite Focus
  dependency_reason: Why this dependency exists
```

### Impact Scoring
```yaml
- label: High Impact Improvement
  text: Description of improvement
  business_impact: 8  # 1-10 scale
  technical_impact: 7  # 1-10 scale
  user_experience_impact: 6  # 1-10 scale
  cost_savings_impact: 5  # 1-10 scale
```

### Progress Tracking
```yaml
- label: Ongoing Work
  text: Description of work in progress
  status: active
  current_context: What's currently being done
  estimated_completion: 2026-08-10
```

## Cross-File Consistency

### SSOT to Served Files
- SSOT files in `docs/ssot/` are the source of truth
- Served copies in `stacks/web/public/` should match
- Public copies in `public/docs/overview/` should match
- Run validation to check for differences

### SSOT to Generated Configs
- MCP configs generated from `ssot.devin.tools.yml`
- Run `python3 scripts/generate-mcp-configs.py` to sync
- Validate generated configs before deployment

### SSOT to Documentation
- KB entries should reference relevant SSOT files
- Documentation should reflect current SSOT state
- Update docs when SSOT structure changes

## Tools and Automation

### Validation Scripts
- **SSOT Validation**: `bash scripts/validate-configs.sh`
- **Focus Validation**: `node scripts/validate-focus.mjs`
- **MCP Config Generation**: `python3 scripts/generate-mcp-configs.py`

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

### Cross-Reference Issues
- **Invalid reference**: Check if referenced file/section exists
- **Broken links**: Update references when files move
- **Circular dependencies**: Restructure to remove cycles

### Sync Issues
- **Served copy differs**: Re-copy from SSOT source
- **Generated config outdated**: Re-run generation script
- **Validation fails**: Fix validation errors before syncing

## Documentation Standards

### SSOT File Documentation
- Include clear `title` and `subtitle`
- Use `ideas` section for context and plans
- Add `config` section for metadata
- Document exceptions to standard patterns

### External Documentation
- Reference SSOT files in relevant docs
- Keep documentation aligned with SSOT changes
- Use SSOT as source of truth for system state
- Document SSOT structure and patterns

## Quality Assurance

### Review Checklist
- [ ] Validation passes without errors
- [ ] No hostname violations (except allowed exceptions)
- [ ] Cross-references are valid
- [ ] Structure follows established patterns
- [ ] Content is clear and accurate
- [ ] Related files are updated
- [ ] Documentation is current

### Testing Considerations
- Test generated configs after SSOT changes
- Validate served copies match SSOT source
- Test tools/scripts that depend on SSOT
- Verify cross-file references work correctly

## Evolution and Improvement

### Pattern Evolution
- Review and update validation patterns regularly
- Add new patterns as SSOT structure evolves
- Deprecate outdated patterns gracefully
- Document pattern changes clearly

### Continuous Improvement
- Gather feedback on SSOT usability
- Identify common validation failures
- Automate repetitive validation tasks
- Improve error messages and guidance

## Conclusion

Following these best practices ensures:
- **Consistency**: Uniform structure across all SSOT files
- **Reliability**: Validation catches errors early
- **Maintainability**: Clear patterns make updates easier
- **Collaboration**: Standards help team coordination
- **Automation**: Structured data enables tooling

SSOT files are a critical part of the project infrastructure - treat them with the same care as production code.
