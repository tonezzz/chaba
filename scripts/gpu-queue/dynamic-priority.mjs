/**
 * Dynamic Priority Adjustment System
 * 
 * Dynamically adjusts job priorities based on system state, job age,
 * resource availability, and historical performance.
 */

import * as db from './db.mjs';
import { predictJobDuration } from './job-duration-prediction.mjs';
import { getCurrentGPUMemoryUsage } from './gpu-memory-aware.mjs';

// Priority adjustment factors
const PRIORITY_FACTORS = {
  age: 0.3,              // Job age (older jobs get higher priority)
  memoryFit: 0.2,        // Memory fit (jobs that fit better get higher priority)
  userPriority: 0.3,     // Original user priority
  performance: 0.2       // Historical performance (faster jobs get higher priority)
};

// Priority thresholds
const PRIORITY_THRESHOLDS = {
  critical: 0.8,         // Above this gets critical priority
  high: 0.6,             // Above this gets high priority
  normal: 0.4,           // Above this gets normal priority
  low: 0.2               // Below this gets low priority
};

/**
 * Calculate dynamic priority for a job
 */
export async function calculateDynamicPriority(job) {
  let score = 0;
  
  // Age factor: older jobs get higher priority
  const ageMs = Date.now() - new Date(job.created_at).getTime();
  const ageMinutes = ageMs / (1000 * 60);
  const ageScore = Math.min(ageMinutes / 60, 1); // Max out at 1 hour
  score += ageScore * PRIORITY_FACTORS.age;
  
  // Memory fit factor
  try {
    const memoryUsage = await getCurrentGPUMemoryUsage();
    const jobMemory = getJobMemoryRequirement(job.type, job.params);
    const memoryFit = memoryUsage.available >= jobMemory ? 1 : 0;
    score += memoryFit * PRIORITY_FACTORS.memoryFit;
  } catch (error) {
    console.error('Failed to calculate memory fit:', error);
  }
  
  // User priority factor
  const userPriorityScore = job.priority / 5; // Normalize to 0-1
  score += userPriorityScore * PRIORITY_FACTORS.userPriority;
  
  // Performance factor: faster jobs get higher priority
  try {
    const predictedDuration = await predictJobDuration(job.type, job.params);
    const performanceScore = Math.max(0, 1 - (predictedDuration / 60000)); // Normalize against 1 minute
    score += performanceScore * PRIORITY_FACTORS.performance;
  } catch (error) {
    console.error('Failed to calculate performance score:', error);
  }
  
  // Map score to priority level (1-5)
  let dynamicPriority;
  if (score >= PRIORITY_THRESHOLDS.critical) {
    dynamicPriority = 5;
  } else if (score >= PRIORITY_THRESHOLDS.high) {
    dynamicPriority = 4;
  } else if (score >= PRIORITY_THRESHOLDS.normal) {
    dynamicPriority = 3;
  } else if (score >= PRIORITY_THRESHOLDS.low) {
    dynamicPriority = 2;
  } else {
    dynamicPriority = 1;
  }
  
  return {
    originalPriority: job.priority,
    dynamicPriority,
    score,
    factors: {
      age: ageScore,
      memoryFit: score >= 0 ? 1 : 0, // Simplified
      userPriority: userPriorityScore,
      performance: score >= 0 ? 1 : 0 // Simplified
    }
  };
}

/**
 * Get job memory requirement (simplified version)
 */
function getJobMemoryRequirement(type, params) {
  const requirements = {
    embedding: 1024,
    imagen2: 2048,
    txt2vid: 4096,
    llama: 2048,
    yomi_summary: 1024,
    yomi_daily: 1536,
    yomi_daily_batch: 2048
  };
  return requirements[type] || 1024;
}

/**
 * Adjust priorities for all pending jobs
 */
