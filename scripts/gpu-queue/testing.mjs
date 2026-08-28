/**
 * Comparative Testing Framework
 * 
 * Runs controlled tests across different GPU sharing approaches
 * to collect performance data for decision making
 */

import * as db from './db.mjs';
import * as scheduler from './scheduler.mjs';
import * as monitor from './monitor.mjs';

let mcpGpu = null;

export function setGpuClient(gpuClient) {
  mcpGpu = gpuClient;
}

/**
 * Test configuration
 */
const TEST_CONFIG = {
  iterations: 5,
  warmupIterations: 2,
  sampleTexts: [
    "GPU queue management system for efficient resource allocation",
    "Semantic search using vector embeddings for document retrieval",
    "Thai legal document processing with multilingual support",
    "Real-time video generation with LTX-Video model",
    "Image generation using SDXL-Lightning for fast inference"
  ]
};

/**
 * Run comparative test suite
 */
export async function runComparativeTestSuite() {
  console.log('Starting comparative test suite...');
  
  const results = {
    timestamp: Date.now(),
    tests: {}
  };

  // Test 1: CPU vs GPU embeddings
  console.log('\n=== Test 1: CPU vs GPU Embeddings ===');
  results.tests.embeddings = await testEmbeddingComparison();

  // Test 2: Scheduling algorithms
  console.log('\n=== Test 2: Scheduling Algorithms ===');
  results.tests.scheduling = await testSchedulingAlgorithms();

  // Test 3: Batch size optimization
  console.log('\n=== Test 3: Batch Size Optimization ===');
  results.tests.batching = await testBatchOptimization();

  // Test 4: Load testing
  console.log('\n=== Test 4: Load Testing ===');
  results.tests.load = await testLoadScenarios();

  // Save results
  await saveTestResults(results);
  
  console.log('\n=== Test Suite Complete ===');
  return results;
}

/**
 * Test 1: CPU vs GPU embeddings
 */
async function testEmbeddingComparison() {
  const results = {
    cpu: [],
    gpu: []
  };

  for (let i = 0; i < TEST_CONFIG.iterations; i++) {
    // Test CPU embeddings
    const cpuStart = Date.now();
    await submitEmbeddingJob('cpu');
    const cpuTime = await waitForJobCompletion();
    results.cpu.push(cpuTime);

    // Test GPU embeddings
    const gpuStart = Date.now();
    await submitEmbeddingJob('gpu');
    const gpuTime = await waitForJobCompletion();
    results.gpu.push(gpuTime);

    console.log(`Iteration ${i + 1}: CPU=${cpuTime}ms, GPU=${gpuTime}ms`);
  }

  return {
    cpu_avg: average(results.cpu),
    gpu_avg: average(results.gpu),
    speedup: average(results.cpu) / average(results.gpu),
    raw_data: results
  };
}

/**
 * Test 2: Scheduling algorithms
 */
async function testSchedulingAlgorithms() {
  const algorithms = ['priority', 'sjf', 'rr', 'adaptive'];
  const results = {};

  for (const algo of algorithms) {
    console.log(`Testing ${algo} scheduler...`);
    scheduler.setScheduler(algo);
    
    // Submit mixed workload
    await submitMixedWorkload(10);
    
    // Measure performance
    const startTime = Date.now();
    await waitForQueueCompletion();
    const totalTime = Date.now() - startTime;
    
    results[algo] = {
      total_time: totalTime,
      avg_job_time: totalTime / 10,
      scheduler_stats: await scheduler.getSchedulerStats()
    };
    
    console.log(`${algo}: ${totalTime}ms total`);
  }

  // Reset to default
  scheduler.setScheduler('priority');
  
  return results;
}

/**
 * Test 3: Batch size optimization
 */
async function testBatchOptimization() {
  const batchSizes = [1, 8, 16, 32, 64];
  const results = {};

  for (const batchSize of batchSizes) {
    console.log(`Testing batch size ${batchSize}...`);
    
    const startTime = Date.now();
    await submitBatchEmbeddingJob(batchSize);
    const totalTime = Date.now() - startTime;
    
    results[batchSize] = {
      total_time: totalTime,
      per_item_time: totalTime / batchSize,
      efficiency: batchSize / totalTime * 1000
    };
    
    console.log(`Batch ${batchSize}: ${totalTime}ms (${(totalTime/batchSize).toFixed(2)}ms per item)`);
  }

  return results;
}

/**
 * Test 4: Load scenarios
 */
