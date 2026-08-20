---
category: operations
---

# KB Workflow Integration

## What it is

Complete KB workflow compliance implementation in mcp-kbman MCP server providing automated git operations, duplicate detection, frontmatter validation, session management, and changelog tracking to maintain KB data integrity while providing modern search capabilities.

## Context/Background

Implemented on 2026-08-11 to address the gap between modern search capabilities and proven KB workflow rules. The integration ensures mcp-kbman respects all KB workflow requirements (kb-start.sh/kb-end.sh) while adding powerful search and automation features, enabling gradual migration from manual workflow to automated MCP-based workflow.

## Related Documentation

- **[mcp-tools.md](../../CascadeProjects/chaba/docs/kb/mcp-tools.md)** - MCP server inventory including mcp-kbman
- **[workflows-mcp-integration.md](workflows-mcp-integration.md)** - Workflow automation integration
- **[mcp-kbman-architecture.md](meta/mcp-kbman-architecture.md)** - Search architecture details
- **[background-task-caching.md](meta/background-task-caching.md)** - Background task system

## Tags

- **mcp-kbman**: MCP knowledge base management server
- **kb-workflow**: KB workflow compliance
- **git**: Version control operations
- **validation**: Data validation and checking
- **automation**: Task automation and workflow
- **duplicate-detection**: File duplicate identification

## See also

- [Architecture Kb Workflow Integration Details](architecture-kb-workflow-integration-details.md)
- [Architecture Kb Workflow Integration Implementation](architecture-kb-workflow-integration-implementation.md)
