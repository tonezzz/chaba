#!/usr/bin/env node
import * as db from './db.mjs';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// GPU Queue Job Processor
// This script automates the full workflow: hold llama, process job, resume llama
// Run this from Cascade or a cron job

async function getQueueStatus() {
  const status = await db.getQueueStatus();
  const running = await db.getRunningJob();
  return { status, running };
}

async function processNextJob() {
  // Get next pending job
  const job = await db.getNextPendingJob();

  if (!job) {
    console.log('No pending jobs');
    return null;
  }

  console.log(`Processing job ${job.id}: ${job.type}`);

  // Hold llama if job is imagen2 or txt2vid
  if (job.type === 'imagen2' || job.type === 'txt2vid') {
    console.log('Holding llama on CPU...');
    console.log('ACTION REQUIRED: Call mcp1_hold_llama from Cascade before proceeding');
    console.log('Press Enter to continue after holding llama...');
    await new Promise(resolve => process.stdin.once('data', resolve));
  }

  // Process job via orchestrator
  console.log('Running orchestrator...');
  try {
    await execAsync('node /home/tony/CascadeProjects/chaba-tony-dell/scripts/gpu-queue/orchestrator.mjs process');
  } catch (error) {
    console.error('Orchestrator failed:', error);
    throw error;
  }

  // Resume llama if job was imagen2 or txt2vid
  if (job.type === 'imagen2' || job.type === 'txt2vid') {
    console.log('Resuming llama on GPU...');
    console.log('ACTION REQUIRED: Call mcp1_resume_llama from Cascade after job completes');
    console.log('Press Enter to continue after resuming llama...');
    await new Promise(resolve => process.stdin.once('data', resolve));
  }

  console.log(`Job ${job.id} completed`);
  return job;
}

// CLI interface
const args = process.argv.slice(2);
const command = args[0];

switch (command) {
  case 'status':
    getQueueStatus().then(status => {
      console.log(JSON.stringify(status, null, 2));
    });
    break;

  case 'process':
    processNextJob().then(job => {
      if (job) {
        console.log(`Processed job ${job.id}`);
      }
    }).catch(error => {
      console.error('Job processing failed:', error);
      process.exit(1);
    });
    break;

  default:
    console.log('Usage:');
    console.log('  node process-job.mjs status   - Get queue status');
    console.log('  node process-job.mjs process  - Process next job with hold/resume');
}
