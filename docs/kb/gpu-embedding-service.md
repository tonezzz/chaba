# GPU Embedding Service

## What it is

GPU-accelerated text embedding service using sentence-transformers for high-performance vector generation. Achieves 34x performance improvement over CPU baseline by leveraging CUDA acceleration for embedding operations.

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
- **Efficiency**: Demonstrates efficient GPU utilization for batch processing with per-text cost reduction from 175ms to ~62-68ms

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
- **Database**: Enhanced schema with embedding-specific fields (execution_time_ms, gpu_used, vram_used_mb, mode, batch_size, queue_wait_time_ms, result)
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
| `docs/assessments/gpu-embedding/gpu-embedding-success-report.md` | Comprehensive success report |
| `docs/assessments/gpu-embedding/gpu-sharing-analysis.md` | GPU sharing analysis and optimization recommendations |

## Deployment

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

## Docker Build Lessons

### Challenges Encountered
1. **PyTorch/NumPy Compatibility**: NumPy 2.x incompatibility with PyTorch
2. **CUDA Base Images**: Issues with official CUDA base images
3. **Pip Dependency Resolution**: sentence-transformers 2.7.0 dependency conflicts
4. **Build Complexity**: Extended build times and complex dependency trees
5. **PyTorch Version Compatibility**: PyTorch 2.1.0 incompatible with transformers 4.57.6
6. **API Method Changes**: sentence-transformers API method name changes

### Successful Approach
- **Pre-built Images**: Use gperdrizet/llms-gpu:latest (pre-configured with PyTorch and CUDA)
- **Direct Deployment**: Run service directly without Docker containerization
- **Dependency Management**: NumPy version compatibility is critical for PyTorch
- **PyTorch Version**: Use torch 2.0.1+cu118 for compatibility with transformers 4.35.0
- **Transformers Version**: Use transformers 4.35.0 for compatibility with PyTorch 2.0.1
- **API Method**: Use get_sentence_embedding_dimension() instead of get_embedding_dimension()

### Dockerfile Configuration (Alternative Approach)
For containerized deployment, use this configuration:
```dockerfile
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

# Install Python
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install wheel first
RUN pip3 install --upgrade pip setuptools wheel

# Install GPU PyTorch first (compatible version)
RUN pip3 install --no-cache-dir torch==2.0.1+cu118 -f https://download.pytorch.org/whl/torch_stable.html

# Verify PyTorch installation
RUN python3 -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')"

# Install other dependencies (compatible transformers version)
COPY requirements.txt .
RUN pip3 install --no-cache-dir flask==3.0.0 sentence-transformers==2.7.0 transformers==4.35.0

# Copy GPU service
COPY embedding-service-gpu.py embedding-service.py

# Expose port
EXPOSE 5000

# Run service
CMD ["python3", "embedding-service.py"]
```

### Key Insights
- Pre-configured GPU images save significant build time
- Direct deployment can be more efficient than complex Docker builds for GPU services
- NumPy version compatibility is critical for PyTorch environments
- PyTorch version must be compatible with transformers version
- sentence-transformers API methods may change between versions
- Use handle_path with strip_prefix for Caddyfile API routing

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
- **Technical Details**:
  - Uses existing `db.mjs` functions for data access
  - Consistent error handling with `{ok, data/error, timestamp}` response format
  - Metrics calculated from recent job history for relevance
  - No dependencies on non-existent database functions

### Batch Embedding Performance Results
- **Single Text**: 175ms per embedding
- **3 Texts Batch**: 187ms total (~62ms per text)
- **5 Texts Batch**: 340ms total (~68ms per text)
- **Efficiency**: Demonstrates efficient GPU utilization for batch processing with per-text cost reduction

## Testing Results

### Service Performance (Updated 2026-08-05)
- **Health Check**: ✅ Healthy
- **Single Embedding**: ✅ Avg 73.2ms (Min 55ms, Max 120ms)
- **Batch Processing**: ✅ Avg 68ms for 5 texts (13.6ms per text)
- **VRAM Usage**: ✅ 2822MB average
- **Queue Completion Rate**: 54.5% (12/22 embedding jobs completed)
- **Average Queue Wait**: 4275ms for completed jobs

### Monitoring System
```bash
# Health check with alerts
curl http://localhost:3001/health

# Job statistics (last 24h)
curl http://localhost:3001/api/gpu-queue/stats?hours=24

# Cancellation rate monitoring
curl http://localhost:3001/api/gpu-queue/cancellation-rate?hours=24

# Recent failures analysis
curl http://localhost:3001/api/gpu-queue/recent-failures?limit=10
```

### Automation Status
- **GPU Queue Processor**: ✅ Running as systemd service (gpu-queue-processor.service)
- **Weaviate Indexer**: ✅ Scheduled daily at 2 AM (weaviate-index.timer)
- **Error Handling**: ✅ Automatic retry with exponential backoff (3 attempts)
- **Service Health Checks**: ✅ Pre-flight validation before job execution

### Integration Testing
- **Weaviate Connection**: ✅ Working
- **Embedding Generation**: ✅ 55-120ms (GPU-accelerated)
- **Queue Processing**: ✅ Automatic with error handling
- **Monitoring Endpoints**: ✅ Operational
- **Search Quality**: ✅ Good relevance scores
- **Performance**: ✅ Consistent

## Troubleshooting

### Service Not Responding
**Check**:
```bash
ps aux | grep embedding-service
curl http://localhost:5000/health
nvidia-smi  # Check GPU status
```

### CUDA Out of Memory
**Symptoms**: Service crashes or returns errors
**Solutions**:
- Reduce batch size
- Monitor VRAM usage with `nvidia-smi`
- Check for other GPU processes
- Restart service to clear GPU memory

### Connection Issues
**Symptoms**: Weaviate cannot connect to embedding service
**Solutions**:
- Verify service is running on port 5000
- Check firewall settings
- Verify EMBEDDING_SERVICE_URL environment variable
- Test with curl: `curl http://localhost:5000/health`

### Performance Degradation
**Symptoms**: Embedding times increase significantly
**Solutions**:
- Check GPU utilization with `nvidia-smi`
- Verify CUDA device is available
- Check for other GPU-intensive processes
- Monitor VRAM usage for memory leaks

## Related Documentation

- **[GPU Embedding Success Report](../assessments/gpu-embedding/gpu-embedding-success-report.md)** - Comprehensive deployment report
- **[GPU Queue Integration](../assessments/gpu-embedding/gpu-queue-integration.md)** - GPU queue system details
- **[Weaviate Configuration](../ssot/ssot.test.weaviate.yml)** - Weaviate service configuration
- **[weaviate.md](weaviate.md)** - Weaviate vector database documentation

## Tags

- **gpu**: GPU-accelerated services
- **embeddings**: Text vector embeddings
- **sentence-transformers**: ML embedding models
- **cuda**: NVIDIA GPU computing
- **weaviate**: Vector database integration
- **performance**: High-performance computing
- **machine-learning**: ML model deployment