---
category: operations
---

# MDDB Collections
collections:
  chaba-kb-system: 27 documents
  chaba-kb-development: 15 documents
  chaba-kb-operations: 4 documents
  chaba-kb-features: 42 documents
  trade-kb-system: [trade docs]
  trade-kb-development: [trade docs]
  trade-kb-operations: [trade docs]
  trade-kb-features: [trade docs]
```

**Benefits**:
- Unified search across all projects
- Consistent KB management
- Single backup strategy
- Simplified MCP configuration
- Cross-project knowledge sharing

**Migration Strategy**:
1. Add trade project collections to existing MDDB
2. Migrate trade documentation to MDDB
3. Remove docs-trade MCP server
4. Update AI agent tool selection logic
5. Add project context metadata to documents

### Option 2: Enhanced Multi-Project mcp-kbman

**Architecture**:
- Revive mcp-kbman with multi-project support
- Project-aware routing and filtering
- Unified MCP interface for all projects
- Backend flexibility (MDDB, file-based, etc.)

**Implementation**:
```python
# Enhanced mcp-kbman features
class MultiProjectKBManager:
    def __init__(self):
        self.projects = {
            'chaba': {'backend': 'mddb', 'collection_prefix': 'chaba-'},
            'trade': {'backend': 'file', 'path': '/home/tony/CascadeProjects/trade/docs'},
            'other': {'backend': 'tbd'}
        }
    
    def search(self, query, project=None):
        if project:
            return self.search_project(query, project)
        else:
            return self.search_all(query)
    
    def add_document(self, content, project, category):
        backend = self.projects[project]['backend']
        # Route to appropriate backend
```

**Benefits**:
- Unified MCP interface
- Project-aware tool selection
- Flexible backend support
- Gradual migration path
- Cross-project search capability

**Challenges**:
- Requires completing mcp-kbman development
- More complex architecture
- Additional maintenance overhead

### Option 3: Project Context Tool Naming

**Architecture**:
- Keep current fragmented system
- Add project context to tool names
- AI agent context awareness
- Manual project selection

**Implementation**:
```json
{
  "mcpServers": {
    "docs-chaba": {
      "args": ["@devista/docs-mcp", "-y", "--docs", "/home/tony/CascadeProjects/chaba/docs"],
      "command": "npx"
    },
    "docs-trade": {
      "args": ["@devista/docs-mcp", "-y", "--docs", "/home/tony/CascadeProjects/trade/docs"],
      "command": "npx"
    }
  }
}
```

**Benefits**:
- Minimal changes required
- Clear project separation
- No migration needed
- Simple to implement

**Drawbacks**:
- Still fragmented architecture
- No cross-project search
- Redundant infrastructure
- Manual project selection required

