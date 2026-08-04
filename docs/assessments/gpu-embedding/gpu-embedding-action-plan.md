# GPU Embedding Implementation Action Plan

## Executive Summary

**Goal**: Implement GPU-accelerated text embeddings for Weaviate semantic search
**Timeline**: 4 weeks (1 month)
**Effort**: 3.5-4.5 days development + testing
**Expected Outcome**: 10x performance improvement, no API costs, local processing

## Phase 1: Foundation & Validation (Week 1)

### Objective: Validate semantic search value before GPU investment

#### Week 1, Day 1-2: OpenAI API Integration
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Working semantic search with real embeddings

**Tasks**:
- [ ] Add OpenAI API key to `/home/tony/CascadeProjects/chaba/stacks/web/.env`
  ```bash
  echo "OPENAI_API_KEY=your_key_here" >> /home/tony/CascadeProjects/chaba/stacks/web/.env
  ```
- [ ] Update `scripts/weaviate/embeddings.mjs` to use OpenAI API
- [ ] Test embedding generation with sample texts
- [ ] Update Weaviate schema for OpenAI dimensions (1536)
- [ ] Run initial document indexing
- [ ] Test search functionality with real embeddings

**Success Criteria**:
- ✅ Search returns relevant results for test queries
- ✅ Embedding generation works without errors
- ✅ At least 10 documents indexed successfully

**Dependencies**: OpenAI API key required

#### Week 1, Day 3-4: Performance Baseline
**Owner**: Developer
**Priority**: MEDIUM
**Deliverables**: Baseline performance metrics

**Tasks**:
- [ ] Measure embedding generation time (OpenAI API)
- [ ] Measure search query response time
- [ ] Document current queue behavior
- [ ] Establish baseline metrics in `ssot.test.weaviate.yml`
- [ ] Test search quality with various queries

**Success Criteria**:
- ✅ Baseline metrics documented
- ✅ Search quality validated
- ✅ Performance characteristics understood

**Dependencies**: OpenAI API integration complete

#### Week 1, Day 5: Decision Gate
**Owner**: Project Lead
**Priority**: HIGH
**Deliverables**: Go/No-Go decision for GPU implementation

**Decision Criteria**:
- Search quality improvement over keyword search?
- Performance acceptable for production use?
- Value justifies GPU implementation effort?

**If GO**: Proceed to Phase 2
**If NO-GO**: Continue with OpenAI API, revisit GPU later

---

## Phase 2: GPU Embedding Service (Week 2)

### Objective: Build GPU-accelerated embedding service

#### Week 2, Day 1-2: PyTorch GPU Setup
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: GPU-capable embedding service

**Tasks**:
- [ ] Update `scripts/embeddings/requirements.txt` for GPU PyTorch
  ```txt
  torch==2.0.1+cu118 --index-url https://download.pytorch.org/whl/cu118
  sentence-transformers==2.7.0
  flask==3.0.0
  ```
- [ ] Update `scripts/embeddings/Dockerfile` for CUDA support
  ```dockerfile
  FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04
  # Install Python and dependencies
  ```
- [ ] Add CUDA runtime to docker-compose.yml
- [ ] Test GPU detection in container
- [ ] Verify PyTorch can access GPU

**Success Criteria**:
- ✅ Container detects GPU successfully
- ✅ PyTorch CUDA operations work
- ✅ nvidia-smi shows GPU usage from container

**Dependencies**: NVIDIA Docker runtime installed

#### Week 2, Day 3: Model Loading System
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Dynamic model loading/unloading

**Tasks**:
- [ ] Implement model loading function in `embedding-service.py`
  ```python
  def load_model(model_name, device='cuda'):
      global current_model
      if current_model is None:
          current_model = SentenceTransformer(model_name)
          current_model.to(device)
  ```
- [ ] Implement model unloading function
  ```python
  def unload_model():
      global current_model
      if current_model is not None:
          del current_model
      torch.cuda.empty_cache()
  ```
- [ ] Add model caching logic (keep loaded if consecutive jobs)
- [ ] Test loading/unloading with MiniLM model
- [ ] Measure VRAM usage during load/unload

