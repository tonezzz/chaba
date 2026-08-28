/**
 * Advanced Queue Scheduling Algorithms
 * 
 * Implements multiple scheduling strategies for comparative testing:
 * - Priority-based (current)
 * - Shortest Job First (SJF)
 * - Round Robin
 * - Adaptive (based on historical performance)
 * - Memory-aware (based on GPU memory availability)
 * - Dynamic priority (based on system state)
 */

import * as db from './db.mjs';
import { predictJobDuration } from './job-duration-prediction.mjs';
import { getNextJobWithMemoryConstraint } from './gpu-memory-aware.mjs';
import { getNextJobWithDynamicPriority } from './dynamic-priority.mjs';

// Scheduling algorithms
const SCHEDULERS = {
  priority: 'priority',           // Current: priority-based
  sjf: 'sjf',                     // Shortest Job First
  rr: 'rr',                       // Round Robin
  adaptive: 'adaptive',           // Adaptive based on performance
  memory_aware: 'memory_aware',   // GPU memory-aware scheduling
  dynamic_priority: 'dynamic_priority' // Dynamic priority adjustment
};

let currentScheduler = SCHEDULERS.memory_aware; // Use memory-aware by default
let timeSlice = 10000; // 10 seconds for round robin

/**
 * Set scheduling algorithm
 */
export function setScheduler(algorithm) {
  if (Object.values(SCHEDULERS).includes(algorithm)) {
    currentScheduler = algorithm;
    console.log(`Scheduler changed to: ${algorithm}`);
  } else {
    throw new Error(`Unknown scheduler: ${algorithm}`);
  }
}

/**
 * Get current scheduler
 */
export function getScheduler() {
  return currentScheduler;
}

/**
 * Estimate job execution time based on historical data
 */
async function estimateExecutionTime(type, params) {
  try {
    const metrics = await db.getPerformanceMetricsByType(type, 10);
    if (metrics.length > 0) {
      // Return average execution time for this job type
      return metrics[0].avg_execution_time;
    }
  } catch (error) {
    console.error('Failed to get historical metrics:', error);
  }

  // Fallback estimates (in ms)
  const estimates = {
    embedding: 5000,
    imagen2: 15000,
    txt2vid: 60000,
    cogvideo: 60000,
    llama: 3000,
    yomi_summary: 5000,
    yomi_daily: 8000,
    yomi_daily_batch: 15000
  };

  return estimates[type] || 10000;
}

/**
 * Priority-based scheduling (current default)
 */
async function getNextJobPriority() {
  return await db.getNextPendingJob();
}

/**
 * Shortest Job First scheduling
 */
async function getNextJobSJF() {
  const jobs = await db.listJobs('pending');
  if (jobs.length === 0) return null;

  // Estimate execution time for each job
  const jobsWithEstimates = await Promise.all(
    jobs.map(async (job) => ({
      job,
      estimate: await estimateExecutionTime(job.type, job.params)
    }))
  );

  // Sort by estimated execution time
  jobsWithEstimates.sort((a, b) => a.estimate - b.estimate);

  return jobsWithEstimates[0].job;
}

/**
 * Round Robin scheduling
 */
let rrIndex = 0;
async function getNextJobRR() {
  const jobs = await db.listJobs('pending');
  if (jobs.length === 0) return null;

  // Simple round robin based on job order
  const job = jobs[rrIndex % jobs.length];
  rrIndex++;
  return job;
}

/**
 * Adaptive scheduling based on performance
 */
async function getNextJobAdaptive() {
  const jobs = await db.listJobs('pending');
  if (jobs.length === 0) return null;

  // Get recent performance metrics
  const metrics = await db.getComparativeMetrics();
  
  // Build performance profile
  const performanceProfile = {};
  metrics.forEach(metric => {
    const key = `${metric.type}_${metric.mode}`;
    performanceProfile[key] = {
      avgTime: metric.avg_time,
      efficiency: metric.job_count > 0 ? metric.avg_time / metric.job_count : Infinity
    };
  });

  // Score each job based on historical performance
  const jobsWithScores = await Promise.all(
    jobs.map(async (job) => {
      const mode = job.params.mode || 'cpu';
      const key = `${job.type}_${mode}`;
      const profile = performanceProfile[key] || { avgTime: 10000, efficiency: 1 };
      
      // Lower score = better (faster, more efficient)
      const score = profile.avgTime * profile.efficiency;
      
      return {
        job,
        score
      };
    })
  );

  // Sort by score (ascending)
  jobsWithScores.sort((a, b) => a.score - b.score);

  return jobsWithScores[0].job;
}

