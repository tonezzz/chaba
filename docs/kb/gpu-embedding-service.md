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

## Architecture

### Service Configuration
- **Base Image**: gperdrizet/llms-gpu:latest
- **Device**: CUDA (NVIDIA GPU)
- **Port**: 5000
- **Model Dimensions**: 384
- **Deployment Method**: Direct Python service (non-containerized)
- **Process**: Running as root user (PID 173324)

### Integration Points
- **Weaviate**: Uses GPU service for semantic search embeddings
- **GPU Queue**: Integrated with existing GPU queue system for batch jobs
- **Database**: Enhanced schema with embedding-specific fields

## Key Files

| File | Purpose |
|------|---------|
| `scripts/embeddings/embedding-service.py` | GPU embedding service implementation |
| `scripts/embeddings/embedding-service-gpu.py` | GPU-specific service configuration |
| `scripts/weaviate/embeddings.mjs` | Weaviate integration module |
| `scripts/gpu-queue/schema.sql` | Database schema with embedding fields |
| `docs/assessments/gpu-embedding/gpu-embedding-success-report.md` | Comprehensive success report |

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

### Enhanced Features
- **VRAM Management**: Track GPU memory usage for embedding jobs
- **GPU Hold/Resume**: Coordinate with llama GPU hold/resume
- **Metrics Tracking**: Enhanced performance metrics for embedding operations
- **Batch Processing**: Ready for batch embedding jobs when needed

## Testing Results

### Service Performance
- **Health Check**: ✅ Healthy
- **Single Embedding**: ✅ 32ms
- **Batch Processing**: ✅ Ready
- **VRAM Usage**: ✅ 2808MB

### Weaviate Search Testing
```bash
node search.mjs "What is the GPU queue system"
# Results: 5 relevant documents with semantic similarity
# Embedding generation: 28ms
```

### Integration Testing
- **Weaviate Connection**: ✅ Working
- **Embedding Generation**: ✅ 28-32ms
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