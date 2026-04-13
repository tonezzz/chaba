#!/bin/bash
# MCP Wiki client for Windsurf
# Connects to idc1-mcp-wiki container via stdio

docker exec -i idc1-mcp-wiki sh -c 'MCP_STDIO=1 node index.js'
