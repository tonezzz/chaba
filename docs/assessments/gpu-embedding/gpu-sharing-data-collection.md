# GPU Sharing Data Collection Methodology

## Overview

This document outlines the systematic approach for collecting performance data across different GPU sharing strategies to inform optimal resource allocation decisions.

## Data Collection Goals

1. **Compare CPU vs GPU embeddings** - Performance, VRAM usage, energy efficiency
2. **Evaluate scheduling algorithms** - Priority, SJF, Round Robin, Adaptive
3. **Optimize batch processing** - Optimal batch sizes for different workloads
4. **Measure system efficiency** - Queue wait times, GPU utilization, throughput
5. **Identify bottlenecks** - VRAM constraints, CPU fallback performance, I/O limitations

## Test Scenarios

### 1. Embedding Performance Comparison

**Objective**: Compare CPU-only vs GPU-accelerated embedding generation

**Variables**:
- Mode: CPU vs GPU
- Model: all-MiniLM-L6-v2 (384 dims) vs OpenAI text-embedding-3-small (1536 dims)
- Batch sizes: 1, 8, 16, 32, 64 texts
- Text lengths: Short (<100 chars), Medium (100-500 chars), Long (>500 chars)

**Metrics Collected**:
- Execution time (ms)
- VRAM usage (MB)
- GPU utilization (%)
- Temperature (°C)
- Queue wait time (ms)
- Cost (for OpenAI)

**Success Criteria**:
- CPU embeddings: <10s per batch of 32
- GPU embeddings: <2s per batch of 32
- VRAM usage: <500MB for embeddings
- Cost: <$0.01 per 1000 embeddings (OpenAI)

### 2. Scheduling Algorithm Comparison

**Objective**: Compare different queue scheduling strategies

**Algorithms Tested**:
1. **Priority-based** (current): txt2vid > imagen2 > llama > embedding
2. **Shortest Job First (SJF)**: Optimize for average completion time
3. **Round Robin**: Fair allocation across job types
4. **Adaptive**: Dynamic based on historical performance

**Test Workloads**:
- Light: 2 concurrent jobs, 30s duration
- Medium: 5 concurrent jobs, 60s duration  
- Heavy: 10 concurrent jobs, 120s duration

**Metrics Collected**:
- Total completion time
- Average job completion time
- Average queue wait time
- GPU utilization percentage
- Job starvation (jobs waiting >60s)

**Success Criteria**:
- Adaptive scheduler: 20% improvement in avg completion time
- SJF: 15% improvement in avg wait time
- Round Robin: Fair allocation (no starvation)

### 3. Batch Size Optimization

**Objective**: Find optimal batch sizes for different workloads

**Workloads**:
- Embeddings: 1, 8, 16, 32, 64 texts
- Image generation: 1, 4, 8 images
- Video generation: 1, 2, 4 videos

**Metrics Collected**:
- Total execution time
- Per-item execution time
- VRAM usage
- Memory usage
- Error rate

**Success Criteria**:
- Find "knee" in performance curve
- Balance between throughput and latency
- VRAM usage <80% capacity

### 4. Load Testing

**Objective**: Measure system behavior under realistic load

**Scenarios**:
- **Burst load**: 10 jobs in 10s, then idle
- **Sustained load**: 2 jobs/minute for 10 minutes
- **Peak load**: 20 jobs in 30s
- **Mixed load**: Combination of all job types

**Metrics Collected**:
- Queue depth over time
- GPU utilization over time
- VRAM usage patterns
- Error rates
- System stability

**Success Criteria**:
- No queue depth >20
- GPU utilization >70% during peak
- Error rate <5%
- System remains stable

## Data Collection Process

### Phase 1: Baseline Measurement (Week 1)

1. **Current System Profiling**
   - Run existing workload for 24 hours
   - Collect baseline metrics
   - Identify current bottlenecks

2. **Instrumentation Setup**
   - Enable GPU monitoring
   - Create test results table
   - Validate data collection pipeline

### Phase 2: CPU Embeddings (Week 2)

1. **Deploy CPU Embedding Service**
   - Build and start embedding-service container
   - Validate health endpoints
   - Test with sample data

2. **Performance Testing**
   - Run embedding comparison tests
   - Collect CPU metrics
   - Document baseline CPU performance

### Phase 3: GPU Queue Integration (Week 3)

1. **Add Embeddings to Queue**
   - Update GPU queue with embedding job type
   - Set priority (embedding: 4, highest)
   - Test queue integration

2. **Comparative Testing**
   - Test CPU vs GPU embeddings through queue
   - Measure queue impact
   - Document performance differences

### Phase 4: Scheduling Optimization (Week 4)

1. **Algorithm Testing**
   - Test each scheduling algorithm
   - Collect performance metrics
   - Compare against baseline

