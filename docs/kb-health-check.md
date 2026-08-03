# Health Check Dashboard

## Overview

Real-time system health monitoring dashboard served from `http://tony-omen.local:8080/apps/health-check/` (home) or `http://localhost:8080/apps/health-check/` (mobile).

## Key files

| File | Purpose |
|------|---------|
| `chaba/stacks/web/public/apps/health-check/index.html` | Main dashboard HTML with tab navigation |
| `chaba/stacks/web/public/apps/health-check/health-check.js` | Dashboard logic, health checks, tab switching |
| `chaba/stacks/web/public/apps/health-check/health-check.css` | Dashboard styling |
| `chaba/docs/overview/ssot.health.yml` | Service definitions and recovery actions |
| `chaba/docs/overview/ssot.health.home.yml` | Home location-specific config |
| `chaba/docs/overview/ssot.health.mobile.yml` | Mobile location-specific config |

## Tabs

### Services Tab
- Overall system status summary
- Individual service health checks (HTTP, container)
- Category filtering (web, api, datastore, gpu, queue, optional)
- Recovery actions for common failure modes
- Auto-refresh support (30s interval)

### GPU Tab
- Real-time GPU hardware status from mcp-gpu
- VRAM usage with progress bar
- GPU utilization and temperature
- Running processes with memory usage
- GPU queue job status (pending, running, completed, failed)
- Currently running job details
- Quick links to GPU Queue UI and Netdata Dashboard

### Yomi Tab
- Yomi API connection status
- Conversation count and last update time
- Summarization coverage statistics
- Daily summaries count

## Location Detection

The dashboard auto-detects location (home vs mobile) by trying to reach local endpoints:
- Home: `http://tony-dell.local:8080/api/status` or `http://tony-omen.local:8080/api/status`
- Mobile: Fallback if home endpoints unreachable

Location-specific SSOT configs are loaded based on detected location.

## API Endpoints

### Status API (status-api container)
- `/api/status` - Full system status (system, host, git, containers, frigate, cameras)
- `/api/gpu/status` - GPU status (VRAM, utilization, temperature, processes)
- `/api/container/{name}` - Single container health
- `/api/turbo` - CPU turbo boost control

### Yomi API (yomi-api service)
- `/api/yomi/health` - Yomi API health check
- `/api/yomi/conversations` - Conversation list
- `/api/yomi/last-updated` - Last data update timestamp
- `/api/yomi/summarization-status` - Summarization statistics

### GPU Queue API (gpu-queue service)
- `/api/gpu-queue/status` - Queue status and running job
- `/api/gpu-queue/jobs` - Job list and submission
- `/api/gpu-queue/jobs/{id}` - Individual job status
- `/health` - Service health check

## Caddyfile Routing

Important routing rules in `chaba/stacks/web/Caddyfile`:
- `/api/gpu/*` → `status-api:8000` (must use `handle`, not `handle_path`)
- `/api/gpu-queue/*` → `host.docker.internal:3001`
- `/api/yomi/*` → `host.docker.internal:3000`
- `/api/*` → `status-api:8000` (catchall for other APIs)

## Troubleshooting

### GPU tab shows "GPU Error"
- Check status-api container is running: `docker ps | grep status-api`
- Verify GPU endpoint works: `curl http://localhost:8080/api/gpu/status`
- Check thai-legal-inference container has GPU access and nvidia-smi
- Review status-api logs: `docker logs status-api`

### Location detection stuck on "Detecting..."
- Check if hostname resolution works for tony-dell.local and tony-omen.local
- Verify network connectivity from browser to local endpoints
- Try manual location selection from dropdown

### Services show "unknown" status
- Check SSOT config files are accessible via Caddy
- Verify service endpoints are reachable from the web container
- Review browser console for CORS or network errors

### Auto-refresh not working
- Check "Auto-refresh (30s)" checkbox is enabled
- Verify browser allows JavaScript execution
- Check for JavaScript errors in browser console

## GPU Tab Implementation Details

The GPU tab integrates data from two sources:

1. **mcp-gpu** (via status-api `/api/gpu/status`):
   - GPU hardware info (model, VRAM total/used/free)
   - GPU utilization percentage
   - Temperature
   - Running processes with PID and memory usage

2. **GPU Queue** (via `/api/gpu-queue/status`):
   - Queue status counts (pending, running, completed, failed, cancelled)
   - Currently running job details (type, ID, start time)

The tab follows the same pattern as the Yomi tab with:
- Initial render on first load
- In-place updates for auto-refresh
- Error handling for API failures
- Visual progress indicators for VRAM usage

## Caddyfile Routing Fix

When adding GPU API routing, use `handle` instead of `handle_path` for `/api/gpu/*`:
```
handle /api/gpu/* {
    reverse_proxy status-api:8000
}
```

Using `handle_path` causes 404 errors because it strips the path prefix before proxying.
