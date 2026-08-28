---
category: operations
---

# MCP Server Analysis

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

- **Implementation Status**: ✅ COMPLETED - Filtered to 4 tools (73% reduction)
- **Current Filtered Tools**: list_conversations, get_chat_messages, get_insight, get_unread_digest
- **Actual Reduction**: 15+ tools → 4 tools (73% reduction)
- **Token Savings**: ~8-12k → ~2-3k tokens per session

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

- **Implementation Status**: ✅ COMPLETED - Filtered to 6 tools (45% reduction)
- **Current Filtered Tools**: query, execute, insert, update, delete
- **Actual Reduction**: 11 tools → 6 tools (45% reduction)
- **Token Savings**: ~3-5k → ~1-2k tokens per session

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

- **Implementation Status**: ✅ COMPLETED - Filtered to 8 tools (60% reduction)
- **Current Filtered Tools**: search_issues, create_issue, add_issue_comment, create_pull_request, list_pull_requests, add_comment_to_pending_review, list_commits, get_file_contents
- **Actual Reduction**: 20+ tools → 8 tools (60% reduction)
- **Token Savings**: ~10-15k → ~3-5k tokens per session

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

- **Implementation Status**: ✅ NO CHANGES NEEDED
- **Reasoning**: Already minimal tool set, all tools are actively used
- **Current State**: 4 tools (unchanged)

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

- **Implementation Status**: ✅ DISABLED
- **Reasoning**: Low usage, not essential for current workflow
- **Token Savings**: ~1-2k tokens eliminated

### 6. playlive.tony-dell MCP Server
- **Tool Count**: 10+ tools
- **Estimated Token Overhead**: 3-5k tokens
- **Usage Pattern**: UNKNOWN - needs usage analysis
- **Optimization Priority**: MEDIUM
- **Current Tools**:
  - Session management: create_chrome_live, create_playwright_chrome, create_playwright, list_sessions, close_session
  - Browser actions: navigate, click, fill, select, eval
  - And more...

- **Implementation Status**: ✅ DISABLED
- **Reasoning**: Low usage, not essential for current workflow
- **Token Savings**: ~3-5k tokens eliminated

### 7. remote-exec-tony-dell MCP Server
- **Tool Count**: UNKNOWN
- **Estimated Token Overhead**: UNKNOWN
- **Usage Pattern**: UNKNOWN
- **Optimization Priority**: TBD
- **Status**: FAILED TO LIST TOOLS - needs investigation

- **Implementation Status**: ✅ DISABLED
- **Reasoning**: Not essential for current workflow
- **Token Savings**: TBD (unknown tool count)