**Success Criteria**:
- ✅ Model loads on GPU successfully
- ✅ VRAM freed after unload
- ✅ Load/unload time <2 seconds

**Dependencies**: GPU PyTorch setup complete

#### Week 2, Day 4: VRAM Management
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Safe VRAM allocation system

**Tasks**:
- [ ] Add VRAM checking before model load
  ```python
  def check_vram_available(required_mb):
      import subprocess
      result = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader'], 
                          capture_output=True, text=True)
      free_mb = int(result.stdout.strip())
      return free_mb >= required_mb
  ```
- [ ] Implement fallback to CPU if insufficient VRAM
- [ ] Add VRAM monitoring during embedding generation
- [ ] Test with different VRAM scenarios
- [ ] Document VRAM requirements per model

**Success Criteria**:
- ✅ VRAM check prevents OOM errors
- ✅ CPU fallback works when GPU busy
- ✅ VRAM usage stays within limits

**Dependencies**: Model loading system complete

#### Week 2, Day 5: GPU Embedding API
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: GPU-accelerated embedding endpoints

**Tasks**:
- [ ] Update `/embed` endpoint to support GPU mode
  ```python
  @app.route('/embed', methods=['POST'])
  def embed():
      data = request.json
      use_gpu = data.get('use_gpu', True)
      texts = data.get('texts', [])
      
      if use_gpu and check_vram_available(700):
          load_model('all-MiniLM-L6-v2', 'cuda')
      else:
          load_model('all-MiniLM-L6-v2', 'cpu')
      
      embeddings = model.encode(texts)
      return jsonify({'embeddings': embeddings.tolist(), 'mode': 'gpu' if use_gpu else 'cpu'})
  ```
- [ ] Add `/model-info` endpoint with GPU status
- [ ] Add performance metrics to responses
- [ ] Test GPU vs CPU performance
- [ ] Update documentation

**Success Criteria**:
- ✅ GPU embeddings 10x faster than CPU
- ✅ API returns performance metrics
- ✅ Error handling robust

**Dependencies**: VRAM management complete

---

## Phase 3: GPU Queue Integration (Week 3)

### Objective: Integrate GPU embeddings into existing queue system

#### Week 3, Day 1: Queue Job Type
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Embedding job type in GPU queue

**Tasks**:
- [ ] Update `scripts/gpu-queue/queue.mjs` embedding processor
  ```javascript
  async function processEmbeddingJob(job) {
    const useGpu = job.params.use_gpu || true;
    
    if (useGpu) {
      await mcpGpu.callTool({ name: 'mcp1_hold_llama' });
      const results = await callEmbeddingService(job.params, 'gpu');
      await mcpGpu.callTool({ name: 'mcp1_resume_llama' });
    } else {
      const results = await callEmbeddingService(job.params, 'cpu');
    }
    
    return results;
  }
  ```
- [ ] Add embedding service client functions
- [ ] Update job parameters schema
- [ ] Test embedding job submission
- [ ] Verify queue priority (embedding: 4)

**Success Criteria**:
- ✅ Embedding jobs accepted by queue
- ✅ Jobs process with correct priority
- ✅ GPU hold/resume works

**Dependencies**: GPU embedding service complete

#### Week 3, Day 2: Service Integration
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Connected embedding service to queue

**Tasks**:
- [ ] Update docker-compose.yml for embedding service
  ```yaml
  embedding-service:
    build: ../../scripts/embeddings
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
  ```
- [ ] Add embedding service to GPU queue dependencies
- [ ] Update Caddy routing for embedding service
- [ ] Test service communication
- [ ] Verify GPU access from queue

**Success Criteria**:
- ✅ Embedding service accessible from queue
- ✅ GPU access confirmed
- ✅ Service communication works

**Dependencies**: Queue job type complete

#### Week 3, Day 3: Metrics Collection
**Owner**: Developer
**Priority**: MEDIUM
**Deliverables**: Performance metrics for GPU embeddings