async function testLoadScenarios() {
  const scenarios = [
    { name: 'light', concurrency: 2, duration: 30000 },
    { name: 'medium', concurrency: 5, duration: 60000 },
    { name: 'heavy', concurrency: 10, duration: 120000 }
  ];

  const results = {};

  for (const scenario of scenarios) {
    console.log(`Testing ${scenario.name} load (${scenario.concurrency} concurrent)...`);
    
    const startTime = Date.now();
    const gpuMetricsBefore = await monitor.collectGPUMetrics();
    
    // Submit concurrent jobs
    const jobIds = [];
    for (let i = 0; i < scenario.concurrency; i++) {
      const job = await submitEmbeddingJob('cpu');
      jobIds.push(job.id);
    }
    
    // Wait for completion
    await waitForJobsCompletion(jobIds);
    
    const totalTime = Date.now() - startTime;
    const gpuMetricsAfter = await monitor.collectGPUMetrics();
    
    results[scenario.name] = {
      concurrency: scenario.concurrency,
      total_time: totalTime,
      avg_time_per_job: totalTime / scenario.concurrency,
      gpu_delta: {
        vram_before: gpuMetricsBefore?.vram_used_mb || 0,
        vram_after: gpuMetricsAfter?.vram_used_mb || 0,
        vram_peak: gpuMetricsAfter?.vram_used_mb || 0
      }
    };
    
    console.log(`${scenario.name}: ${totalTime}ms total`);
  }

  return results;
}

/**
 * Helper: Submit embedding job
 */
async function submitEmbeddingJob(mode) {
  const params = {
    texts: TEST_CONFIG.sampleTexts,
    mode: mode,
    batch_size: TEST_CONFIG.sampleTexts.length
  };
  
  return await db.createJob('embedding', params);
}

/**
 * Helper: Submit batch embedding job
 */
async function submitBatchEmbeddingJob(batchSize) {
  const texts = Array(batchSize).fill(TEST_CONFIG.sampleTexts[0]);
  const params = {
    texts: texts,
    mode: 'cpu',
    batch_size: batchSize
  };
  
  return await db.createJob('embedding', params);
}

/**
 * Helper: Submit mixed workload
 */
async function submitMixedWorkload(count) {
  const types = ['embedding', 'imagen2', 'llama'];
  
  for (let i = 0; i < count; i++) {
    const type = types[i % types.length];
    const params = getTestParams(type);
    await db.createJob(type, params);
  }
}

/**
 * Helper: Get test parameters for job type
 */
function getTestParams(type) {
  switch (type) {
    case 'embedding':
      return {
        texts: [TEST_CONFIG.sampleTexts[0]],
        mode: 'cpu',
        batch_size: 1
      };
    case 'imagen2':
      return {
        prompt: "Test prompt for imagen2",
        width: 512,
        height: 512,
        steps: 4
      };
    case 'llama':
      return {
        prompt: "Test prompt for llama",
        max_tokens: 100,
        temperature: 0.7
      };
    default:
      return {};
  }
}

/**
 * Helper: Wait for job completion
 */
async function waitForJobCompletion() {
  // Simple polling - in production would use websockets or events
  while (true) {
    const runningJob = await db.getRunningJob();
    if (!runningJob) break;
    await sleep(1000);
  }
  return 0; // Would return actual time in production
}

/**
 * Helper: Wait for queue completion
 */
async function waitForQueueCompletion() {
  while (true) {
    const pendingJobs = await db.listJobs('pending');
    const runningJob = await db.getRunningJob();
    if (pendingJobs.length === 0 && !runningJob) break;
    await sleep(1000);
  }
}

/**
 * Helper: Wait for specific jobs completion
 */
async function waitForJobsCompletion(jobIds) {
  while (true) {
    const jobs = await Promise.all(jobIds.map(id => db.getJob(id)));
    const allComplete = jobs.every(job => 
      job.status === 'completed' || job.status === 'failed'
    );
    if (allComplete) break;
    await sleep(1000);
  }
}

/**
 * Helper: Calculate average
 */
function average(arr) {
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

/**
 * Helper: Sleep
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Save test results to database
 */
async function saveTestResults(results) {
  try {
    await db.pool.query(`
      INSERT INTO test_results (timestamp, results, test_type)
      VALUES ($1, $2, $3)
    `, [
      new Date(results.timestamp),
      JSON.stringify(results),
      'comparative'
    ]);
    console.log('Test results saved to database');
  } catch (error) {
    console.error('Failed to save test results:', error);
  }
}

/**
 * Get historical test results
 */
export async function getTestResults(limit = 10) {
  try {
    const result = await db.pool.query(`
      SELECT * FROM test_results
      ORDER BY timestamp DESC
      LIMIT $1
    `, [limit]);
    return result.rows;
  } catch (error) {
    console.error('Failed to get test results:', error);
    return [];
  }
}

/**
 * Create test results table
 */
export async function createTestResultsTable() {
  try {
    await db.pool.query(`
      CREATE TABLE IF NOT EXISTS test_results (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        results JSONB NOT NULL,
        test_type VARCHAR(50) NOT NULL
      )
    `);

    await db.pool.query(`
      CREATE INDEX IF NOT EXISTS idx_test_results_timestamp 
      ON test_results(timestamp DESC)
    `);

    await db.pool.query(`
      CREATE INDEX IF NOT EXISTS idx_test_results_type 
      ON test_results(test_type)
    `);

    console.log('Test results table ready');
  } catch (error) {
    console.error('Failed to create test results table:', error);
  }
}
