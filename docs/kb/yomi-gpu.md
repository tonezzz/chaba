---
category: operations
---

# GPU Queue Integration (2026-08-04)

### Overview

Yomi integrates with the GPU queue system for managed GPU workload scheduling:

**Job Types:**
- `yomi_summary`: Individual conversation summarization
- `yomi_daily`: Daily summary generation
- Priority level: 2 (medium-high priority)

### Integration Module

**File:** `scripts/yomi/gpu-queue-integration.mjs`

**Functions:**
- `submitSummaryJob(chatId, prompt, type)`: Submit summary job to queue
- `submitDailySummaryJob(chatId, date, prompt, type)`: Submit daily summary job
- `submitBatchDailySummaryJob(chatId, dates, prompt, type)`: Submit batch daily summary job
- `getJob(jobId)`: Check job status
- `updateJobStatus(jobId, status, error)`: Update job completion

### Job Parameters

**Summary Job:**
```json
{
  "chatId": "c123",
  "prompt": "Summarize conversation...",
  "type": "yomi_summary",
  "model": "Phi-3-mini-4k-instruct-q4",
  "maxTokens": 150,
  "temperature": 0.3
}
```

**Daily Summary Job:**
```json
{
  "chatId": "c123",
  "date": "2026-08-01",
  "prompt": "Extract daily summary...",
  "type": "yomi_daily",
  "model": "Phi-3-mini-4k-instruct-q4",
  "maxTokens": 300,
  "temperature": 0.3
}
```

**Batch Daily Summary Job:**
```json
{
  "chatId": "c123",
  "dates": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"],
  "prompt": "Extract batch daily summaries...",
  "type": "batch_daily_summary",
  "model": "Phi-3-mini-4k-instruct-q4",
  "maxTokens": 600,
  "temperature": 0.3
}
```

### Priority Levels

**GPU Queue Priority Mapping:**
- P4: embedding, yomi_summary, yomi_daily (highest priority)
- P3: txt2vid, cogvideo
- P2: imagen2
- P1: llama (lowest priority)

**Rationale:**
- Yomi workloads are high priority for user-facing features
- Embedding jobs are critical for search functionality
- Image/video generation is lower priority (background work)

### Database Functions

**File:** `scripts/gpu-queue/db.mjs`

**Yomi-Specific Functions:**
- `getJobTypeBreakdown()`: Returns job counts by type and status
- `getRecentJobs(limit)`: Returns recent completed/failed/cancelled jobs
- `getPriorityDistribution()`: Returns pending jobs by priority level

**Job Type Breakdown Response:**
```json
{
  "yomi_summary": {
    "completed": 10,
    "failed": 1,
    "running": 2
  },
  "yomi_daily": {
    "completed": 5,
    "failed": 0,
    "running": 1
  }
}
```

### Integration Benefits

**GPU Load Management:**
- Centralized queue prevents GPU overload
- Priority-based scheduling ensures critical work completes first
- Fair sharing across all GPU workloads

**Monitoring:**
- Job status tracking in health check dashboard
- Historical job data for performance analysis
- Error tracking and retry logic

**Scalability:**
- Easy to add new Yomi job types
- Configurable priority levels
- Support for batch and single jobs

### Current Status

**Implementation Phase:** Ready for integration
- GPU queue integration module created
- Job submission functions implemented
- Database functions for job tracking available
- Priority levels configured

**Next Steps:**
- Replace direct Llama API calls with GPU queue submissions
- Update process-conversations.mjs to use queue
- Add job status polling for completion
- Implement fallback to direct API on queue failures

### Performance Optimizations (2026-08-04)
- **Batch Processing**: Process 4 dates per API call to reduce Llama API calls by 60-75%
- **Selective Processing**: Only generate daily summaries for last 30 days (reduces processing load by 40-60%)
- **Conversation Prioritization**: One-on-one conversations first, then recent (last 30 days), then older
- **Parallel Processing**: Process 3 conversations simultaneously for daily summaries
- **Extended Window**: Processing timer increased from 5min to 10min for more complete cycles
- **GPU Queue Integration**: Ready for integration with existing GPU queue system (priority 2 for Yomi workloads)

