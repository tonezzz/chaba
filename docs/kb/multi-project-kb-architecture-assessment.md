# Multi-Project KB Architecture Assessment

**Date**: 2026-08-12
**Purpose**: Assess gaps for unified KB system supporting chaba, trade, and other projects

## Current Architecture

### Project-Specific KB Systems

**Chaba Project**:
- **Primary KB**: MDDB (http://tony-omen.local:3002/)
- **Docs MCP**: docs server for chaba documentation
- **Location**: /home/tony/CascadeProjects/chaba/docs
- **Status**: Migrated to MDDB, docs MCP still active

**Trade Project**:
- **Primary KB**: File-based documentation system
- **Docs MCP**: docs-trade server for trade documentation
- **Location**: /home/tony/CascadeProjects/trade/docs
- **Status**: Active with extensive documentation

**Other Projects**: Unknown (need assessment)

### Current MCP Configuration

**docs (Chaba)**:
```json
{
  "docs": {
    "args": ["@devista/docs-mcp", "-y", "--docs", "/home/tony/CascadeProjects/chaba/docs"],
    "command": "npx"
  }
}
```

**docs-trade (Trade)**:
```json
{
  "docs-trade": {
    "args": ["@devista/docs-mcp", "-y", "--docs", "/home/tony/CascadeProjects/trade/docs", "--cache-dir", "/home/tony/CascadeProjects/trade/.docs-mcp"],
    "command": "npx"
  }
}
```

## Identified Gaps

### 1. Fragmented KB Architecture
**Gap**: Each project has separate KB system and docs MCP server
**Impact**: 
- AI agents must know which project context they're working in
- No unified search across projects
- Redundant infrastructure (multiple docs MCP instances)
- Inconsistent KB management approaches

### 2. Tool Selection Ambiguity
**Gap**: AI agents receive tools from multiple docs MCP servers without clear project context
**Impact**:
- Difficult to select correct tools for cross-project work
- Risk of using wrong project's documentation
- No automatic project context awareness
- Manual tool selection required

### 3. Cross-Project Search Limitations
**Gap**: No unified search across project documentation
**Impact**:
- Cannot find related information across projects
- Duplicate documentation possible
- No shared knowledge base
- Siloed information

### 4. Inconsistent KB Management
**Gap**: Chaba uses MDDB, Trade uses file-based system
**Impact**:
- Different search capabilities
- Inconsistent user experience
- No unified backup strategy
- Different maintenance procedures

## Proposed Solutions

### Option 1: Unified MDDB for All Projects (Recommended)

**Architecture**:
- Single MDDB instance serving all projects
- Project-specific collections for isolation
- Unified semantic search across all projects
- Consistent MCP integration

**Implementation**:
```yaml
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

## AI Agent Tool Selection Improvements

### Current Issues
- Tools from multiple docs MCP servers without context
- No automatic project awareness
- Manual tool selection required
- Risk of using wrong project's documentation

### Proposed Improvements

#### 1. Project Context Metadata
```python
# Add project context to tool descriptions
tools = [
    {
        "name": "search_docs_chaba",
        "description": "Search chaba project documentation",
        "project": "chaba",
        "scope": "chaba knowledge base"
    },
    {
        "name": "search_docs_trade",
        "description": "Search trade project documentation", 
        "project": "trade",
        "scope": "trade knowledge base"
    }
]
```

#### 2. Context-Aware Tool Selection
```python
def select_tools_for_context(context):
    """Select appropriate tools based on project context"""
    if context.get('project') == 'chaba':
        return ['mddb', 'docs-chaba']
    elif context.get('project') == 'trade':
        return ['docs-trade', 'postgres']
    else:
        return ['mddb', 'docs-chaba', 'docs-trade']
```

#### 3. Unified Search Interface
```python
def unified_search(query, project=None):
    """Search across all projects with optional project filter"""
    if project:
        return search_project(query, project)
    else:
        results = []
        for proj in ['chaba', 'trade']:
            results.extend(search_project(query, proj))
        return deduplicate_results(results)
```

## Recommendation

### Short-term (Immediate)
1. **Keep docs-trade active** - Trade project needs search capability
2. **Add project context to tool names** - Rename docs → docs-chaba
3. **Document project context** - Add project context to tool descriptions
4. **Assess other projects** - Identify all projects needing KB support

### Medium-term (1-2 weeks)
1. **Evaluate unified MDDB approach** - Test multi-project MDDB architecture
2. **Prototype cross-project search** - Build unified search interface
3. **Assess trade documentation migration** - Evaluate moving trade docs to MDDB
4. **Design tool selection logic** - Implement context-aware tool selection

### Long-term (1-2 months)
1. **Implement unified KB system** - Either MDDB or enhanced mcp-kbman
2. **Migrate all projects** - Consolidate all project documentation
3. **Remove redundant docs MCP servers** - Simplify infrastructure
4. **Implement AI agent context awareness** - Automatic project detection

## Next Steps

1. **Assess other projects** - Identify all projects needing KB support
2. **Evaluate trade documentation** - Determine if trade should migrate to MDDB
3. **Prototype unified search** - Test cross-project search capabilities
4. **Design tool selection** - Implement context-aware tool selection logic
5. **Choose architecture** - Decide between unified MDDB or enhanced mcp-kbman

## Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Migration Strategy**: docs/kb/mddb-migration-strategy.md
- **mcp-kbman Archive**: mcp-kbman.archive/README.md
- **SSOT MCP Infrastructure**: docs/ssot/infrastructure/ssot.mcp.yml