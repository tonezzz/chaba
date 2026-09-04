#!/usr/bin/env node
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * Automatic Weaviate Indexer
 * Runs full document indexing with Chonkie chunking and GPU embeddings
 * Designed to run as a scheduled job (cron/systemd timer)
 */

async function runAutoIndex() {
  console.log('Starting automatic Weaviate indexing...');
  const startTime = Date.now();

  try {
    // Run the main indexing script
    const { stdout, stderr } = await execAsync(
      'node /home/tony/CascadeProjects/chaba-tony-dell/scripts/weaviate/index-ssot.mjs',
      { timeout: 300000 } // 5 minute timeout
    );

    console.log('Indexing output:', stdout);
    if (stderr) {
      console.warn('Indexing warnings:', stderr);
    }

    const duration = Date.now() - startTime;
    console.log(`Automatic indexing completed in ${Math.round(duration / 1000)}s`);

  } catch (error) {
    console.error('Automatic indexing failed:', error);
    process.exit(1);
  }
}

// Run indexing if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAutoIndex().catch(error => {
    console.error('Auto indexing failed:', error);
    process.exit(1);
  });
}

export { runAutoIndex };