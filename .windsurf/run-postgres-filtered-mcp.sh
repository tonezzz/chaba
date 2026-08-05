#!/bin/bash
# Filtered PostgreSQL MCP server - only CRUD operations for token optimization
# Essential tools: query, execute, insert, update, delete

/tmp/mcp-filter-venv/bin/python -m mcp_filter run \
  --transport stdio \
  --stdio-command "/bin/bash" \
  --stdio-arg "/home/tony/CascadeProjects/chaba/.windsurf/run-postgres-crud-mcp.sh" \
  --allow-tool "query" \
  --allow-tool "execute" \
  --allow-tool "insert" \
  --allow-tool "update" \
  --allow-tool "delete" \
  --health