/**
 * Memory-aware scheduling
 */
async function getNextJobMemoryAware() {
  return await getNextJobWithMemoryConstraint();
}

/**
 * Dynamic priority scheduling
 */
async function getNextJobDynamicPriority() {
  return await getNextJobWithDynamicPriority();
}

/**
 * Get next job based on current scheduler
 */
export async function getNextJob() {
  switch (currentScheduler) {
    case SCHEDULERS.sjf:
      return await getNextJobSJF();
    case SCHEDULERS.rr:
      return await getNextJobRR();
    case SCHEDULERS.adaptive:
      return await getNextJobAdaptive();
    case SCHEDULERS.memory_aware:
      return await getNextJobMemoryAware();
    case SCHEDULERS.dynamic_priority:
      return await getNextJobDynamicPriority();
    case SCHEDULERS.priority:
    default:
      return await getNextJobPriority();
  }
}

/**
 * Batch optimization for embeddings
 */
export function optimizeBatch(texts, maxBatchSize = 32) {
  if (texts.length <= maxBatchSize) {
    return [texts];
  }

  const batches = [];
  for (let i = 0; i < texts.length; i += maxBatchSize) {
    batches.push(texts.slice(i, i + maxBatchSize));
  }

  return batches;
}

/**
 * Get scheduler statistics
 */
export async function getSchedulerStats() {
  const jobs = await db.getRecentJobsWithMetrics(100);
  
  const stats = {
    total_jobs: jobs.length,
    by_type: {},
    by_mode: {},
    avg_execution_time: 0,
    avg_queue_wait: 0,
    scheduler: currentScheduler
  };

  let totalExecutionTime = 0;
  let totalQueueWait = 0;
  let executionCount = 0;
  let queueWaitCount = 0;

  jobs.forEach(job => {
    // By type
    if (!stats.by_type[job.type]) {
      stats.by_type[job.type] = { count: 0, avg_time: 0 };
    }
    stats.by_type[job.type].count++;
    if (job.execution_time_ms) {
      stats.by_type[job.type].avg_time += job.execution_time_ms;
    }

    // By mode
    if (job.mode) {
      if (!stats.by_mode[job.mode]) {
        stats.by_mode[job.mode] = { count: 0, avg_time: 0 };
      }
      stats.by_mode[job.mode].count++;
      if (job.execution_time_ms) {
        stats.by_mode[job.mode].avg_time += job.execution_time_ms;
      }
    }

    // Totals
    if (job.execution_time_ms) {
      totalExecutionTime += job.execution_time_ms;
      executionCount++;
    }
    if (job.queue_wait_time_ms) {
      totalQueueWait += job.queue_wait_time_ms;
      queueWaitCount++;
    }
  });

  // Calculate averages
  if (executionCount > 0) {
    stats.avg_execution_time = totalExecutionTime / executionCount;
  }
  if (queueWaitCount > 0) {
    stats.avg_queue_wait = totalQueueWait / queueWaitCount;
  }

  // Calculate per-type averages
  Object.keys(stats.by_type).forEach(type => {
    const typeData = stats.by_type[type];
    if (typeData.count > 0) {
      typeData.avg_time = typeData.avg_time / typeData.count;
    }
  });

  // Calculate per-mode averages
  Object.keys(stats.by_mode).forEach(mode => {
    const modeData = stats.by_mode[mode];
    if (modeData.count > 0) {
      modeData.avg_time = modeData.avg_time / modeData.count;
    }
  });

  return stats;
}
