---
category: operations
---

# Content Guidelines

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

