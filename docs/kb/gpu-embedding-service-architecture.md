---
category: operations
---

# Architecture

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

