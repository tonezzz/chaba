---
title: Health Check Dashboard
description: Real-time system health monitoring dashboard with GPU, Yomi, and service status tabs with auto-refresh and category-based filtering
tags: [monitoring, health-check, gpu, yomi, dashboard, services, cpu-frequency]
created: 2026-08-01
updated: 2026-08-12
category: operations
related: [ssot.health.yml, ssot.health.home.yml, ssot.health.mobile.yml, gpu-embedding-service.md, ssot.mysystem.home.yml]
search_keywords: [health monitoring, service status, GPU tab, Yomi API, dashboard, auto-refresh, troubleshooting, cpu frequency, throttling, cpu governor]
---

# Health Check Dashboard
## What it is

title: Health Check Dashboard


**Abstract**: Real-time system health monitoring dashboard providing unified view of service status, GPU metrics, and Yomi API health with auto-refresh, category-based filtering, and location-specific configuration support.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Overview

Real-time system health monitoring dashboard served from `http://tony-omen.local:8080/apps/health-check/` (home) or `http://localhost:8080/apps/health-check/` (mobile).

## Purpose

Provides unified real-time monitoring of all Chaba infrastructure services with category-based filtering, automatic location detection, and comprehensive troubleshooting guidance for service failures.

## Key files

| File | Purpose |
|------|---------|
| `chaba/stacks/web/public/apps/health-check/index.html` | Main dashboard HTML with tab navigation |
| `chaba/stacks/web/public/apps/health-check/health-check.js` | Dashboard logic, health checks, tab switching |
| `chaba/stacks/web/public/apps/health-check/health-check.css` | Dashboard styling |
| `chaba/docs/ssot/infrastructure/ssot.health.yml` | Service definitions and recovery actions |
| `chaba/docs/ssot/infrastructure/ssot.health.home.yml` | Home location-specific config |
| `chaba/docs/ssot/infrastructure/ssot.health.mobile.yml` | Mobile location-specific config |

## Tabs

### Services Tab
- Overall system status summary
- Individual service health checks (HTTP, container, local)
- Category filtering (web, api, datastore, gpu, queue, optional, system)
- Recovery actions for common failure modes
- Auto-refresh support (30s interval)

### System Services Category (August 11, 2026)

**New Category Added:**
- **Purpose**: Monitor workstation-level services like Barrier client and cron jobs
- **Check Type**: Local process monitoring using `ps -ef | grep <process> | grep -v grep`
- **Services Monitored**:
  - **Barrier Client**: Input sharing between tony-omen and tony-dell workstations
    - Binary: `~/.local/bin/barrierc` (`/usr/bin/barrierc` not installed)
    - Startup: `nohup "$HOME/.local/bin/barrierc" --no-daemon --disable-crypto --name tony-dell --log /tmp/barrier-client.log 100.75.102.88 >/dev/null 2>&1 &`
    - Autostart: `~/.config/autostart/barrierc.desktop` (or `health-monitor.sh` every 10 min)
    - Health check: `ps -ef | grep barrierc` and `tail -n 5 /tmp/barrier-client.log` should contain `connected to server`
    - Autofix: `pkill -x barrierc; nohup "$HOME/.local/bin/barrierc" ... 100.75.102.88 >/dev/null 2>&1 &`
  - **Barrier Server**: Barrier KVM server on tony-omen
    - Systemd: `systemctl --user status barriers.service`
    - Log: `/tmp/barrier-server.log`
    - Autofix: `systemctl --user restart barriers.service`
  - **Screen Timeout Cron**: Power management automation
    - Check: `crontab -l | grep screen-timeout`
    - Scripts: `/home/tony/scripts/screen-timeout-night.sh`, `/home/tony/scripts/screen-timeout-day.sh`

**Configuration:**
- SSOT: `docs/ssot/infrastructure/ssot.health.yml` (server, `barrier-server`), `docs/ssot/ssot.mysystem.home.yml` (client commands), `docs/overview/hosts.tony-dell.yml` (client)
- Workflow: `workflows/monitoring/home-profile-health-check.yml`
- Recovery commands provided in health check output

### CPU Frequency Monitoring (August 12, 2026)

**New Monitoring Capability:**
- **Purpose**: Detect CPU throttling and performance limitations due to thermal/power constraints
- **Implementation**: Enhanced `scripts/health-monitor.sh` with CPU frequency monitoring
- **Monitoring Script**: Runs every 10 minutes via `chaba-health-monitor.timer` systemd service

**CPU Specifications (tony-omen):**
- **Model**: Intel Core i7-9750H
- **Max Frequency**: 2.60GHz (2600 MHz)
- **Min Frequency**: 800 MHz
- **Cores/Threads**: 6 cores / 12 threads
- **Documented in**: `docs/ssot/ssot.mysystem.home.yml`

**Monitoring Capabilities:**
- **Current Frequency**: Reads from `/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq`
- **Max Frequency**: Reads from `/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq`
- **Throttling Detection**: Alerts when CPU <80% of max frequency under load (>50% CPU load)
- **Minimum Frequency Detection**: Alerts when CPU stuck at min frequency under load
- **Governor Monitoring**: Checks CPU governor state (powersave, performance, etc.)

**Alert Conditions:**
- **CPU Throttling**: CPU frequency <80% of max under high load
- **CPU Frequency Low**: CPU stuck at minimum frequency under load
- **CPU Governor**: Using powersave/conservative governor (may limit performance)

**Recovery Actions:**
- Check thermal throttling: `watch -n 1 'cat /sys/class/thermal/thermal_zone*/temp'`
- Check CPU temperature: `sensors` or thermal zone files
- Change CPU governor: `echo performance | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
- Check cooling: clean fans, verify airflow, check thermal paste
- Review system load: `htop` or `top` to identify CPU-intensive processes

**Verification Commands:**
- Check current frequency: `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq`
- Check max frequency: `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq`
- Check CPU governor: `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
- Monitor log: `tail -f /home/tony/CascadeProjects/chaba/logs/health-monitor.log`

**Configuration:**
- SSOT: `docs/ssot/infrastructure/ssot.health.yml` (chaba-health-monitor-timer)
- Script: `scripts/health-monitor.sh`
- Log: `logs/health-monitor.log`
- Systemd timer: `chaba-health-monitor.timer` (every 10 minutes)

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
- **Config**: `docs/ssot/infrastructure/ssot.health.home.yml`

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
- `docs/ssot/infrastructure/ssot.health.home.yml` - Changed Txt2Vid from container check to HTTP check
- `docs/ssot/infrastructure/ssot.health.yml` - Changed Txt2Vid from container check to HTTP check

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

## Related Documentation

- **SSOT Health Configuration**: `docs/ssot/infrastructure/ssot.health.yml` - Service definitions and recovery actions
- **GPU Embedding Service**: `docs/kb/gpu-embedding-service.md` - GPU service integration and monitoring
- **System Automation**: `docs/kb/system-automation.md` - Automated monitoring and maintenance scripts
- **SSOT GPU Configuration**: `docs/ssot/infrastructure/ssot.gpu.yml` - GPU policy and queue implementation

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-01 | Initial creation | tony |
| 2026-08-03 | GPU service health checks, Txt2Vid migration | tony |
| 2026-08-03 | Enhanced GPU queue monitoring with job type breakdown | tony |
| 2026-08-06 | Added frontmatter metadata, standardized structure | devin |

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