**Tasks**:
- [ ] Add GPU-specific metrics to queue jobs
  ```javascript
  await db.updateJobMetrics(job.id, {
    execution_time_ms: executionTime,
    gpu_used: useGpu,
    vram_used_mb: vramDelta,
    mode: useGpu ? 'gpu' : 'cpu',
    result: results
  });
  ```
- [ ] Update monitoring for embedding jobs
- [ ] Add VRAM tracking during jobs
- [ ] Test metrics collection
- [ ] Update analytics functions

**Success Criteria**:
- ✅ GPU metrics collected accurately
- ✅ VRAM usage tracked
- ✅ Analytics functions work

**Dependencies**: Service integration complete

#### Week 3, Day 4-5: Integration Testing
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Fully integrated GPU embedding system

**Tasks**:
- [ ] Test embedding job submission
- [ ] Test GPU hold/resume during embeddings
- [ ] Test concurrent embeddings
- [ ] Test VRAM exhaustion scenarios
- [ ] Test CPU fallback
- [ ] Test queue priority ordering
- [ ] Load testing with multiple jobs
- [ ] Document integration behavior

**Success Criteria**:
- ✅ End-to-end embedding jobs work
- ✅ VRAM management robust
- ✅ Queue behavior correct
- ✅ No GPU crashes or OOM errors

**Dependencies**: Metrics collection complete

---

## Phase 4: Performance Optimization (Week 4)

### Objective: Optimize and validate GPU embedding performance

#### Week 4, Day 1: Performance Benchmarking
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Comprehensive performance data

**Tasks**:
- [ ] Benchmark CPU vs GPU embeddings
  - Test batch sizes: 1, 8, 16, 32, 64
  - Measure time per batch
  - Calculate speedup ratios
- [ ] Benchmark different models
  - MiniLM (384 dims, 700MB)
  - SEA-LION (768 dims, 1.5GB)
  - CLIP (512 dims, 800MB)
- [ ] Measure VRAM usage per model
- [ ] Document performance characteristics
- [ ] Update `gpu-embedding-gap-analysis.md`

**Success Criteria**:
- ✅ 10x speedup confirmed
- ✅ VRAM usage documented
- ✅ Model comparison complete

**Dependencies**: Integration testing complete

#### Week 4, Day 2: Model Selection
**Owner**: Developer
**Priority**: MEDIUM
**Deliverables**: Optimal model for production

**Tasks**:
- [ ] Evaluate MiniLM vs SEA-LION quality
- [ ] Test Thai language support
- [ ] Test English language support
- [ ] Evaluate embedding quality for search
- [ ] Make model selection decision
- [ ] Update configuration

**Success Criteria**:
- ✅ Model selected based on quality/performance
- ✅ Thai/English support validated
- ✅ Configuration updated

**Dependencies**: Performance benchmarking complete

#### Week 4, Day 3: Batch Optimization
**Owner**: Developer
**Priority**: MEDIUM
**Deliverables**: Optimal batch sizes

**Tasks**:
- [ ] Test optimal batch sizes for throughput
- [ ] Test optimal batch sizes for latency
- [ ] Balance between queue efficiency and response time
- [ ] Document optimal configurations
- [ ] Update queue defaults

**Success Criteria**:
- ✅ Optimal batch size identified
- ✅ Queue efficiency maximized
- ✅ Response time acceptable

**Dependencies**: Model selection complete

#### Week 4, Day 4: Production Deployment
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Production-ready GPU embedding system

**Tasks**:
- [ ] Update docker-compose.yml for production
- [ ] Add health checks
- [ ] Add monitoring
- [ ] Add logging
- [ ] Deploy to production
- [ ] Verify deployment
- [ ] Update documentation

**Success Criteria**:
- ✅ System deployed successfully
- ✅ Health checks passing
- ✅ Monitoring working
- ✅ Documentation updated

**Dependencies**: Batch optimization complete

#### Week 4, Day 5: Validation & Documentation
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Validated system with complete documentation

**Tasks**:
- [ ] Run comprehensive test suite
- [ ] Validate performance against targets
- [ ] Update `ssot.test.weaviate.yml` with final status
- [ ] Update `gpu-embedding-gap-analysis.md` with results
- [ ] Create operational runbook
- [ ] Train on troubleshooting
- [ ] Handoff to operations

