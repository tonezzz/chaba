# Health Monitoring Mcp-Health 2026-08-18

## What it is

Health Monitoring Mcp-Health 2026-08-18

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
Health monitoring / mcp-health (2026-08-18):
- mcp-health MCP server was failing to start because it defaulted to localhost:5432; postgres is on tony-dell.
- Added POSTGRES_HOST=tony-dell to ~/.config/devin/mcp_config.json and docs/ssot/infrastructure/ssot.mcp.yml.
- Caddy on tony-omen did not route /api/yomi/* or /api/weaviate/* to tony-dell, causing status-data-api 404 and health-check errors. Added Caddy handlers and reloaded.
- Caddy health check url changed from /apps/ (which returned 404) to /apps/map/ (which returns 200).
- Health score improved from 67 (D) to 75 (C); caddy and yomi-api now healthy.
- The mcp-health database currently contains historical entries from 2026-08-15, so get_health_status reflects the last full run, not just this test.

Conventions:
- For mcp-health to be stable, it needs POSTGRES_HOST pointing at the actual postgres host (tony-dell), not localhost.
- Use Caddy handle/handle_path before the catch-all handle /api/* to proxy /api/yomi and /api/weaviate to tony-dell ports 3000 and 8084.
- When /home fills, git and podman image operations fail; safe first-step cleanup is pip cache and untracked podman images before deleting user data.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-18
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
