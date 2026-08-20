---
category: operations
---

# API Endpoints

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

