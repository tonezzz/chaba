# MCP Server Audit Report

## Executive Summary

Comprehensive audit of configured MCP servers to identify token optimization opportunities. Total current MCP tool count: ~65 tools across 7 servers, estimated token overhead: 25-40k tokens per session.

**Total MCP Tools**: ~65 tools
**Estimated Token Overhead**: 25-40k tokens per session
**Optimization Potential**: 50-70% reduction through filtering

## MCP Server Analysis

### 1. Yomi MCP Server
- **Tool Count**: 15+ tools
- **Estimated Token Overhead**: 8-12k tokens
- **Usage Pattern**: HIGH - frequently used for communication analysis
- **Optimization Priority**: HIGH
- **Current Tools**:
  - login, login_complete (authentication)
  - list_conversations (conversation listing)
  - get_chat_messages (message retrieval)
  - get_message_image, get_message_media (media download)
  - get_unread_digest (unread summary)
  - get_insight (attention analysis)
  - send_message (messaging)
  - search_messages (message search)
  - collect_messages (bulk collection)
  - exclude_chats, include_chats (chat management)
  - list_excluded_chats (exclusion list)
  - get_scope_policy (policy management)

- **Recommended Essential Tools** (3 tools, ~80% reduction):
  - `list_conversations` - Conversation listing
  - `get_chat_messages` - Message retrieval  
  - `get_insight` - Attention analysis

- **Optional Tools** (if needed):
  - `send_message` - If sending messages is required
  - `get_unread_digest` - If unread monitoring is needed

- **Tools to Filter Out** (10+ tools):
  - Authentication tools (if session is persistent)
  - Media download tools (if not needed)
  - Chat management tools (if exclusion not needed)
  - Search and collection tools (if not needed)

### 2. PostgreSQL MCP Server
- **Tool Count**: 11 tools
- **Estimated Token Overhead**: 3-5k tokens
- **Usage Pattern**: MEDIUM - used for GPU queue and application data
- **Optimization Priority**: MEDIUM
- **Current Tools**:
  - query (read-only SQL)
  - execute (write SQL)
  - insert (record insertion)
  - update (record updates)
  - delete (record deletion)
  - createTable (DDL operations)
  - createFunction (function creation)
  - createTrigger (trigger creation)
  - createIndex (index creation)
  - alterTable (table alteration)

- **Recommended Essential Tools** (5 tools, ~60% reduction):
  - `query` - Read-only queries
  - `execute` - Write operations
  - `insert` - Record insertion
  - `update` - Record updates
  - `delete` - Record deletion

- **Tools to Filter Out** (6 tools):
  - DDL tools (createTable, createFunction, createTrigger, createIndex, alterTable)
  - These are rarely used in day-to-day operations

### 3. GitHub MCP Server
- **Tool Count**: 20+ tools
- **Estimated Token Overhead**: 10-15k tokens
- **Usage Pattern**: MEDIUM - used for git workflow automation
- **Optimization Priority**: MEDIUM
- **Current Tools**:
  - Issues: create_issue, list_issue_types, search_issues, get_issue, update_issue, add_issue_comment
  - Pull Requests: create_pull_request, list_pull_requests, get_pull_request, update_pull_request, pull_request_review_write, add_comment_to_pending_review, add_reply_to_pull_request_comment
  - Commits: list_commits, get_commit
  - Files: create_file, update_file, delete_file, get_file_contents
  - Repositories: list_repositories, get_repository
  - And many more...

- **Recommended Essential Tools** (6-8 tools, ~70% reduction):
  - `search_issues` - Issue search
  - `create_issue` - Issue creation
  - `add_issue_comment` - Issue commenting
  - `create_pull_request` - PR creation
  - `list_pull_requests` - PR listing
  - `add_comment_to_pending_review` - PR review comments
  - `list_commits` - Commit history
  - `get_file_contents` - File reading

- **Tools to Filter Out** (12+ tools):
  - Advanced issue management (update_issue, list_issue_types)
  - Advanced PR operations (update_pull_request, get_pull_request)
  - File operations (create_file, update_file, delete_file)
  - Repository management (list_repositories, get_repository)
  - Specialized tools (milestones, projects, etc.)

