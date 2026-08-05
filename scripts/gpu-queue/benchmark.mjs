#!/usr/bin/env node
import * as db from './db.mjs';
import * as queue from './queue.mjs';

/**
 * GPU Queue Performance Benchmarking
 * Comprehensive performance testing of the complete system
 */

const BENCHMARK_CONFIG = {
  embedding: {
    single_text: "GPU embedding performance test for comprehensive system validation",
    batch_texts: [
      "GPU queue system for efficient resource management",
      "Semantic search using Weaviate vector database", 
      "GPU-accelerated embeddings for faster processing",
      "Queue-based resource management system",
      "High-performance computing with CUDA acceleration"
    ],
    iterations: 5
  },
  stats: {
    hours: 24
  }
};

async function benchmarkEmbeddingService() {
  console.log('=== EMBEDDING SERVICE BENCHMARK ===\n');
  
  const results = {
    single_embeddings: [],
    batch_embeddings: [],
    service_health: null
  };

  // Test service health
  try {
    const healthResponse = await fetch('http://localhost:5000/health');
    results.service_health = await healthResponse.json();
    console.log('✓ Service Health:', JSON.stringify(results.service_health));
  } catch (error) {
    console.error('✗ Service Health Check Failed:', error.message);
    return results;
  }

  // Benchmark single embeddings
  console.log('\n--- Single Embedding Performance ---');
  for (let i = 0; i < BENCHMARK_CONFIG.embedding.iterations; i++) {
    const start = Date.now();
    const response = await fetch('http://localhost:5000/embed-single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: BENCHMARK_CONFIG.embedding.single_text, use_gpu: true })
    });
    const duration = Date.now() - start;
    const data = await response.json();
    
    results.single_embeddings.push({
      iteration: i + 1,
      duration_ms: duration,
      dimensions: data.dimensions,
      model: data.model,
      vram_usage_mb: data.vram_usage_mb
    });
    
    console.log(`  Iteration ${i + 1}: ${duration}ms (${data.dimensions} dimensions, ${data.vram_usage_mb}MB VRAM)`);
  }

  // Calculate single embedding statistics
  const singleStats = {
    avg_duration: results.single_embeddings.reduce((sum, r) => sum + r.duration_ms, 0) / results.single_embeddings.length,
    min_duration: Math.min(...results.single_embeddings.map(r => r.duration_ms)),
    max_duration: Math.max(...results.single_embeddings.map(r => r.duration_ms)),
    avg_vram: results.single_embeddings.reduce((sum, r) => sum + r.vram_usage_mb, 0) / results.single_embeddings.length
  };
  console.log(`\nSingle Embedding Stats: Avg ${singleStats.avg_duration.toFixed(1)}ms, Min ${singleStats.min_duration}ms, Max ${singleStats.max_duration}ms, Avg VRAM ${singleStats.avg_vram.toFixed(0)}MB`);

  // Benchmark batch embeddings
  console.log('\n--- Batch Embedding Performance ---');
  for (let i = 0; i < BENCHMARK_CONFIG.embedding.iterations; i++) {
    const start = Date.now();
    const response = await fetch('http://localhost:5000/embed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texts: BENCHMARK_CONFIG.embedding.batch_texts, use_gpu: true })
    });
    const duration = Date.now() - start;
    const data = await response.json();
    
    results.batch_embeddings.push({
      iteration: i + 1,
      duration_ms: duration,
      text_count: data.count,
      per_text_ms: duration / data.count,
      dimensions: data.embeddings?.[0]?.length || data.dimensions
    });
    
    console.log(`  Iteration ${i + 1}: ${duration}ms total (${results.batch_embeddings[i].per_text_ms.toFixed(1)}ms per text, ${data.count} texts)`);
  }

  // Calculate batch embedding statistics
  const batchStats = {
    avg_duration: results.batch_embeddings.reduce((sum, r) => sum + r.duration_ms, 0) / results.batch_embeddings.length,
    min_duration: Math.min(...results.batch_embeddings.map(r => r.duration_ms)),
    max_duration: Math.max(...results.batch_embeddings.map(r => r.duration_ms)),
    avg_per_text: results.batch_embeddings.reduce((sum, r) => sum + r.per_text_ms, 0) / results.batch_embeddings.length
  };
  console.log(`\nBatch Embedding Stats: Avg ${batchStats.avg_duration.toFixed(1)}ms, Min ${batchStats.min_duration}ms, Max ${batchStats.max_duration}ms, Avg per-text ${batchStats.avg_per_text.toFixed(1)}ms`);

  return {
    service: results.service_health,
    single_embeddings: singleStats,
    batch_embeddings: batchStats,
    raw_results: results
  };
}

