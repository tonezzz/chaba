---
title: Application SSOT Standards
description: Standardized structure and conventions for application SSOT files to ensure consistency across the chaba project ecosystem.
tags: [ssot, documentation, standards, applications, consistency]
created: 2026-08-06
updated: 2026-08-06
category: operations
related: [ssot.validation-patterns.yml, ssot-documentation-standards.md, template.app.yml]
search_keywords: [app-ssot, ssot-template, app-documentation, standardization, consistency]
---

# Application SSOT Standards
## What it is

title: Application SSOT Standards


**Abstract**: Standardized structure and conventions for application SSOT (Single Source of Truth) files to ensure consistency across the chaba project ecosystem, making documentation easier to create, maintain, and search.
## Context/Background

Created 2026-08-06 as part of Chaba infrastructure documentation.


## Overview

Application SSOT files provide comprehensive documentation for individual applications in the chaba ecosystem. This standard defines the structure, sections, and conventions to ensure consistency across all app SSOT files, making them easier to create, maintain, and search.

## Purpose

- **Consistency**: Uniform structure across all application SSOT files
- **Discoverability**: Standardized sections make information easy to find
- **Maintainability**: Clear structure reduces documentation debt
- **Searchability**: Consistent terminology improves search results
- **Onboarding**: New contributors can quickly understand app documentation patterns

## Standard Structure

All application SSOT files should follow this structure:

### Required Sections

1. **Core Features** (✅ icon)
   - Main functionality and user-facing features
   - Key capabilities and value propositions

2. **Technical Architecture** (⚙️ icon)
   - Technical components and their relationships
   - Architecture patterns and design decisions

3. **Files & Modules** (📁 icon)
   - Key files and their purposes
   - Module organization and responsibilities

4. **Deployment** (🚀 icon)
   - File locations and deployment targets
   - URLs, registry entries, and branch information

### Optional Sections (include as needed)

5. **Testing** (🧪 icon)
   - Testing approaches and coverage
   - Test suites and validation methods

6. **Integration** (🔗 icon)
   - Integration points with other systems
   - APIs, data flows, and dependencies

7. **Known Issues** (⚠️ icon)
   - Current limitations and known problems
   - Workarounds and future improvements

## File Template

Use `docs/ssot/apps/template.app.yml` as the starting point for new app SSOT files:

```yaml
title: [App Name]
subtitle: [1-2 sentence description]
icon: [emoji]
sections:
  - title: Core Features
    icon: ✅
    layout: list
    items:
      - label: [Feature name]
        text: '[Detailed description]'
  # ... other sections
config:
  version: 1
  created: YYYY-MM-DD
  maintainer: [name]
  status: [active|deprecated|experimental]
  deployment: [target(s)]
```

## Naming Conventions

### File Naming
- Pattern: `ssot.apps.[app-name].yml`
- Use lowercase, hyphen-separated app names
- Examples: `ssot.apps.track4.yml`, `ssot.apps.wind.yml`, `ssot.apps.test-pwa.yml`

### Section Icons
Use consistent emoji icons for sections:
- ✅ Core Features
- ⚙️ Technical Architecture  
- 📁 Files & Modules
- 🚀 Deployment
- 🧪 Testing
- 🔗 Integration
- ⚠️ Known Issues

### App Icons
Use descriptive emoji for app identification:
- 🏁 Race management apps
- 💨 Weather/environmental apps
- 🗺️ Mapping/visualization apps
- 📱 Mobile/PWA apps
- 🎨 Creative/design apps
- 🔧 Utility/tool apps

## Content Guidelines

### Descriptions
- **Subtitle**: 1-2 sentences maximum, focus on main purpose
- **Item text**: Be specific but concise, include technical details
- **Focus**: What it does, how it works, why it matters

### Technical Details
- Include file paths relative to repository root
- Specify deployment URLs and access methods
- Note branch names and worktree locations
- Mention integration points and dependencies

### Status Classification
- **active**: Currently maintained and deployed
- **deprecated**: Still exists but superseded by newer solutions
- **experimental**: Early stage, may change significantly

## Integration with SSOT Index

All app SSOT files must be registered in `docs/ssot/ssot.index.yml`:

```yaml
- title: Applications
  icon: 📱
  layout: list
  items:
    - label: apps/ssot.apps.[app-name].yml
      text: [Brief description]
      path: docs/ssot/apps/ssot.apps.[app-name].yml
```

## Examples

### Well-Structured App SSOT
- `ssot.apps.track4.yml` - Comprehensive modularization documentation
- `ssot.apps.wind.yml` - Minimal but complete feature documentation
- `ssot.apps.test-pwa.yml` - Full deployment and testing procedures

### Common Patterns
- **Race apps**: Include simulation, physics, and course editor sections
- **Visualization apps**: Include rendering, data sources, and performance sections
- **Utility apps**: Include deployment, configuration, and integration sections

## Maintenance

### When to Update
- New features added to the application
- Architecture changes or refactoring
- Deployment locations or methods change
- New integrations or dependencies added
- Known issues resolved or discovered

### Review Process
- Quarterly review of all app SSOT files
- Check for consistency with template
- Update status classifications as needed
- Remove deprecated apps or move to archive

## Validation

Use the ssot-validate skill to check app SSOT files:

```bash
# Validate specific app SSOT
ssot-validate docs/ssot/apps/ssot.apps.[app-name].yml

# Validate all app SSOT files
ssot-validate docs/ssot/apps/
```

## Related Documentation

- **SSOT Validation Patterns**: `docs/ssot/ssot.validation-patterns.yml` - General SSOT standards
- **Documentation Standards**: `docs/kb/documentation-maintenance-standards.md` - KB entry guidelines
- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master index of all SSOT files
- **App Template**: `docs/ssot/apps/template.app.yml` - Canonical app SSOT template

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial creation with template and standards | tony |

## Tags

- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **docker**: docker
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
