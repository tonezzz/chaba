/**
 * GPU Memory-Aware Scheduling
 * 
 * Manages GPU memory allocation and scheduling based on available GPU memory
 * and job memory requirements.
 */

import * as db from './db.mjs';

// GPU memory configuration (in MB)
const GPU_MEMORY_CONFIG = {
  total: 8192,        // 8GB total GPU memory
  reserved: 1024,     // 1GB reserved for system/overhead
  available: 7168,    // 7GB available for jobs
  safety_margin: 512   // 512MB safety margin
};

// Job memory requirements (in MB) - estimated based on job type and parameters
const JOB_MEMORY_REQUIREMENTS = {
  embedding: (params) => {
    const batchSize = params.batch_size || 1;
    const embeddingDim = params.embedding_dim || 768;
    // Rough estimate: batch_size * embedding_dim * 4 bytes * 2 (activations)
    return Math.min(batchSize * embeddingDim * 8 / 1024, 2048);
  },
  
  imagen2: (params) => {
    const resolution = params.resolution || '512x512';
    const [width, height] = resolution.split('x').map(Number);
    // Rough estimate based on image size
    return Math.min((width * height * 4) / 1024, 4096);
  },
  
  txt2vid: (params) => {
    const frames = params.num_frames || 16;
    const resolution = params.resolution || '512x512';
    const [width, height] = resolution.split('x').map(Number);
    // Video generation is memory intensive
    return Math.min(frames * (width * height * 4) / 1024, 6144);
  },
  
  llama: (params) => {
    const contextLength = params.context_length || 2048;
    const modelSize = params.model_size || '7b';
    // LLM memory depends on context length and model size
    const modelMemory = modelSize === '7b' ? 4096 : 8192;
    return Math.min(modelMemory + (contextLength * 2) / 1024, 6144);
  },
  
  yomi_summary: (params) => {
    const textLength = params.text_length || 1000;
    // Summary jobs use smaller models
    return Math.min(1024 + (textLength / 10), 2048);
  },
  
  yomi_daily: (params) => {
    const messageCount = params.message_count || 10;
    // Daily summaries process more messages
    return Math.min(2048 + (messageCount * 50), 3072);
  },
  
  yomi_daily_batch: (params) => {
    const batchSize = params.batch_size || 5;
    // Batch processing needs more memory
    return Math.min(3072 + (batchSize * 512), 4096);
  },
  
  default: () => 1024 // Default 1GB
};

/**
 * Get memory requirement for a job
 */
export function getJobMemoryRequirement(type, params) {
  const estimator = JOB_MEMORY_REQUIREMENTS[type] || JOB_MEMORY_REQUIREMENTS.default;
  return Math.ceil(estimator(params));
}

/**
 * Get current GPU memory usage
 */
export async function getCurrentGPUMemoryUsage() {
  try {
    // Check if there's a running job
    const runningJob = await db.getRunningJob();
    
    if (!runningJob) {
      return {
        used: 0,
        available: GPU_MEMORY_CONFIG.available,
        total: GPU_MEMORY_CONFIG.total,
        utilization: 0
      };
    }
    
    // Get memory requirement for running job
    const memoryUsed = getJobMemoryRequirement(runningJob.type, runningJob.params);
    const available = GPU_MEMORY_CONFIG.available - memoryUsed - GPU_MEMORY_CONFIG.safety_margin;
    
    return {
      used: memoryUsed,
      available: Math.max(0, available),
      total: GPU_MEMORY_CONFIG.total,
      utilization: (memoryUsed / GPU_MEMORY_CONFIG.available) * 100
    };
  } catch (error) {
    console.error('Failed to get GPU memory usage:', error);
    return {
      used: 0,
      available: GPU_MEMORY_CONFIG.available,
      total: GPU_MEMORY_CONFIG.total,
      utilization: 0
    };
  }
}

/**
 * Check if job can fit in available GPU memory
 */
export async function canJobFitInMemory(type, params) {
  const memoryUsage = await getCurrentGPUMemoryUsage();
  const jobMemory = getJobMemoryRequirement(type, params);
  
  return memoryUsage.available >= jobMemory;
}

/**
 * Get next job that fits in available GPU memory
 */
export async function getNextJobWithMemoryConstraint() {
  const memoryUsage = await getCurrentGPUMemoryUsage();
  const pendingJobs = await db.listJobs('pending');
  
  if (pendingJobs.length === 0) {
    return null;
  }
  
  // Filter jobs that can fit in available memory
  const fittingJobs = pendingJobs.filter(job => {
    const jobMemory = getJobMemoryRequirement(job.type, job.params);
    return memoryUsage.available >= jobMemory;
  });
  
  if (fittingJobs.length === 0) {
    console.log('No pending jobs fit in available GPU memory');
    return null;
  }
  
  // Among fitting jobs, use the current scheduler (SJF by default)
  // For now, just return the first fitting job
  // In production, this would integrate with the scheduler
  return fittingJobs[0];
}

/**
 * Memory-aware job prioritization
 * Prioritizes jobs that better utilize available memory
 */
export async function prioritizeJobsByMemory() {
  const memoryUsage = await getCurrentGPUMemoryUsage();
  const pendingJobs = await db.listJobs('pending');
  
  if (pendingJobs.length === 0) {
    return [];
  }
  
  // Score each job based on memory fit and priority
  const jobsWithScores = pendingJobs.map(job => {
    const jobMemory = getJobMemoryRequirement(job.type, job.params);
    const memoryFit = jobMemory <= memoryUsage.available ? 1 : 0;
    const memoryEfficiency = jobMemory / memoryUsage.available; // Higher is better for utilization
    
    // Combined score: memory fit (binary) + memory efficiency + original priority
    const score = (memoryFit * 100) + (memoryEfficiency * 50) + (job.priority * 10);
    
    return {
      job,
      score,
      memoryFit,
      memoryEfficiency,
      jobMemory
    };
  });
  
  // Sort by score (descending)
  jobsWithScores.sort((a, b) => b.score - a.score);
  
  return jobsWithScores.map(item => item.job);
}

/**
 * Get GPU memory statistics
 */
export async function getGPUMemoryStats() {
  const memoryUsage = await getCurrentGPUMemoryUsage();
  const pendingJobs = await db.listJobs('pending');
  
  // Calculate memory requirements for all pending jobs
  const pendingMemoryRequirements = pendingJobs.map(job => ({
    id: job.id,
    type: job.type,
    memory: getJobMemoryRequirement(job.type, job.params),
    canFit: getJobMemoryRequirement(job.type, job.params) <= memoryUsage.available
  }));
  
  const totalPendingMemory = pendingMemoryRequirements.reduce((sum, req) => sum + req.memory, 0);
  const fittingJobs = pendingMemoryRequirements.filter(req => req.canFit);
  
  return {
    current: memoryUsage,
    pending: {
      totalJobs: pendingJobs.length,
      totalMemory: totalPendingMemory,
      fittingJobs: fittingJobs.length,
      fittingMemory: fittingJobs.reduce((sum, req) => sum + req.memory, 0)
    },
    configuration: GPU_MEMORY_CONFIG
  };
}

/**
 * Update GPU memory configuration
 */
export function updateGPUMemoryConfig(config) {
  Object.assign(GPU_MEMORY_CONFIG, config);
  console.log('GPU memory configuration updated:', GPU_MEMORY_CONFIG);
}

/**
 * Get GPU memory configuration
 */
export function getGPUMemoryConfig() {
  return { ...GPU_MEMORY_CONFIG };
}