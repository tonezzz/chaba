---
category: operations
---

# mddb MCP Server Configuration

## Context

The mddb MCP server requires the correct URL and the `/mcp` path suffix. Misconfiguration leads to connection failures when trying to use MCP tools.

## Current Runtime (tony-dell)

The migrated `mddb` Quadlet/systemd service on `tony-dell` uses host networking and exposes the MCP endpoint directly on port `9000`:

- **MCP URL**: `http://tony-dell:9000/mcp` (Tailscale IP `100.68.142.13`)
- **HTTP API**: `http://tony-dell:11023`
- **gRPC**: `http://tony-dell:11024`

The legacy `docker-compose.yml` in `stacks/web/mddb/docker-compose.yml` still maps `9001:9000`; that mapping applies only to the old Compose stack on `tony-omen` and is no longer used for the live MCP endpoint.

## Correct Configuration

**MCP Config** (`~/.config/devin/mcp_config.json`):
```json
{
  "mddb": {
    "url": "http://100.68.142.13:9000/mcp"
  }
}
```

**Verification**:
```bash
# Test MCP endpoint (should return "MCP-Session-Id required")
curl -s http://tony-dell:9000/mcp
# Expected: {"error":"MCP-Session-Id required"}

# Check container status
ssh tony-dell 'podman ps | grep mddb'

# View MCP server logs
ssh tony-dell 'podman logs mddb | grep MCP'
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
- **URL**: `http://tony-dell:9000/mcp`
- **Expected status**: `400` (`{"error":"MCP-Session-Id required"}`)
- **Service Group**: `ssot-sync`
- **Recovery Actions**: Include MCP config verification and container restart

## Date Added

2026-08-12
