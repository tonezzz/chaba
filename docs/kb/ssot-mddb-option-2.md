---
category: operations
---

# Option 2: SSOT Documentation in MDDB

### Architecture
```
SSOT YAML Files (Direct Edit - Config Only)
SSOT Documentation (MDDB - Search Only)
```

### Implementation
- **SSOT YAML**: Keep for actual configuration values
- **SSOT Documentation**: Create MDDB entries with SSOT descriptions
- **Metadata**: Link to YAML files for reference
- **Content**: Human-readable SSOT descriptions, not raw YAML

### Example Structure
```markdown
# SSOT: MCP Infrastructure Configuration
title: MCP Infrastructure Configuration
subtitle: Single source of truth for MCP server configuration
icon: 🔧
...
```

### Benefits
- ✅ Preserves direct YAML editing
- ✅ Rich metadata for better search
- ✅ Single source of truth (YAML file)
- ✅ No separate documentation needed
- ✅ Frontmatter is standard practice

### Challenges
- ⚠️ Requires modifying all SSOT YAML files
- ⚠️ Frontmatter parsing complexity
- ⚠️ YAML validation becomes more complex
- ⚠️ Frontmatter may interfere with YAML processing

### Implementation Complexity: Medium-High

## Overview
Single source of truth for MCP server configuration...

## Server Definitions
### github
- Name: GitHub Integration
- Description: GitHub API integration for workflow automation
- Implementation: docker ghcr.io/github/github-mcp-server:latest

## Related Files
- docs/ssot/infrastructure/ssot.mcp.yml
- ~/.config/devin/mcp_config.json
```

### Benefits
- ✅ Preserves direct YAML editing
- ✅ High-quality semantic search (human-readable content)
- ✅ Clean separation of config vs documentation
- ✅ No sync mechanism needed
- ✅ Better search relevance

### Challenges
- ⚠️ Requires maintaining documentation separately from YAML
- ⚠️ Potential duplication between YAML and documentation
- ⚠️ Documentation may become outdated
- ⚠️ Higher maintenance overhead

### Implementation Complexity: Low