### 4. GPU MCP Server
- **Tool Count**: 4 tools
- **Estimated Token Overhead**: 1-2k tokens
- **Usage Pattern**: HIGH - used for GPU queue operations
- **Optimization Priority**: LOW
- **Current Tools**:
  - gpu_status (GPU status)
  - hold_llama (move llama to CPU)
  - resume_llama (restore llama to GPU)
  - generate_image (image generation)

- **Recommendation**: NO FILTERING NEEDED
- **Reasoning**: Already minimal tool set, all tools are actively used

### 5. mcp-llama MCP Server
- **Tool Count**: 5 tools
- **Estimated Token Overhead**: 1-2k tokens
- **Usage Pattern**: UNKNOWN - needs usage analysis
- **Optimization Priority**: LOW
- **Current Tools**:
  - chat (chat with model)
  - complete (text completion)
  - tokenize (tokenization)
  - models (list models)
  - status (server status)

- **Recommendation**: MONITOR USAGE FIRST
- **Reasoning**: Low overhead, unclear usage pattern

### 6. playlive.tony-dell MCP Server
- **Tool Count**: 10+ tools
- **Estimated Token Overhead**: 3-5k tokens
- **Usage Pattern**: UNKNOWN - needs usage analysis
- **Optimization Priority**: MEDIUM
- **Current Tools**:
  - Session management: create_chrome_live, create_playwright_chrome, create_playwright, list_sessions, close_session
  - Browser actions: navigate, click, fill, select, eval
  - And more...

- **Recommendation**: ANALYZE USAGE PATTERN
- **Reasoning**: Medium overhead, need to determine if actively used

### 7. remote-exec-tony-dell MCP Server
- **Tool Count**: UNKNOWN
- **Estimated Token Overhead**: UNKNOWN
- **Usage Pattern**: UNKNOWN
- **Optimization Priority**: TBD
- **Status**: FAILED TO LIST TOOLS - needs investigation

- **Recommendation**: INVESTIGATE SERVER STATUS
- **Reasoning**: Could not retrieve tool list, server may be misconfigured

## Optimization Recommendations

### Immediate Actions (Phase 1)
1. **Disable Unused Servers**: Disable servers with unknown/low usage patterns
   - remote-exec-tony-dell (investigate first, then likely disable)
   - mcp-llama (monitor usage, consider disabling if unused)
   - playlive.tony-dell (analyze usage, disable if not needed)

2. **Filter High-Usage Servers**: Implement mcp-filter for high-priority servers
   - Yomi: Filter to 3 essential tools (80% reduction)
   - PostgreSQL: Filter to 5 CRUD tools (60% reduction)
   - GitHub: Filter to 6-8 core tools (70% reduction)

### Expected Impact
- **Yomi Filtering**: 8-12k → 2-3k tokens (75% reduction)
- **PostgreSQL Filtering**: 3-5k → 1-2k tokens (60% reduction)
- **GitHub Filtering**: 10-15k → 3-5k tokens (70% reduction)
- **Unused Server Cleanup**: 5-8k tokens elimination
- **Total Expected Reduction**: 25-40k → 8-13k tokens (65-70% reduction)

## Implementation Priority

### HIGH Priority (Implement First)
1. Yomi MCP filtering (highest usage, highest savings)
2. Disable unused/unknown servers
3. PostgreSQL MCP filtering (medium usage, good savings)

### MEDIUM Priority (Implement Second)
1. GitHub MCP filtering (medium usage, good savings)
2. playlive.tony-dell analysis and potential filtering

### LOW Priority (Implement Last)
1. mcp-llama monitoring and potential filtering
2. GPU server (no action needed, already optimal)

## Next Steps

1. **Implement Phase 1**: Disable unused servers
2. **Install mcp-filter**: Set up filtering infrastructure
3. **Configure Yomi filtering**: Highest priority, highest impact
4. **Configure PostgreSQL filtering**: Medium priority, good impact
5. **Configure GitHub filtering**: Medium priority, good impact
6. **Test and validate**: Ensure all filtered servers work correctly
7. **Monitor results**: Track token reduction and functionality

## Risk Assessment

### Low Risk
- Disabling unused servers (easily reversible)
- Filtering tools (can revert to direct connection)

### Medium Risk
- Filtering essential tools (may break workflows)
- Need to test thoroughly after filtering

### Mitigation
- Start with conservative filtering (allow more tools initially)
- Test each filtered server independently
- Maintain rollback documentation
- Monitor for errors or functionality issues
