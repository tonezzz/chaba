#!/usr/bin/env node
import { readFile, writeFile, unlink } from 'fs/promises';
import { join } from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import { mkdtemp, rmdir } from 'fs/promises';
import { tmpdir } from 'os';

const execAsync = promisify(exec);

const WEAVIATE_URL = 'http://localhost:8082';
const CHUNK_SIZES = [256, 512, 1024];
const TEST_QUERIES = [
  "GPU queue system for resource management",
  "Chonkie text chunking for semantic search",
  "Embedding service performance optimization",
  "Weaviate vector database configuration",
  "System health monitoring and alerts"
];

async function testChunkSize(chunkSize) {
  console.log(`\n=== Testing chunk size: ${chunkSize} ===`);
  
  // Create test document
  const testContent = `
# GPU Queue System and Weaviate Integration

The GPU queue system provides efficient resource management for GPU-accelerated services including embedding generation, image generation (Imagen2), and video generation (Txt2Vid). It integrates with Weaviate for semantic search capabilities using Chonkie text chunking for optimal document processing.

## GPU Queue Architecture

The queue system uses PostgreSQL for job management with support for different job types including embedding, imagen2, llama, and txt2vid. Each job has configurable priority, timeout settings, and retry logic with exponential backoff for error handling.

## Weaviate Integration

Weaviate is configured to use the GPU embedding service on port 5000 for generating 384-dimensional vectors using the all-MiniLM-L6-v2 model. The system uses Chonkie for intelligent text chunking with configurable chunk sizes and overlap to optimize search quality.

## Performance Monitoring

Comprehensive monitoring system tracks queue health, performance metrics, error statistics, and recent activity. API endpoints provide real-time statistics for job completion rates, cancellation rates, and average execution times.

## Automation

The system includes automatic queue processing via systemd services and scheduled daily Weaviate indexing at 2 AM to ensure the search index stays current with the latest documentation.
`;

  const tempDir = await mkdtemp(join(tmpdir(), 'chunk-test-'));
  const tempFile = join(tempDir, 'test.txt');
  await writeFile(tempFile, testContent, 'utf-8');
  
  try {
    // Test chunking
    const { stdout } = await execAsync(
      `/home/tony/venv-embeddings/bin/python /home/tony/CascadeProjects/chaba/scripts/chunk-text.py "${tempFile}" ${chunkSize} 50`,
      { timeout: 30000 }
    );
    
    const result = JSON.parse(stdout);
    const chunks = result.chunks;
    
    console.log(`Chunk count: ${chunks.length}`);
    console.log(`Average chunk length: ${Math.round(testContent.length / chunks.length)} chars`);
    
    // Analyze chunk characteristics
    const chunkLengths = chunks.map(c => c.length);
    const avgLength = chunkLengths.reduce((a, b) => a + b, 0) / chunkLengths.length;
    const minLength = Math.min(...chunkLengths);
    const maxLength = Math.max(...chunkLengths);
    
    console.log(`Chunk length stats: avg ${Math.round(avgLength)}, min ${minLength}, max ${maxLength}`);
    
    // Test search quality (simulated - we'd need real search for this)
    console.log(`Search quality analysis: Would need to index and test search queries`);
    
    return {
      chunkSize,
      chunkCount: chunks.length,
      avgChunkLength: Math.round(avgLength),
      minChunkLength: minLength,
      maxChunkLength: maxLength,
      chunks: chunks
    };
    
  } finally {
    await unlink(tempFile);
    await rmdir(tempDir);
  }
}

async function compareChunkSizes() {
  console.log('=== Chunk Size Comparison Analysis ===\n');
  
  const results = [];
  
  for (const chunkSize of CHUNK_SIZES) {
    const result = await testChunkSize(chunkSize);
    results.push(result);
  }
  
  console.log('\n=== Comparison Summary ===');
  console.log('Chunk Size | Chunks | Avg Length | Min Length | Max Length');
  console.log('-----------|--------|------------|------------|------------');
  
  for (const result of results) {
    console.log(
      `${result.chunkSize.toString().padEnd(10)} | ` +
      `${result.chunkCount.toString().padEnd(6)} | ` +
      `${result.avgChunkLength.toString().padEnd(10)} | ` +
      `${result.minChunkLength.toString().padEnd(10)} | ` +
      `${result.maxChunkLength}`
    );
  }
  
  // Recommendations
  console.log('\n=== Recommendations ===');
  console.log('Based on the analysis:');
  console.log('- Smaller chunks (256): More granular search, higher precision, more vectors');
  console.log('- Medium chunks (512): Balanced approach, good for general search');
  console.log('- Larger chunks (1024): More context per chunk, better for broad queries');
  console.log('\nCurrent recommendation: 512 tokens (balanced approach)');
  console.log('Consider testing with real search queries to determine optimal size for your use case.');
  
  return results;
}

// Run comparison if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  compareChunkSizes().catch(error => {
    console.error('Chunk size comparison failed:', error);
    process.exit(1);
  });
}

export { compareChunkSizes, testChunkSize };