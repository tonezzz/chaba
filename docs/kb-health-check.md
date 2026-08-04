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
- GPU service health (Imagen2, Thai Legal, Txt2Vid)
- GPU queue job status (pending, running, completed, failed, cancelled)
- Currently running job details with duration
- Job type breakdown by status
- Recent job history (last 5 jobs)
- Priority distribution for pending jobs
- Quick links to GPU Queue UI and Netdata Dashboard

### GPU Service Health Checks (August 3, 2026)

**Individual Service Monitoring:**
- **Imagen2**: HTTP health check on port 8000 (`http://tony-omen.local:8000/health`)
- **Thai Legal LLM**: HTTP health check on port 8001 (`http://tony-omen.local:8001/health`)
- **Txt2Vid**: HTTP health check on port 8002 (`http://tony-omen.local:8002/health`)

**Health Check Configuration:**
- **Type**: HTTP endpoint checks
- **Expected Status**: 200
- **Timeout**: 10 seconds
- **Category**: GPU services
- **Config**: `docs/overview/ssot.health.home.yml`

**Service Status Display:**
- Individual health indicators for each GPU service
- Model information when available
- Response time tracking
- Error message display on failures

**Txt2Vid Migration:**
- Changed from container health check to HTTP health check
- More accurate service availability detection
- Better integration with service-specific health endpoints

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
- `/api/health` - Full system health check (updated from `/api/status`)
- `/api/status` - Full system status (system, host, git, containers, frigate, cameras, gpu)
- `/api/gpu/status` - GPU status (VRAM, utilization, temperature, processes)
- `/api/container/{name}` - Single container health
- `/api/turbo` - CPU turbo boost control

### Health Check Configuration Updates (August 2026)

**API Endpoint Changes:**
- Primary health check endpoint changed from `/api/status` to `/api/health`
- `/api/health` provides service health status only
- `/api/status` provides full system status including hardware metrics
- Both endpoints remain available for different use cases

**New Yomi Health Endpoints:**
- `/api/yomi/health` - Yomi API health check
- `/api/yomi/conversations` - Conversation list endpoint (used for health monitoring)
- `/api/yomi/summarization-status` - Summarization service health
- `/api/yomi/rate-limiter-status` - Rate limiter and circuit breaker status

**Location Detection Updates:**
- Home: `http://tony-dell.local:8080/api/health` or `http://tony-omen.local:8080/api/health`
- Mobile: Fallback if home endpoints unreachable
- Both `/api/health` and `/api/status` supported for backward compatibility

### Yomi API (yomi-api service)
- `/api/yomi/health` - Yomi API health check
- `/api/yomi/conversations` - Conversation list
- `/api/yomi/last-updated` - Last data update timestamp
- `/api/yomi/summarization-status` - Summarization statistics

### GPU Queue API (gpu-queue service)
- `/api/gpu-queue/status` - Queue status, running job, job type breakdown, recent jobs, priority distribution
- `/api/gpu-queue/jobs` - Job list and submission
- `/api/gpu-queue/jobs/{id}` - Individual job status
- `/health` - Service health check

### Enhanced GPU Queue Monitoring (August 3, 2026)

**Job Type Breakdown:**
- Shows jobs by type (imagen2, txt2vid, embedding, llama, yomi_summary, yomi_daily)
- Status counts per job type (pending, running, completed, failed, cancelled)
- Helps identify which workloads are generating errors or delays

**Recent Job History:**
- Displays last 5 completed/failed/cancelled jobs
- Includes job ID, type, status, timestamps
- Shows error messages for failed jobs
- Helps identify patterns in job failures

**Priority Distribution:**
- Shows pending jobs by priority level (P1-P4)
- Priority mapping:
  - P4: embedding, yomi_summary, yomi_daily (highest)
  - P3: txt2vid, cogvideo
  - P2: imagen2
  - P1: llama (lowest)
- Helps understand queue backlog and scheduling

**Cancelled Job Tracking:**
- Added cancelled status to queue status display
- Tracks jobs that were manually cancelled
- Helps identify abandoned or unnecessary workloads

**Job Duration Display:**
- Shows how long running jobs have been executing
- Helps detect stuck or hung jobs
- Displays time since job started
- Alert threshold: jobs running > 1 hour

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

1. **mcp-gpu** (via status-api `/api/gpu/status` and `/api/status`):
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

## GPU Status Integration (August 2026)

**File modified:** `chaba-omen/stacks/web/status-api/main.py`

The GPU status endpoint `/api/gpu/status` was integrated into the main `/api/status` endpoint to provide a unified system status response.

