#!/bin/bash
# Filtered Yomi MCP server - only essential tools for token optimization
# Essential tools: list_conversations, get_chat_messages, get_insight

/tmp/mcp-filter-venv/bin/python -m mcp_filter run \
  --transport stdio \
  --stdio-command "/usr/bin/node" \
  --stdio-arg "/home/tony/.yomi/mcpb/run.mjs" \
  --allow-tool "list_conversations" \
  --allow-tool "get_chat_messages" \
  --allow-tool "get_insight" \
  --health