export async function adjustPendingJobPriorities() {
  const pendingJobs = await db.listJobs('pending');
  
  if (pendingJobs.length === 0) {
    return { adjusted: 0, jobs: [] };
  }
  
  const adjustments = [];
  
  for (const job of pendingJobs) {
    const dynamicPriority = await calculateDynamicPriority(job);
    
    // Only update if priority changed significantly
    if (Math.abs(dynamicPriority.dynamicPriority - job.priority) >= 1) {
      try {
        await db.updateJobPriority(job.id, dynamicPriority.dynamicPriority);
        adjustments.push({
          id: job.id,
          type: job.type,
          original: job.priority,
          dynamic: dynamicPriority.dynamicPriority,
          score: dynamicPriority.score
        });
      } catch (error) {
        console.error(`Failed to update priority for job ${job.id}:`, error);
      }
    }
  }
  
  return {
    adjusted: adjustments.length,
    jobs: adjustments
  };
}

/**
 * Get next job with dynamic priority
 */
export async function getNextJobWithDynamicPriority() {
  // First adjust priorities
  await adjustPendingJobPriorities();
  
  // Then get next job using standard priority-based selection
  return await db.getNextPendingJob();
}

/**
 * Priority escalation for long-waiting jobs
 */
export async function escalateLongWaitingJobs(maxWaitMinutes = 30) {
  const pendingJobs = await db.listJobs('pending');
  const maxWaitMs = maxWaitMinutes * 60 * 1000;
  
  let escalated = 0;
  
  for (const job of pendingJobs) {
    const waitTime = Date.now() - new Date(job.created_at).getTime();
    
    if (waitTime > maxWaitMs && job.priority < 5) {
      try {
        await db.updateJobPriority(job.id, 5); // Escalate to critical
        escalated++;
        console.log(`Escalated job ${job.id} to critical priority (waited ${Math.floor(waitTime / 60000)} minutes)`);
      } catch (error) {
        console.error(`Failed to escalate job ${job.id}:`, error);
      }
    }
  }
  
  return { escalated };
}

/**
 * Priority adjustment based on system load
 */
export async function adjustPriorityBasedOnLoad() {
  const memoryUsage = await getCurrentGPUMemoryUsage();
  const pendingJobs = await db.listJobs('pending');
  
  if (pendingJobs.length === 0) {
    return { adjusted: 0 };
  }
  
  let adjusted = 0;
  
  // If GPU is heavily utilized, prioritize smaller/faster jobs
  if (memoryUsage.utilization > 80) {
    for (const job of pendingJobs) {
      const predictedDuration = await predictJobDuration(job.type, job.params);
      
      // Fast jobs get priority boost
      if (predictedDuration < 10000 && job.priority < 4) {
        try {
          await db.updateJobPriority(job.id, job.priority + 1);
          adjusted++;
        } catch (error) {
          console.error(`Failed to adjust priority for job ${job.id}:`, error);
        }
      }
    }
  }
  
  return { adjusted };
}

/**
 * Get priority adjustment statistics
 */
export async function getPriorityAdjustmentStats() {
  const pendingJobs = await db.listJobs('pending');
  
  if (pendingJobs.length === 0) {
    return {
      totalJobs: 0,
      averageDynamicPriority: 0,
      priorityDistribution: {}
    };
  }
  
  const dynamicPriorities = await Promise.all(
    pendingJobs.map(job => calculateDynamicPriority(job))
  );
  
  const averageDynamicPriority = dynamicPriorities.reduce((sum, dp) => sum + dp.dynamicPriority, 0) / dynamicPriorities.length;
  
  const priorityDistribution = {};
  dynamicPriorities.forEach(dp => {
    priorityDistribution[dp.dynamicPriority] = (priorityDistribution[dp.dynamicPriority] || 0) + 1;
  });
  
  return {
    totalJobs: pendingJobs.length,
    averageDynamicPriority: averageDynamicPriority.toFixed(2),
    priorityDistribution,
    factors: {
      age: PRIORITY_FACTORS.age,
      memoryFit: PRIORITY_FACTORS.memoryFit,
      userPriority: PRIORITY_FACTORS.userPriority,
      performance: PRIORITY_FACTORS.performance
    }
  };
}

/**
 * Configure priority adjustment factors
 */
export function configurePriorityFactors(factors) {
  Object.assign(PRIORITY_FACTORS, factors);
  console.log('Priority factors updated:', PRIORITY_FACTORS);
}

/**
 * Get current priority factors
 */
export function getPriorityFactors() {
  return { ...PRIORITY_FACTORS };
}