async function benchmarkQueueSystem() {
  console.log('\n=== QUEUE SYSTEM BENCHMARK ===\n');
  
  const results = {
    job_stats: null,
    cancellation_rate: null,
    recent_failures: null
  };

  // Get job statistics
  try {
    const stats = await db.getJobStats(BENCHMARK_CONFIG.stats.hours);
    results.job_stats = stats;
    console.log('✓ Job Statistics (last 24h):');
    stats.forEach(stat => {
      if (stat.count > 0) {
        console.log(`  ${stat.type}/${stat.status}: ${stat.count} jobs (avg execution: ${stat.avg_execution_time_ms ? Math.round(stat.avg_execution_time_ms) + 'ms' : 'N/A'}, avg queue wait: ${stat.avg_queue_wait_time_ms ? Math.round(stat.avg_queue_wait_time_ms) + 'ms' : 'N/A'})`);
      }
    });
    
    // Calculate completion rate
    const totalJobs = stats.reduce((sum, s) => sum + s.count, 0);
    const completedJobs = stats.reduce((sum, s) => sum + (s.status === 'completed' ? s.count : 0), 0);
    const completionRate = totalJobs > 0 ? ((completedJobs / totalJobs) * 100).toFixed(2) : 'N/A';
    console.log(`  Overall completion rate: ${completionRate}%`);
  } catch (error) {
    console.error('✗ Job Statistics Failed:', error.message);
  }

  // Get cancellation rate
  try {
    const cancellationRate = await db.getCancellationRate(BENCHMARK_CONFIG.stats.hours);
    results.cancellation_rate = cancellationRate;
    console.log('\n✓ Cancellation Rate (last 24h):');
    cancellationRate.forEach(rate => {
      console.log(`  ${rate.type}: ${rate.cancellation_rate}% (${rate.cancelled}/${rate.total} cancelled)`);
    });
  } catch (error) {
    console.error('✗ Cancellation Rate Failed:', error.message);
  }

  // Get recent failures
  try {
    const failures = await db.getRecentFailures(5);
    results.recent_failures = failures;
    console.log('\n✓ Recent Failures:');
    failures.forEach(failure => {
      console.log(`  Job ${failure.id} (${failure.type}): ${failure.status} - ${failure.error || 'No error'}`);
    });
  } catch (error) {
    console.error('✗ Recent Failures Failed:', error.message);
  }

  return results;
}

