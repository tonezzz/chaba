#!/bin/bash
# Filtered GitHub MCP server - only core workflow tools for token optimization
# Essential tools: search_issues, create_issue, add_issue_comment, create_pull_request, list_pull_requests, add_comment_to_pending_review, list_commits, get_file_contents

/tmp/mcp-filter-venv/bin/python -m mcp_filter run \
  --transport stdio \
  --stdio-command "/bin/bash" \
  --stdio-arg "/home/tony/CascadeProjects/chaba/.windsurf/run-github-mcp.sh" \
  --allow-tool "search_issues" \
  --allow-tool "create_issue" \
  --allow-tool "add_issue_comment" \
  --allow-tool "create_pull_request" \
  --allow-tool "list_pull_requests" \
  --allow-tool "add_comment_to_pending_review" \
  --allow-tool "list_commits" \
  --allow-tool "get_file_contents" \
  --health
