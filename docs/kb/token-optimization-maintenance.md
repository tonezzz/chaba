---
category: operations
---

# Maintenance

### Weekly
- Review token usage statistics
- Check proxy performance
- Verify MCP server health

### Monthly
- Check for mcp-filter updates
- Check for Headroom proxy updates
- Review and optimize filter configurations

### Quarterly
- Evaluate overall token optimization effectiveness
- Review cost savings achieved
- Plan future improvements

## Configuration Reference

### MCP Filter Environment Variables
- **MF_ALLOW_TOOLS**: Comma-separated list of allowed tool names
- **MF_SHOW_TOKEN_ESTIMATES**: Enable token estimate logging (1 = enabled)
- **MF_TRANSPORT**: Transport type (stdio or http)
- **MF_STDIO_COMMAND**: Upstream MCP server command
- **MF_STDIO_ARGS**: Arguments for upstream MCP server

### Headroom Proxy Configuration
- **--host**: Host to bind to (default: 127.0.0.1)
- **--port**: Port to bind to (default: 8787)
- **--mode**: Optimization mode (token or cache)
- **--no-optimize**: Disable optimization (passthrough mode)
- **--no-cache**: Disable semantic caching

## Testing Guide

### Test Environment
- **MCP Filtering**: mcp-filter v0.2.0 installed in `/tmp/mcp-filter-venv`
- **Headroom Proxy**: headroom-ai v0.34.0 installed in `/tmp/headroom-venv`
- **Configuration Files**: Updated in `~/.config/devin/mcp_config.json`
- **Filter Scripts**: Created in `.windsurf/` directory

### Test Results (2026-08-05)

#### ✅ MCP Server Filtering Tests - PASSED

**Yomi MCP Server Filtering**
- Status: ✅ PASSED
- Actual Tools: list_conversations, get_chat_messages, get_insight, health
- Tool Count: 4 tools (3 essential + 1 health)
- Reduction: 73% reduction from 15+ tools
- Health Check: Upstream OK, token estimate functional

**PostgreSQL MCP Server Filtering**
- Status: ✅ PASSED
- Actual Tools: query, execute, insert, update, delete, health
- Tool Count: 6 tools (5 essential + 1 health)
- Reduction: 45% reduction from 11 tools
- Health Check: Upstream OK, token estimate functional

**GitHub MCP Server Filtering**
- Status: ✅ PASSED
- Actual Tools: add_comment_to_pending_review, add_issue_comment, create_pull_request, get_file_contents, list_commits, list_pull_requests, search_issues, health
- Tool Count: 8 tools (7 essential + 1 health)
- Reduction: 60% reduction from 20+ tools
- Health Check: Upstream OK, token estimate functional

#### ✅ Disabled MCP Servers - PASSED
- Status: ✅ PASSED
- Disabled Servers: remote-exec-tony-dell, mcp-llama, playlive.tony-dell
- Active Servers: postgres, github, yomi, mcp-gpu
- Result: Only essential servers active, disabled servers not accessible

#### ✅ Headroom Proxy - PASSED
- Status: ✅ PASSED
- Proxy URL: http://127.0.0.1:8787
- Mode: cache (provider prefix cache stability)
- Health Check: All systems healthy, upstream connections OK
- Optimization: ENABLED
- Caching: ENABLED
- Rate Limiting: ENABLED

### Token Usage Measurement

**Before Optimization**:
- Total MCP tools: ~65 tools
- Estimated token overhead: 25-40k tokens per session

**After Optimization**:
- Total MCP tools: 18 tools (72% reduction from 65)
  - Yomi: 4 tools (73% reduction from 15+)
  - PostgreSQL: 6 tools (45% reduction from 11)
  - GitHub: 8 tools (60% reduction from 20+)
  - GPU: 4 tools (no change, already minimal)
- Estimated token overhead: 8-13k tokens per session (65-70% reduction)

### Rollback Procedures

**MCP Filtering Rollback**:
1. Edit `~/.config/devin/mcp_config.json`
2. Revert filtered server configurations to original
3. Restart Devin Desktop
4. Verify functionality restored

**Headroom Proxy Rollback**:
1. Stop Headroom proxy process
2. Remove proxy configuration from Devin
3. Restart Devin Desktop
4. Verify direct connection works

**Disabled Servers Rollback**:
1. Edit `~/.config/devin/mcp_config.json`
2. Remove `"disabled": true` from server configurations
3. Restart Devin Desktop
4. Verify servers are accessible

