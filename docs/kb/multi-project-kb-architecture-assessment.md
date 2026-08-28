---
category: operations
---

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

## See also

- [Multi Project Kb Ai Agent](multi-project-kb-ai-agent.md)
- [Multi Project Kb Mddb Collections](multi-project-kb-mddb-collections.md)
- [Multi Project Kb Proposed Solutions](multi-project-kb-proposed-solutions.md)