async function benchmarkWeaviateSearch() {
  console.log('\n=== WEAVIATE SEARCH BENCHMARK ===\n');
  
  const results = {
    collection_info: null,
    search_queries: []
  };

  // Get collection info
  try {
    const response = await fetch('http://localhost:8082/v1/schema');
    const schema = await response.json();
    results.collection_info = schema;
    console.log('✓ Weaviate Collection:', schema.classes[0].class);
  } catch (error) {
    console.error('✗ Weaviate Collection Info Failed:', error.message);
    return results;
  }

  // Benchmark search queries
  const testQueries = [
    "GPU queue system for resource management",
    "Chonkie text chunking for semantic search",
    "Embedding service performance optimization",
    "Weaviate vector database configuration"
  ];

  console.log('\n--- Search Query Performance ---');
  for (const query of testQueries) {
    const start = Date.now();
    const response = await fetch('http://localhost:8082/v1/objects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nearText: {
          concepts: [query],
          certainty: 0.7
        },
        limit: 5
      })
    });
    const duration = Date.now() - start;
    const data = await response.json();
    
    results.search_queries.push({
      query: query,
      duration_ms: duration,
      result_count: data.objects?.length || 0
    });
    
    console.log(`  "${query.substring(0, 40)}...": ${duration}ms (${data.objects?.length || 0} results)`);
  }

  // Calculate search statistics
  const searchStats = {
    avg_duration: results.search_queries.reduce((sum, r) => sum + r.duration_ms, 0) / results.search_queries.length,
    min_duration: Math.min(...results.search_queries.map(r => r.duration_ms)),
    max_duration: Math.max(...results.search_queries.map(r => r.duration_ms)),
    avg_results: results.search_queries.reduce((sum, r) => sum + r.result_count, 0) / results.search_queries.length
  };
  console.log(`\nSearch Stats: Avg ${searchStats.avg_duration.toFixed(1)}ms, Min ${searchStats.min_duration}ms, Max ${searchStats.max_duration}ms, Avg ${searchStats.avg_results.toFixed(1)} results`);

  return {
    collection: results.collection_info,
    search_performance: searchStats,
    raw_results: results
  };
}

async function runCompleteBenchmark() {
  console.log('Starting Complete System Performance Benchmark...\n');
  const startTime = Date.now();

  const embeddingResults = await benchmarkEmbeddingService();
  const queueResults = await benchmarkQueueSystem();
  const weaviateResults = await benchmarkWeaviateSearch();

  const totalDuration = Date.now() - startTime;

  const summary = {
    benchmark_timestamp: new Date().toISOString(),
    total_duration_ms: totalDuration,
    embedding_service: {
      status: embeddingResults.service?.status || 'unknown',
      single_embedding_avg_ms: embeddingResults.single_embeddings?.avg_duration || 0,
      batch_embedding_avg_ms: embeddingResults.batch_embeddings?.avg_duration || 0,
      batch_per_text_avg_ms: embeddingResults.batch_embeddings?.avg_per_text || 0,
      avg_vram_usage_mb: embeddingResults.single_embeddings?.avg_vram || 0
    },
    queue_system: {
      total_jobs_24h: queueResults.job_stats?.reduce((sum, s) => sum + s.count, 0) || 0,
      completion_rate: queueResults.job_stats ? 
        ((queueResults.job_stats.reduce((sum, s) => sum + (s.status === 'completed' ? s.count : 0), 0) / 
          queueResults.job_stats.reduce((sum, s) => sum + s.count, 0)) * 100).toFixed(2) : 'N/A',
      avg_queue_wait_ms: queueResults.job_stats?.reduce((sum, s) => sum + (s.avg_queue_wait_time_ms || 0), 0) / queueResults.job_stats.length || 0
    },
    weaviate_search: {
      collection_status: weaviateResults.collection?.classes?.[0]?.class || 'unknown',
      avg_search_duration_ms: weaviateResults.search_performance?.avg_duration || 0,
      avg_result_count: weaviateResults.search_performance?.avg_results || 0
    },
    overall_health: {
      embedding_healthy: embeddingResults.service?.status === 'healthy',
      queue_operational: queueResults.job_stats !== null,
      weaviate_operational: weaviateResults.collection !== null
    }
  };

  console.log('\n=== BENCHMARK SUMMARY ===');
  console.log(JSON.stringify(summary, null, 2));
  console.log(`\nTotal Benchmark Duration: ${Math.round(totalDuration / 1000)}s`);

  return summary;
}

// Run benchmark if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runCompleteBenchmark().catch(error => {
    console.error('Benchmark failed:', error);
    process.exit(1);
  });
}

export { runCompleteBenchmark, benchmarkEmbeddingService, benchmarkQueueSystem, benchmarkWeaviateSearch };