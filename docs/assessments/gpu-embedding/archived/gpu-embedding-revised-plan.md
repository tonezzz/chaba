# GPU Embedding Implementation Plan (No API Key)

## Executive Summary

**Situation**: No OpenAI API key available for validation phase
**Revised Approach**: Direct GPU implementation using local models
**Timeline**: 3 weeks (skips validation phase)
**Effort**: 3-4 days development + testing
**Expected Outcome**: 10x performance improvement, no API costs, local processing

## Revised Strategy

### Original Plan vs Revised Plan

| Aspect | Original Plan | Revised Plan |
|--------|---------------|--------------|
| Phase 1 | OpenAI API validation (2 days) | **SKIP** - Go directly to GPU |
| Phase 2 | GPU embedding service (3 days) | **START HERE** - GPU service first |
| Phase 3 | Queue integration (3 days) | **SAME** - Queue integration |
| Phase 4 | Optimization (3 days) | **SAME** - Performance tuning |
| **Total** | 4 weeks, 11 days | **3 weeks, 9 days** |

### Rationale for Skipping Validation

**Pros of Direct GPU Implementation**:
- ✅ No API key dependency
- ✅ Faster time to value (skip 1 week)
- ✅ Lower long-term costs (no API fees)
- ✅ Better privacy (local processing)
- ✅ Hardware already available

**Cons**:
- ❌ No baseline comparison with OpenAI
- ❌ Higher initial development effort
- ❌ Risk of investing without proven value

**Mitigation**:
- Start with simple CPU embeddings for quick validation
- Use mock data for UI testing
- Incremental development with early testing

---

## Revised Phase 1: Quick CPU Validation (Week 1)

### Objective: Validate semantic search concept with minimal effort

#### Week 1, Day 1: Simple CPU Embeddings
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Working CPU embedding service

**Tasks**:
- [ ] Simplify `scripts/embeddings/requirements.txt` for CPU-only
  ```txt
  sentence-transformers==2.7.0
  torch==2.0.1
  flask==3.0.0
  ```
- [ ] Use simple CPU Dockerfile (no CUDA)
  ```dockerfile
  FROM python:3.11-slim
  # Install CPU-only PyTorch
  ```
- [ ] Deploy CPU embedding service
- [ ] Test with MiniLM model
- [ ] Update Weaviate search to use CPU service
- [ ] Test basic semantic search

**Success Criteria**:
- ✅ CPU embedding service running
- ✅ Basic search functionality working
- ✅ Response time <10s per query

**Dependencies**: None

#### Week 1, Day 2: Quick Search Validation
**Owner**: Developer
**Priority**: MEDIUM
**Deliverables**: Validated search quality

**Tasks**:
- [ ] Index sample SSOT documents
- [ ] Test search with various queries
- [ ] Evaluate search quality
- [ ] Make Go/No-Go decision for GPU investment

**Decision Criteria**:
- Search results relevant and useful?
- Performance acceptable for testing?
- Value justifies GPU implementation effort?

**If GO**: Proceed to GPU implementation
**If NO-GO**: Reconsider approach or use case

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
- [ ] Implement model loading function
- [ ] Implement model unloading function
- [ ] Add model caching logic
- [ ] Test with MiniLM model
- [ ] Measure VRAM usage

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
- [ ] Implement fallback to CPU if insufficient VRAM
- [ ] Add VRAM monitoring during embedding generation
- [ ] Test with different VRAM scenarios

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

## Phase 4: Performance Optimization (Week 4 - Optional)

### Objective: Optimize and validate GPU embedding performance

#### Week 4, Day 1: Performance Benchmarking
**Owner**: Developer
**Priority**: MEDIUM
**Deliverables**: Comprehensive performance data

**Tasks**:
- [ ] Benchmark CPU vs GPU embeddings
- [ ] Benchmark different models (MiniLM, SEA-LION)
- [ ] Measure VRAM usage per model
- [ ] Document performance characteristics

**Success Criteria**:
- ✅ 10x speedup confirmed
- ✅ VRAM usage documented
- ✅ Model comparison complete

**Dependencies**: Integration testing complete

#### Week 4, Day 2: Model Selection
**Owner**: Developer
**Priority**: LOW
**Deliverables**: Optimal model for production

**Tasks**:
- [ ] Evaluate MiniLM vs SEA-LION quality
- [ ] Test Thai language support
- [ ] Test English language support
- [ ] Make model selection decision

**Success Criteria**:
- ✅ Model selected based on quality/performance
- ✅ Thai/English support validated

**Dependencies**: Performance benchmarking complete

#### Week 4, Day 3: Production Deployment
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Production-ready GPU embedding system

**Tasks**:
- [ ] Update docker-compose.yml for production
- [ ] Add health checks
- [ ] Add monitoring
- [ ] Deploy to production
- [ ] Verify deployment
- [ ] Update documentation

**Success Criteria**:
- ✅ System deployed successfully
- ✅ Health checks passing
- ✅ Documentation updated

**Dependencies**: Model selection complete

#### Week 4, Day 4-5: Validation & Documentation
**Owner**: Developer
**Priority**: HIGH
**Deliverables**: Validated system with complete documentation

**Tasks**:
- [ ] Run comprehensive test suite
- [ ] Validate performance against targets
- [ ] Update SSOT files with final status
- [ ] Create operational runbook
- [ ] Update documentation

**Success Criteria**:
- ✅ All tests passing
- ✅ Performance targets met
- ✅ Documentation complete

**Dependencies**: Production deployment complete

---

## Immediate Next Steps

### Option A: Quick CPU Validation (Recommended)
1. **Deploy CPU embedding service** (Week 1, Day 1)
2. **Test basic semantic search** (Week 1, Day 2)
3. **Make Go/No-Go decision** for GPU investment

### Option B: Direct GPU Implementation
1. **Skip CPU validation**
2. **Start GPU PyTorch setup** (Week 2, Day 1)
3. **Follow 3-week GPU implementation plan**

### Option C: Continue with Mock Data
1. **Keep current mock implementation**
2. **Revisit GPU embeddings later**
3. **Focus on other priorities**

---

## Recommendation

**Recommended Approach**: Option A (Quick CPU Validation)

**Rationale**:
- Low effort (1-2 days) to validate the concept
- Reduces risk of GPU investment without proven value
- Provides baseline for GPU performance comparison
- Easy to pivot if results don't justify GPU

**If CPU validation successful**: Proceed to GPU implementation (Week 2-4)
**If CPU validation unsuccessful**: Reconsider approach or use case

---

## Updated Timeline

| Week | Phase | Key Deliverables | Effort |
|------|-------|------------------|---------|
| 1 | CPU Validation | CPU embeddings, search validation | 2 days |
| 2 | GPU Service | GPU embedding service, VRAM management | 3 days |
| 3 | Integration | Queue integration, testing | 3 days |
| 4 | Optimization | Performance tuning, deployment | 3 days |

**Total Effort**: 11 days over 4 weeks
**Critical Path**: CPU validation → GPU service → Integration → Deployment

---

## Decision Required

**Immediate Decision**: Which approach to take?

- [ ] **Option A**: Quick CPU validation (1-2 days, then decide)
- [ ] **Option B**: Direct GPU implementation (skip validation)
- [ ] **Option C**: Continue with mock data (defer decision)

**Recommendation**: Option A - Quick CPU validation to de-risk the investment

---

**Last Updated**: 2026-08-03
**Next Review**: After CPU validation (Week 1, Day 2)
