---
category: operations
---

# Standard Structure

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