2. **Adaptive Tuning**
   - Implement adaptive scheduler
   - Train on collected data
   - Validate improvements

### Phase 5: Load Testing (Week 5)

1. **Scenario Testing**
   - Run all load scenarios
   - Collect comprehensive metrics
   - Identify system limits

2. **Stress Testing**
   - Push system to limits
   - Document failure modes
   - Establish safe operating thresholds

## Data Analysis

### Key Performance Indicators (KPIs)

1. **Efficiency Metrics**
   - Average job completion time
   - GPU utilization percentage
   - Queue throughput (jobs/hour)
   - Resource efficiency (work/VRAM)

2. **User Experience Metrics**
   - Average queue wait time
   - 95th percentile wait time
   - Job starvation rate
   - Error rate

3. **System Health Metrics**
   - VRAM usage patterns
   - Temperature trends
   - System stability
   - Resource contention

### Analysis Methods

1. **Comparative Analysis**
   - CPU vs GPU performance
   - Scheduling algorithm comparison
   - Batch size optimization

2. **Trend Analysis**
   - Performance over time
   - Usage patterns
   - Capacity planning

3. **Correlation Analysis**
   - Queue depth vs wait time
   - VRAM usage vs performance
   - Job type vs resource usage

## Decision Framework

### Criteria for GPU Sharing Strategy Selection

1. **Performance**
   - Average completion time < target
   - 95th percentile wait time < target
   - GPU utilization >70%

2. **Efficiency**
   - Resource utilization >80%
   - Cost per job < target
   - Energy efficiency

3. **Reliability**
   - Error rate <5%
   - System stability >99%
   - No data loss

4. **User Experience**
   - Queue wait time <30s (95th percentile)
   - No job starvation
   - Predictable performance

### Decision Matrix

| Strategy | Performance | Efficiency | Reliability | UX | Overall |
|----------|-------------|------------|-------------|-----|---------|
| Current (Priority) | Baseline | Baseline | Baseline | Baseline | Baseline |
| CPU Embeddings | ? | ? | ? | ? | ? |
| GPU Embeddings | ? | ? | ? | ? | ? |
| SJF Scheduling | ? | ? | ? | ? | ? |
| Adaptive Scheduling | ? | ? | ? | ? | ? |
| Hybrid Approach | ? | ? | ? | ? | ? |

## Implementation Timeline

### Week 1: Setup and Baseline
- Deploy monitoring infrastructure
- Collect baseline metrics
- Validate data collection

### Week 2: CPU Embeddings
- Deploy CPU embedding service
- Run performance tests
- Document results

### Week 3: GPU Queue Integration
- Add embeddings to queue
- Test queue integration
- Compare CPU vs GPU

### Week 4: Scheduling Optimization
- Test scheduling algorithms
- Implement adaptive scheduler
- Validate improvements

### Week 5: Load Testing
- Run load scenarios
- Stress test system
- Document limits

### Week 6: Analysis and Decision
- Analyze all collected data
- Compare strategies
- Make final recommendation

## Data Storage

### Database Schema

**gpu_queue_jobs** (enhanced):
- Performance metrics (execution_time_ms, gpu_used, vram_used_mb)
- Mode tracking (cpu, gpu, hybrid)
- Batch optimization (batch_size)
- Queue metrics (queue_wait_time_ms)

**gpu_metrics** (new):
- Continuous GPU monitoring
- VRAM usage over time
- GPU utilization
- Temperature tracking

**test_results** (new):
- Test suite results
- Comparative test data
- Performance benchmarks

## Success Metrics

### Quantitative Goals

- **Performance**: 20% improvement in avg completion time
- **Efficiency**: 30% improvement in GPU utilization
- **User Experience**: 50% reduction in queue wait time
- **Cost**: 40% reduction in embedding costs (if applicable)

### Qualitative Goals

- Better user experience (faster responses)
- More predictable performance
- Easier capacity planning
- Clear decision framework

## Risk Mitigation

### Potential Issues

1. **Data Collection Overhead**
   - Risk: Monitoring affects performance
   - Mitigation: Lightweight monitoring, sampling

2. **Test Environment vs Production**
   - Risk: Test results don't match production
   - Mitigation: Use production-like workloads, validate with real data

3. **GPU Queue Disruption**
   - Risk: Testing affects production queue
   - Mitigation: Separate test queue, off-peak testing

4. **Insufficient Data**
   - Risk: Not enough data for conclusions
   - Mitigation: Extended testing period, statistical significance

## Conclusion

This methodology provides a systematic approach to collecting comprehensive performance data across different GPU sharing strategies. The data collected will inform evidence-based decisions about optimal GPU resource allocation for the chaba project.

## Next Steps

1. Review and approve this methodology
2. Set up monitoring infrastructure
3. Begin Phase 1 baseline measurement
4. Execute testing phases according to timeline
5. Analyze results and make recommendations
