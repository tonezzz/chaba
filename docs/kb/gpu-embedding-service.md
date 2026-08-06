---
title: GPU Embedding Service
description: GPU-accelerated text embedding service using sentence-transformers for high-performance vector generation with 34x performance improvement over CPU baseline
tags: [gpu, embeddings, vector-generation, sentence-transformers, cuda, weaviate]
created: 2026-08-04
updated: 2026-08-06
category: operations
related: [ssot.test.weaviate.yml, weaviate.md, ssot.gpu.yml]
search_keywords: [GPU embeddings, vector generation, sentence-transformers, CUDA, Weaviate, performance optimization]
---

# GPU Embedding Service

**Abstract**: GPU-accelerated text embedding service using sentence-transformers for high-performance vector generation, achieving 34x performance improvement over CPU baseline through CUDA acceleration with comprehensive GPU queue integration and monitoring.

## Overview

GPU-accelerated text embedding service using sentence-transformers for high-performance vector generation. Achieves 34x performance improvement over CPU baseline by leveraging CUDA acceleration for embedding operations.

## Purpose

Provides high-performance text embedding capabilities for semantic search and vector operations, integrated with Weaviate vector database and GPU queue system for efficient resource management and monitoring.

## Performance Metrics

### Baseline Comparison
- **CPU Service**: 1.1s per embedding (all-MiniLM-L6-v2, 384 dimensions)
- **GPU Service**: 32ms per embedding (all-MiniLM-L6-v2, 384 dimensions)
- **Performance Gain**: 34x faster
- **VRAM Usage**: 2808MB
- **Model**: all-MiniLM-L6-v2 (sentence-transformers)

### Batch Embedding Performance
- **Single Text**: 175ms per embedding
- **3 Texts Batch**: 187ms total (~62ms per text)
- **5 Texts Batch**: 340ms total (~68ms per text)
- **Efficiency**: Demonstrates efficient GPU utilization for batch processing

## Architecture

### Service Configuration
- **Base Image**: gperdrizet/llms-gpu:latest
- **Device**: CUDA (NVIDIA GPU)
- **Port**: 5000
- **Model Dimensions**: 384
- **Deployment Method**: Direct Python service (non-containerized)
- **Process**: Running as root user (PID 173324)

### Integration Points
- **Weaviate**: Uses GPU service for semantic search embeddings with Chonkie chunking
- **GPU Queue**: Fully integrated with orchestrator functions (processEmbeddingJob, updateJobMetadata)
- **Database**: Enhanced schema with embedding-specific fields
- **Batch Processing**: Validated performance with efficient GPU utilization
- **Monitoring System**: Comprehensive health checks, performance metrics, error tracking via monitoring.mjs
- **Automation**: Automatic queue processor (auto-processor.mjs) and daily Weaviate indexing (systemd timers)

## Key Files

| File | Purpose |
|------|---------|
| `scripts/embeddings/embedding-service.py` | GPU embedding service implementation |
| `scripts/embeddings/embedding-service-gpu.py` | GPU-specific service configuration |
| `scripts/weaviate/embeddings.mjs` | Weaviate integration module |
| `scripts/gpu-queue/schema.sql` | Database schema with embedding fields |
| `scripts/gpu-queue/orchestrator.mjs` | GPU queue orchestrator with processEmbeddingJob() and updateJobMetadata() |
| `scripts/gpu-queue/monitoring.mjs` | Health checks and performance metrics |
| `scripts/gpu-queue/benchmark.mjs` | Performance benchmarking system |
| `scripts/gpu-queue/auto-processor.mjs` | Automatic queue processor |

## Operational Procedures

### Service Startup
```bash
cd /home/tony/CascadeProjects/chaba/scripts/embeddings
source ~/venv-embeddings/bin/activate
python embedding-service.py
```

### Health Check
```bash
curl http://localhost:5000/health
# Response: {"device":"cuda","model":"all-MiniLM-L6-v2","model_loaded":true,"status":"healthy"}
```

### Single Embedding Test
```bash
curl -X POST http://localhost:5000/embed-single \
  -H "Content-Type: application/json" \
  -d '{"text": "GPU embeddings are fast", "use_gpu": true}'
# Response: 32ms, 384 dimensions, VRAM usage 2808MB
```

### Weaviate Integration
The Weaviate embeddings module is configured to use the GPU service:
```javascript
const EMBEDDING_SERVICE_URL = process.env.EMBEDDING_SERVICE_URL || 'http://localhost:5000';
```

## GPU Queue Integration

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

## Troubleshooting

### Service Not Starting
- Check port 5000 is not in use: `lsof -i :5000`
- Verify Python virtual environment is intact
- Check CUDA is available: `nvidia-smi`
- Review service logs for errors

### Performance Issues
- Check GPU memory usage: `nvidia-smi`
- Verify CUDA device is available
- Check for other GPU processes consuming resources
- Review batch size configuration

### Integration Issues
- Verify Weaviate embeddings module configuration
- Check GPU queue database schema is updated
- Test service health endpoint independently
- Review orchestrator logs for errors

## Related Documentation

- **GPU Success Report**: `docs/assessments/gpu-embedding/archived/gpu-embedding-success-report.md` - Implementation success analysis
- **GPU Queue Schema**: `scripts/gpu-queue/schema.sql` - Database schema with embedding fields
- **Weaviate Configuration**: `docs/ssot/infrastructure/ssot.test.weaviate.yml` - Vector database setup
- **SSOT GPU Configuration**: `docs/ssot/infrastructure/ssot.gpu.yml` - GPU policy and queue implementation
- **Health Check Dashboard**: `docs/kb/health-check.md` - GPU monitoring integration

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-04 | Initial deployment | tony |
| 2026-08-05 | GPU queue monitoring integration | tony |
| 2026-08-06 | GPU queue backpressure system documentation | tony |
| 2026-08-06 | Added frontmatter metadata, standardized structure | devin |
