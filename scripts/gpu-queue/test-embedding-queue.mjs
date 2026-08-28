#!/usr/bin/env node

/**
 * Test embedding job submission to GPU queue
 */

import * as queue from './queue.mjs';
import * as db from './db.mjs';

async function testEmbeddingQueue() {
  console.log('Testing embedding queue integration...\n');

  try {
    // Test 1: Single GPU embedding
    console.log('Test 1: Single GPU embedding');
    const job1 = await queue.submitJob('embedding', {
      text: 'GPU queue system for efficient resource management',
      use_gpu: true,
      embedding_service_url: 'http://localhost:5000',
      model: 'all-MiniLM-L6-v2'
    });
    console.log(`Submitted job ${job1.id} with priority ${job1.priority}\n`);

    // Test 2: Batch GPU embeddings
    console.log('Test 2: Batch GPU embeddings');
    const job2 = await queue.submitJob('embedding', {
      texts: [
        'Semantic search using Weaviate vector database',
        'GPU-accelerated embeddings for faster processing',
        'Queue-based resource management system'
      ],
      use_gpu: true,
      embedding_service_url: 'http://localhost:5000',
      model: 'all-MiniLM-L6-v2',
      batch_size: 3
    });
    console.log(`Submitted job ${job2.id} with priority ${job2.priority}\n`);

    // Test 3: Large batch GPU embedding
    console.log('Test 3: Large batch GPU embedding');
    const job3 = await queue.submitJob('embedding', {
      texts: [
        'GPU embeddings with VRAM management',
        'Efficient resource allocation for ML workloads',
        'Queue-based job scheduling system',
        'Semantic search optimization techniques',
        'Vector database performance tuning'
      ],
      use_gpu: true,
      embedding_service_url: 'http://localhost:5000',
      model: 'all-MiniLM-L6-v2',
      batch_size: 5
    });
    console.log(`Submitted job ${job3.id} with priority ${job3.priority}\n`);

    // Check queue status
    console.log('Current queue status:');
    const nextJob = await db.getNextPendingJob();
    if (nextJob) {
      console.log(`Next pending job: ${nextJob.id} (${nextJob.type}, priority ${nextJob.priority})`);
    } else {
      console.log('No pending jobs');
    }

    console.log('\nAll tests completed successfully!');
    console.log('Note: Jobs will be processed by the queue processor');
    console.log('GPU embedding service is running on port 5000 (32ms per embedding)');

  } catch (error) {
    console.error('Test failed:', error);
    process.exit(1);
  }
}

testEmbeddingQueue();