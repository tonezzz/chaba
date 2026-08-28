---
category: operations
---

# Option 3: SSOT YAML with Frontmatter Metadata

### Architecture
```
SSOT YAML Files (Direct Edit)
    ↓ (frontmatter extraction)
MDDB Collections (Search + Metadata)
```

### Implementation
- **SSOT YAML**: Add frontmatter metadata to YAML files
- **Extraction**: Parse frontmatter for search indexing
- **Content**: YAML content + frontmatter in MDDB
- **Metadata**: Extracted from frontmatter for better search

### Example Structure
```yaml
---
title: MCP Infrastructure Configuration
description: Single source of truth for MCP server configuration
tags: [mcp, infrastructure, configuration]
collection: ssot-infrastructure
---

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

