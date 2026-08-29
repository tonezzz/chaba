# Overnight System Assessment Report
**Date:** 2026-08-29  
**Timestamp:** 20260829-1452  
**Hostname:** tony-dell  
**Duration:** Snapshot  

## Executive Summary

All critical services on `tony-dell` are healthy. The migration from `tony-omen` Docker to `tony-dell` rootless Podman continues to pass end-to-end health checks.

## 1. Health Check Integration

**Profile:** home  
**Base URL:** http://tony-dell:8080

### Service Status Summary

- **Total services:** 57
- **Healthy:** 37
- **Degraded:** 0
- **Error:** 0
- **Unknown:** 0
- **Intentional (disabled):** 20

### Category Breakdown

| Category | Healthy | Intentional | Notes |
|----------|---------|-------------|-------|
| web      | 8       | 0           | Caddy, BServer, Raceman Web, Helm Dashboard, MDDB Panel, Home Assistant |
| api      | 9       | 1           | Sensor Reader disabled (tony-omen) |
| datastore| 7       | 3           | Redis/Postgres/MDDB Container disabled |
| gpu      | 1       | 3           | Llama/Imagen2/Txt2Vid disabled |
| queue    | 1       | 0           | GPU Queue healthy |
| optional | 0       | 3           | Activepieces/Frigate/Camera disabled |
| automation| 1      | 0           | Trade Automation healthy |
| mcp      | 1       | 1           | Workflows MCP healthy; RView Proxy disabled |
| mcp-debug| 2       | 0           | MCP Debug SSE + CORS healthy |
| system   | 6       | 6           | Timers and tony-omen canary services |
| tony-dell| 1       | 0           | tony-dell host canary healthy |
| tailscale| 1       | 0           | Tailscale status healthy |

### Critical Service Health

- **Caddy Web Server:** healthy
- **PostgreSQL:** intentional (disabled from quick checks)
- **Weaviate:** healthy
- **Redis:** intentional (disabled)
- **Yomi API:** healthy
- **Trade API:** healthy
- **GPU Queue:** healthy
- **Status Data API:** healthy
- **MDDB API:** healthy
- **Workflows MCP:** healthy
- **Home Assistant:** healthy

## 2. Quick Health

`mcp-health quick_health` returned:

- **Services checked:** 8
- **Passed:** 8
- **Failed:** 0

## 3. Configuration Validation

- SSOT validation: 243/243 files valid, 0 errors, 0 warnings.
- `mcp-health-snapshot` systemd user timer is active and logging every 10 minutes.

## 4. Conclusion

No alerts. No failing services. The `tony-dell` health profile is stable.
