---
category: operations
---

# SSOT File Structure

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

