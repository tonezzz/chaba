#!/usr/bin/env node
import * as db from './db.mjs';
import * as queue from './queue.mjs';

/**
 * Automatic Queue Processor
 * Continuously processes pending jobs from the GPU queue
 * Designed to run as a background service or cron job
 */

const PROCESSING_INTERVAL_MS = 5000; // Check for jobs every 5 seconds
const MAX_CONSECUTIVE_ERRORS = 5;
const ERROR_BACKOFF_MS = 30000; // Wait 30 seconds after errors

let consecutiveErrors = 0;
let isProcessing = false;

async function processNextJob() {
  if (isProcessing) {
    console.log('Already processing a job, skipping');
    return;
  }

  try {
    isProcessing = true;
    const job = await db.getNextPendingJob();

    if (!job) {
      console.log('No pending jobs to process');
      consecutiveErrors = 0; // Reset error counter on successful check
      return;
    }

    console.log(`Processing job ${job.id} (${job.type}, priority ${job.priority})`);
    await queue.processJob(job);
    consecutiveErrors = 0; // Reset error counter on successful processing
    console.log(`Job ${job.id} processing completed`);

  } catch (error) {
    consecutiveErrors++;
    console.error(`Error processing job (consecutive errors: ${consecutiveErrors}):`, error);

    if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
      console.error(`Too many consecutive errors (${consecutiveErrors}), backing off for ${ERROR_BACKOFF_MS}ms`);
      await new Promise(resolve => setTimeout(resolve, ERROR_BACKOFF_MS));
    }
  } finally {
    isProcessing = false;
  }
}

async function startAutoProcessor() {
  console.log('Starting automatic GPU queue processor...');
  console.log(`Processing interval: ${PROCESSING_INTERVAL_MS}ms`);
  console.log(`Max consecutive errors: ${MAX_CONSECUTIVE_ERRORS}`);
  console.log(`Error backoff: ${ERROR_BACKOFF_MS}ms`);

  // Process immediately on start
  await processNextJob();

  // Set up interval processing
  setInterval(async () => {
    await processNextJob();
  }, PROCESSING_INTERVAL_MS);
}

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('Shutting down auto processor...');
  await db.closePool();
  process.exit(0);
});

process.on('SIGINT', async () => {
  console.log('Shutting down auto processor...');
  await db.closePool();
  process.exit(0);
});

// Start processor if run directly
if (import.meta.url === `file://${process.argv[1]}`) {
  startAutoProcessor().catch(error => {
    console.error('Failed to start auto processor:', error);
    process.exit(1);
  });
}

export { processNextJob, startAutoProcessor };