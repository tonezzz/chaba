---
category: operations
---

# GPU Queue Integration

### Database Schema Updates
Added embedding-specific fields to `gpu_queue_jobs` table:
- `embedding_dimensions`: Embedding vector dimensions (e.g., 384)
- `embedding_model`: Model name (e.g., all-MiniLM-L6-v2)
- `text_count`: Number of texts processed
- `execution_time_ms`: Job execution time in milliseconds
- `gpu_used`: GPU device identifier
- `vram_used_mb`: VRAM usage in megabytes
- `mode`: Processing mode (single/batch)
- `batch_size`: Number of texts in batch
- `queue_wait_time_ms`: Time spent in queue before processing
- `result`: Job result status/output

### Orchestrator Functions
- **processEmbeddingJob()**: Handles embedding job processing in GPU queue
- **updateJobMetadata()**: Updates embedding-specific metrics after job completion

### Enhanced Features
- **VRAM Management**: Track GPU memory usage for embedding jobs
- **GPU Hold/Resume**: Coordinate with llama GPU hold/resume
- **Metrics Tracking**: Enhanced performance metrics for embedding operations
- **Batch Processing**: Fully operational with validated performance
- **Monitoring Integration**: GPU queue monitoring module added 2026-08-05

### GPU Queue Monitoring Module (2026-08-05)
- **Module**: `scripts/gpu-queue/monitoring.mjs`
- **Functions**:
  - `getQueueHealth()`: Queue status, running job, job type breakdown, priority distribution
  - `getPerformanceMetrics()`: Average execution time, success rate from recent jobs
  - `getRecentActivity(limit)`: Recent job history with configurable limit
  - `getSystemOverview()`: Comprehensive system overview combining all metrics
- **API Endpoints**:
  - `GET /health` - Basic health check with queue status
  - `GET /api/gpu-queue/monitoring/health` - Detailed health check
  - `GET /api/gpu-queue/monitoring/performance` - Performance metrics
  - `GET /api/gpu-queue/monitoring/activity?limit=20` - Recent activity
  - `GET /api/gpu-queue/monitoring/overview` - System overview

### GPU Queue Backpressure System (2026-08-06)
- **Module**: `scripts/gpu-queue/index.mjs`
- **Purpose**: GPU-aware queue processing with intelligent load management
- **Key Features**:
  - **GPU Monitoring**: Real-time GPU utilization tracking via Netdata API
  - **Backpressure**: Automatic throttling when GPU load exceeds 80%
  - **Job-Specific Rate Limiting**: Per-job-type concurrency limits
  - **Circuit Breaker**: Automatic protection after consecutive failures
  - **Adaptive Wait Times**: Dynamic delays based on GPU load

**GPU Monitoring:**
```javascript
// GPU status check via Netdata API
const gpuStatus = await checkGPUStatus();
// Returns: { available, memoryPercent, memoryUsed, memoryTotal }
// Threshold: GPU < 80% utilization required for processing
```

**Job-Specific Rate Limits:**
```javascript
const jobLimits = {
  yomi_summary: { maxConcurrent: 1, lastProcessed: 0 },
  yomi_daily: { maxConcurrent: 1, lastProcessed: 0 },
  yomi_daily_batch: { maxConcurrent: 1, lastProcessed: 0 },
  embedding: { maxConcurrent: 2, lastProcessed: 0 },
  imagen2: { maxConcurrent: 1, lastProcessed: 0 },
  txt2vid: { maxConcurrent: 1, lastProcessed: 0 },
  llama: { maxConcurrent: 1, lastProcessed: 0 }
};
// Minimum 3 seconds between same job types
```

**Circuit Breaker:**
```javascript
const MAX_CONSECUTIVE_FAILURES = 5;
const BACKPRESSURE_DELAY = 30000; // 30 seconds
// Triggers after 5 consecutive failures
// Resets after backpressure delay
```

**Adaptive Processing:**
```javascript
// Adaptive wait time based on GPU load
const waitTime = gpuStatus.memoryPercent > 60 ? 10000 : 5000;
// 10s wait when GPU > 60%, 5s otherwise
```

**Smart Context Management:**
```javascript
// Context length management with job-type-specific chunking
function manageContextLength(prompt, jobType = 'default') {
  const MAX_CONTEXT_LENGTH = 6000;
  // For daily summaries: prioritize recent messages
  // For regular summaries: keep most recent content
  // Smart chunking based on job type
}
```

**Request Timeouts:**
- Yomi summary: 30 seconds
- Yomi daily: 60 seconds  
- Yomi batch daily: 90 seconds
- Implemented via AbortController for reliable timeout handling

