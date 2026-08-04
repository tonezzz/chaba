#!/usr/bin/env node

/**
 * Test embedding job submission to GPU queue
 */

import * as queue from './queue.mjs';
import * as db from './db.mjs';

async function testEmbeddingQueue() {
  console.log('Testing embedding queue integration...\n');

  try {
    // Test 1: Single CPU embedding
    console.log('Test 1: Single CPU embedding');
    const job1 = await queue.submitJob('embedding', {
      text: 'GPU queue system for efficient resource management',
      use_gpu: false,
      embedding_service_url: 'http://localhost:5001',
      model: 'all-MiniLM-L6-v2'
    });
    console.log(`Submitted job ${job1.id} with priority ${job1.priority}\n`);

    // Test 2: Batch CPU embeddings
    console.log('Test 2: Batch CPU embeddings');
    const job2 = await queue.submitJob('embedding', {
      texts: [
        'Semantic search using Weaviate vector database',
        'GPU-accelerated embeddings for faster processing',
        'Queue-based resource management system'
      ],
      use_gpu: false,
      embedding_service_url: 'http://localhost:5001',
      model: 'all-MiniLM-L6-v2',
      batch_size: 3
    });
    console.log(`Submitted job ${job2.id} with priority ${job2.priority}\n`);

    // Test 3: GPU embedding (will fallback to CPU if no GPU service)
    console.log('Test 3: GPU embedding (will fallback to CPU if needed)');
    const job3 = await queue.submitJob('embedding', {
      text: 'GPU embeddings with VRAM management',
      use_gpu: true,
      embedding_service_url: 'http://localhost:5000', // Will be GPU service when ready
      model: 'all-MiniLM-L6-v2'
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
    console.log('GPU embedding service will be used when Docker build completes');

  } catch (error) {
    console.error('Test failed:', error);
    process.exit(1);
  }
}

testEmbeddingQueue();