---
name: ssot-search
description: Search across all SSOT YAML files for keywords (use MCP docs server for broader documentation search)
allowed-tools:
  - grep
  - read
  - mcp_call_tool
triggers:
  - user
  - model
---

Search across all SSOT YAML files in docs/ssot/:

1. Accept search term as argument or prompt for it
2. Ask user: "Search SSOT YAML only (grep) or all documentation (MCP docs server)?"
3. If SSOT YAML only:
   - Search across all SSOT files matching pattern: docs/ssot/**/*.yml
   - Exclude template file: template.yml
   - Use grep to find matches with context (2 lines before and after)
   - Group results by SSOT file
   - For each matching file:
     - Show file name
     - Show matching lines with context
     - Count total matches in that file
   - Provide summary:
     - Total files searched
     - Files with matches
     - Total matches across all files
4. If all documentation (MCP docs server):
   - Use mcp_call_tool with server "docs" and tool "search_docs"
   - Pass search query and optional limit (default: 5)
   - Display results with path, excerpt, and relevance ranking
   - Offer to retrieve full page content with get_page tool
5. If no matches found, suggest:
   - Try different search terms
   - Check spelling
   - Use broader terms
   - Try the other search method (SSOT vs MCP)
