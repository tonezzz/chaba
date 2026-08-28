---
category: operations
---

# mddb MCP Server Configuration

## Context

The mddb MCP server requires specific URL configuration including both the correct port and the `/mcp` path suffix. Misconfiguration leads to connection failures when trying to use MCP tools.

## Issue

Initial MCP configuration pointed to `http://localhost:9000` which failed because:
1. Wrong port (9000 vs 9001)
2. Missing `/mcp` path suffix

## Root Cause

**Docker Port Mapping**: The mddb docker container maps internal port 9000 to host port 9001:
```yaml
ports:
  - "9001:9000"  # host:container
```

**MCP Endpoint Path**: The mddb MCP server serves the MCP protocol at `/mcp` path, not the root URL.

## Correct Configuration

**MCP Config** (`~/.config/devin/mcp_config.json`):
```json
{
  "mddb": {
    "url": "http://localhost:9001/mcp"
  }
}
```

**Verification**:
```bash
# Test MCP endpoint (should return "MCP-Session-Id required")
curl -s http://localhost:9001/mcp
# Expected: {"error":"MCP-Session-Id required"}

# Check container status
docker ps | grep mddb

# View MCP server logs
docker logs mddb | grep MCP
```

## Available MCP Tools

After successful configuration, mddb provides these MCP tools:
- `add_document` - Add or update documents
- `search_documents` - Search with filters and sorting
- `delete_document` - Delete documents
- `get_stats` - Get server statistics
- `aggregate` - Compute metadata facets and histograms
- `semantic_search` - Search by meaning using semantic similarity

## Troubleshooting

**Symptom**: "Failed to list tools for server `mddb`"

**Checks**:
1. Verify docker container is running: `docker ps | grep mddb`
2. Check port mapping: `docker port mddb`
3. Test MCP endpoint: `curl -s http://localhost:9001/mcp`
4. Verify MCP logs: `docker logs mddb | grep MCP`
5. Check for conflicting host processes: `ps aux | grep mddbd`

**Dual Process Issue**: If a host process `/app/mddbd` is running alongside the docker container, it may cause port conflicts. The docker container is the correct source for MCP connectivity.

## Related Documentation

- `stacks/web/mddb/docker-compose.yml` - mddb container configuration
- `docs/ssot/infrastructure/ssot.services.yml` - Service definitions and ports
- `docs/ssot/infrastructure/ssot.health.yml` - Health check endpoints (includes mddb-mcp check)

## Health Monitoring

The mddb-mcp endpoint is monitored by the health check system:
- **Service ID**: `mddb-mcp`
- **URL**: `http://tony-omen.local:9001/mcp`
- **Service Group**: `ssot-sync`
- **Recovery Actions**: Include MCP config verification and container restart

## Date Added

2026-08-12