**Changes made:**
- Added `gpu_status()` call to the `/api/status` endpoint response (line 403 in main.py)
- GPU metrics now available in both `/api/gpu/status` (dedicated endpoint) and `/api/status` (unified endpoint)
- Real-time GPU data includes: memory (total/used/free), utilization percentage, temperature, and running processes with PID and memory usage

**Implementation details:**
- `gpu_status()` function (lines 440-512) uses nvidia-smi via docker python library
- Executes nvidia-smi commands inside the `thai-legal-inference` container which has GPU access
- Returns GPU hardware info and running processes with error handling
- Process names are resolved from host using psutil.Process(pid).name()

**Health check verification:**
- Confirmed 12/13 services operational (only Frigate optional service offline)
- Frigate confirmed as properly stopped (exited 12 days ago) and remains as optional on-demand service
- GPU metrics successfully returned in `/api/status` response

## Caddyfile Routing Fix

When adding GPU API routing, use `handle` instead of `handle_path` for `/api/gpu/*`:
```
handle /api/gpu/* {
    reverse_proxy status-api:8000
}
```

Using `handle_path` causes 404 errors because it strips the path prefix before proxying.

## GPU Tab Enhancements (August 3, 2026)

**Enhanced GPU tab with comprehensive status displays:**

### New Features Added:
1. **GPU Service Health** - Individual health checks for Imagen2 (port 8000), Thai Legal LLM (port 8001), and Txt2Vid (port 8002) with model information
2. **Cancelled Count** - Added cancelled jobs to queue status display (was missing)
3. **Job Duration** - Shows how long running jobs have been executing (helps detect stuck jobs)
4. **Job Type Breakdown** - Shows jobs by type (imagen2, txt2vid, embedding, llama) with status counts
5. **Recent Job History** - Displays last 5 completed/failed/cancelled jobs with timestamps
6. **Priority Distribution** - Shows pending jobs by priority level (P4=embedding, P3=txt2vid, P2=imagen2, P1=llama)

### Files Modified:
- `scripts/gpu-queue/db.mjs` - Added `getJobTypeBreakdown()`, `getRecentJobs()`, `getPriorityDistribution()` functions
- `scripts/gpu-queue/index.mjs` - Enhanced `/api/gpu-queue/status` endpoint to return new data
- `stacks/web/public/apps/health-check/health-check.js` - Enhanced GPU tab rendering with new displays
- `stacks/web/public/apps/health-check/health-check.css` - Added 240+ lines of new styling
- `docs/overview/ssot.health.home.yml` - Changed Txt2Vid from container check to HTTP check
- `docs/overview/ssot.health.yml` - Changed Txt2Vid from container check to HTTP check

### GPU Queue API Response Structure:
```json
{
  "status": {
    "pending": 0,
    "running": 0,
    "completed": 4,
    "failed": 1,
    "cancelled": 1
  },
  "running": null,
  "jobTypeBreakdown": {
    "imagen2": {
      "completed": 3,
      "failed": 1,
      "cancelled": 1
    },
    "txt2vid": {
      "completed": 1
    }
  },
  "recentJobs": [
    {
      "id": 17,
      "type": "imagen2",
      "status": "failed",
      "created_at": "2026-07-31T10:58:30.800Z",
      "started_at": "2026-07-31T10:58:30.803Z",
      "completed_at": "2026-08-03T13:02:20.793Z",
      "error": "Job stuck in running state for 3+ days - manually failed"
    }
  ],
  "priorityDistribution": {}
}
```

### Stuck Job Resolution:
- Fixed stuck job ID 17 that was in "running" status for 3+ days (July 31 - Aug 3)
- Manually failed the job and set completed_at timestamp
- Removed 12 pending jobs to clean up the queue
- Job duration display now helps detect similar stuck jobs in the future

### GPU Queue Priority Levels:
- P4: embedding, yomi_summary, yomi_daily (highest priority)
- P3: txt2vid, cogvideo
- P2: imagen2
- P1: llama (lowest priority)

---

## Tags

- **health-check**: Real-time system health monitoring dashboard
- **gpu-monitoring**: GPU hardware status, queue monitoring, service health
- **yomi-monitoring**: Yomi API health, summarization status, rate limiter status
- **location-detection**: Auto-detection of home vs mobile network
- **api-endpoints**: Status API, Yomi API, GPU Queue API
- **caddy-routing**: Reverse proxy configuration for API routing
- **troubleshooting**: Common issues and resolution steps
- **gpu-services**: Imagen2, Thai Legal LLM, Txt2Vid health monitoring
- **queue-monitoring**: Job type breakdown, recent jobs, priority distribution