**Success Criteria**:
- ✅ All tests passing
- ✅ Performance targets met
- ✅ Documentation complete
- ✅ Operations trained

**Dependencies**: Production deployment complete

---

## Risk Mitigation

### Technical Risks

#### Risk 1: VRAM Exhaustion
**Probability**: Medium
**Impact**: High
**Mitigation**:
- VRAM checking before model load
- CPU fallback when GPU busy
- Model unloading after use
- Conservative VRAM estimates

#### Risk 2: GPU Queue Conflicts
**Probability**: Medium
**Impact**: Medium
**Mitigation**:
- Priority system (embedding: 4, highest)
- Hold llama during embeddings
- Proper queue testing
- Load testing before production

#### Risk 3: Model Loading Overhead
**Probability**: Low
**Impact**: Medium
**Mitigation**:
- Model caching for consecutive jobs
- Lazy loading strategy
- Pre-load popular models
- Monitor load times

### Operational Risks

#### Risk 1: Service Complexity
**Probability**: High
**Impact**: Low
**Mitigation**:
- Clear documentation
- Monitoring and alerting
- Health checks
- Operational runbook

#### Risk 2: Docker GPU Runtime
**Probability**: Medium
**Impact**: High
**Mitigation**:
- Test GPU runtime early (Week 2, Day 1)
- Have CPU fallback ready
- Document runtime requirements
- Plan B: CPU-only service

---

## Success Criteria

### Performance Targets
- ✅ 10x speedup over CPU embeddings
- ✅ <2s for batch of 32 embeddings
- ✅ VRAM usage <1.5GB
- ✅ Queue wait time <5s (95th percentile)

### Quality Targets
- ✅ Search quality matches or exceeds OpenAI
- ✅ Thai language support functional
- ✅ No GPU crashes or OOM errors
- ✅ System stability >99%

### Operational Targets
- ✅ Health checks passing
- ✅ Monitoring and alerting working
- ✅ Documentation complete
- ✅ Operations trained

---

## Timeline Summary

| Week | Phase | Key Deliverables | Effort |
|------|-------|------------------|---------|
| 1 | Foundation | OpenAI integration, baseline metrics | 2 days |
| 2 | GPU Service | GPU embedding service, VRAM management | 3 days |
| 3 | Integration | Queue integration, testing | 3 days |
| 4 | Optimization | Performance tuning, production deployment | 3 days |

**Total Effort**: 11 days over 4 weeks
**Buffer Time**: 9 days for testing, documentation, contingencies

---

## Next Steps

### Immediate (This Week)
1. **Add OpenAI API key** to validate semantic search value
2. **Test OpenAI embeddings** with real data
3. **Make Go/No-Go decision** for GPU implementation

### If GO Decision
1. **Start Week 2**: GPU PyTorch setup
2. **Follow 4-week plan** as outlined
3. **Review progress** at weekly checkpoints

### If NO-GO Decision
1. **Continue with OpenAI API** for embeddings
2. **Revisit GPU embeddings** when volume justifies cost
3. **Monitor API costs** for future optimization

---

## Resources

### Documentation
- GPU Embedding Gap Analysis: `docs/assessments/gpu-embedding/gpu-embedding-gap-analysis.md`
- Weaviate Test SSOT: `docs/ssot/ssot.test.weaviate.yml`
- GPU Queue SSOT: `docs/ssot/infrastructure/ssot.gpu.yml`

### Code
- Embedding Service: `scripts/embeddings/embedding-service.py`
- GPU Queue: `scripts/gpu-queue/`
- Weaviate Tools: `scripts/weaviate/`

### External References
- PyTorch GPU Installation: https://pytorch.org/get-started/locally/
- Sentence Transformers: https://www.sbert.net/
- NVIDIA Docker: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/

---

## Approval Required

- [ ] Project Lead: Phase 1 Go/No-Go decision
- [ ] Infrastructure: GPU runtime availability
- [ ] Operations: Production deployment approval
- [ ] Budget: Any additional tooling costs

---

**Last Updated**: 2026-08-03
**Next Review**: End of Week 1 (Go/No-Go decision)
