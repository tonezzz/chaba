import * as db from './db.mjs';
import * as scheduler from './scheduler.mjs';
import { processYomiSummaryJob, processYomiDailyJob, processYomiDailyBatchJob } from './orchestrator.mjs';

// MCP tool call helpers (will be called via stdio MCP interface)
// For now, we'll use placeholder functions that will be replaced with actual MCP calls
let mcpGpu = null;
let mcpLlama = null;

export function setMcpClients(gpuClient, llamaClient) {
  mcpGpu = gpuClient;
  mcpLlama = llamaClient;
}

// Export scheduler functions
export { setScheduler, getScheduler, getNextJob, optimizeBatch, getSchedulerStats } from './scheduler.mjs';

// Job timeout configuration (in milliseconds)
export const JOB_TIMEOUTS = {
  embedding: 300000,      // 5 minutes
  imagen2: 600000,        // 10 minutes
  txt2vid: 1200000,       // 20 minutes
  cogvideo: 1200000,      // 20 minutes
  llama: 120000,          // 2 minutes
  default: 300000         // 5 minutes default
};

// Retry configuration
export const MAX_RETRIES = 3;
export const RETRY_DELAY = 5000; // 5 seconds

// Service health check configuration
export const SERVICE_HEALTH_CHECKS = {
  embedding: {
    url: 'http://localhost:5000/health',
    timeout: 5000
  },
  imagen2: {
    url: 'http://localhost:8000/health',
    timeout: 5000
  },
  txt2vid: {
    url: 'http://localhost:8002/health',
    timeout: 5000
  }
};

// Check if GPU is busy by checking running job
export async function isGpuBusy() {
  const runningJob = await db.getRunningJob();
  return runningJob !== null;
}

// Service health check
export async function checkServiceHealth(serviceType) {
  const config = SERVICE_HEALTH_CHECKS[serviceType];
  if (!config) {
    console.warn(`No health check configuration for service type: ${serviceType}`);
    return true; // Assume healthy if no config
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), config.timeout);

    const response = await fetch(config.url, {
      method: 'GET',
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      console.log(`✓ ${serviceType} service health check passed`);
      return true;
    } else {
      console.warn(`✗ ${serviceType} service health check failed: ${response.status}`);
      return false;
    }
  } catch (error) {
    console.warn(`✗ ${serviceType} service health check error: ${error.message}`);
    return false;
  }
}

// Sleep utility
export function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Process a single job with timeout and retry logic
export async function processJob(job) {
  console.log(`Processing job ${job.id}: ${job.type}`);

  const startTime = Date.now();
  const queueWaitTime = startTime - new Date(job.created_at).getTime();
  const timeout = JOB_TIMEOUTS[job.type] || JOB_TIMEOUTS.default;

  let retryCount = 0;
  let lastError = null;

  // Pre-flight service health check
  const serviceHealthy = await checkServiceHealth(job.type);
  if (!serviceHealthy) {
    console.error(`Job ${job.id} aborted: ${job.type} service health check failed`);
    await db.updateJobStatus(job.id, 'failed', `Service health check failed for ${job.type}`);
    return;
  }

  while (retryCount <= MAX_RETRIES) {
    try {
      // Mark as running
      await db.updateJobStatus(job.id, 'running');

      // Track queue wait time
      await db.updateJobMetrics(job.id, { 
        queue_wait_time_ms: queueWaitTime,
        retry_count: retryCount
      });

      // Process with timeout
      const result = await Promise.race([
        executeJobProcessing(job),
        new Promise((_, reject) => 
          setTimeout(() => reject(new Error(`Job timeout after ${timeout}ms`)), timeout)
        )
      ]);

      // Job completed successfully
      const endTime = Date.now();
      const executionTime = endTime - startTime;

      await db.updateJobMetrics(job.id, { execution_time_ms: executionTime });
      await db.updateJobStatus(job.id, 'completed');
      console.log(`Job ${job.id} completed successfully in ${executionTime}ms (attempt ${retryCount + 1})`);
      return;

    } catch (error) {
      lastError = error;
      console.error(`Job ${job.id} failed (attempt ${retryCount + 1}):`, error.message);

      // Check if error is retryable
      const isRetryable = isRetryableError(error);
      
      if (isRetryable && retryCount < MAX_RETRIES) {
        retryCount++;
        console.log(`Retrying job ${job.id} in ${RETRY_DELAY}ms... (attempt ${retryCount + 1}/${MAX_RETRIES})`);
        await sleep(RETRY_DELAY);
      } else {
        // Non-retryable error or max retries reached
        const errorMessage = isRetryable 
          ? `Job failed after ${MAX_RETRIES} retries: ${error.message}`
          : `Job failed with non-retryable error: ${error.message}`;
        
        console.error(`Job ${job.id} final failure: ${errorMessage}`);
        await db.updateJobStatus(job.id, 'failed', errorMessage);
        return;
      }
    }
  }
}

// Execute job processing (separated for timeout handling)
async function executeJobProcessing(job) {
  console.log(`Executing job ${job.id}: ${job.type}`);

  // Get initial VRAM usage if GPU client available
  let initialVRAM = 0;
  if (mcpGpu) {
    try {
      const gpuStatus = await mcpGpu.callTool({
        name: 'mcp1_gpu_status',
        arguments: {}
      });
      initialVRAM = gpuStatus.vram_used_mb || 0;
    } catch (error) {
      console.error('Failed to get initial GPU status:', error);
    }
  }

  // Route to appropriate processor
  let result;
  let gpuUsed = false;
  let mode = 'cpu';

  switch (job.type) {
    case 'imagen2':
      gpuUsed = true;
      mode = 'gpu';
      result = await processImagen2Job(job);
      break;
    case 'cogvideo':
    case 'txt2vid':
      gpuUsed = true;
      mode = 'gpu';
      result = await processCogvideoJob(job);
      break;
    case 'llama':
      mode = job.params.mode || 'auto';
      result = await processLlamaJob(job);
      break;
    case 'embedding':
      mode = job.params.mode || 'cpu';
      gpuUsed = mode === 'gpu';
      result = await processEmbeddingJob(job);
      break;
    case 'yomi_summary':
      mode = 'cpu';
      result = await processYomiSummaryJob(job);
      break;
    case 'yomi_daily':
      mode = 'cpu';
      result = await processYomiDailyJob(job);
      break;
    case 'yomi_daily_batch':
      mode = 'cpu';
      result = await processYomiDailyBatchJob(job);
      break;
    default:
      throw new Error(`Unknown job type: ${job.type}`);
  }

  // Get final VRAM usage
  let finalVRAM = 0;
  if (mcpGpu && gpuUsed) {
    try {
      const gpuStatus = await mcpGpu.callTool({
        name: 'mcp1_gpu_status',
        arguments: {}
      });
      finalVRAM = gpuStatus.vram_used_mb || 0;
    } catch (error) {
      console.error('Failed to get final GPU status:', error);
    }
  }

  // Update job metrics
  const metrics = {
    gpu_used: gpuUsed,
    vram_used_mb: finalVRAM - initialVRAM,
    mode: mode,
    batch_size: job.params.batch_size || 1,
    result: result
  };

  // Add embedding-specific metrics if applicable
  if (job.type === 'embedding' && result) {
    metrics.embedding_dimensions = result.embeddings?.[0]?.length || 384;
    metrics.embedding_model = job.params.model || 'all-MiniLM-L6-v2';
    metrics.text_count = result.text_count || 1;
  }

  await db.updateJobMetrics(job.id, metrics);

  return result;
}

// Determine if error is retryable
export function isRetryableError(error) {
  const retryablePatterns = [
    /timeout/i,
    /fetch failed/i,
    /network/i,
    /connection/i,
    /service unavailable/i,
    /temporary/i,
    /ECONNREFUSED/i,
    /ETIMEDOUT/i
  ];

  const errorMessage = error.message || '';
  return retryablePatterns.some(pattern => pattern.test(errorMessage));
}

// Process imagen2 job
async function processImagen2Job(job) {
  console.log('Processing imagen2 job - holding llama');

  // Hold llama on CPU
  if (mcpGpu) {
    try {
      await mcpGpu.callTool({
        name: 'mcp1_hold_llama',
        arguments: {}
      });
      console.log('Llama held on CPU');
    } catch (error) {
      console.error('Failed to hold llama:', error);
      // Continue anyway - llama might already be on CPU
    }
  }

  // Run imagen2 generation
  const params = job.params;
  console.log('Running imagen2 generation with params:', params);

  if (mcpGpu) {
    try {
      await mcpGpu.callTool({
        name: 'mcp1_generate_image',
        arguments: {
          prompt: params.prompt,
          negative_prompt: params.negative_prompt,
          width: params.width || 1024,
          height: params.height || 1024,
          steps: params.steps || 4,
          guidance_scale: params.guidance_scale || 1.0,
          guidance_rescale: params.guidance_rescale || 0.0,
          seed: params.seed || -1,
          mode: params.mode || 'lightning_txt2img'
        }
      });
      console.log('Imagen2 generation completed');
    } catch (error) {
      throw new Error(`Imagen2 generation failed: ${error.message}`);
    }
  } else {
    throw new Error('MCP GPU client not available');
  }

  // Resume llama on GPU
  console.log('Resuming llama on GPU');
  if (mcpGpu) {
    try {
      await mcpGpu.callTool({
        name: 'mcp1_resume_llama',
        arguments: {}
      });
      console.log('Llama resumed on GPU');
    } catch (error) {
      console.error('Failed to resume llama:', error);
    }
  }
}

// Process cogvideo job
async function processCogvideoJob(job) {
  console.log('Processing cogvideo job - holding llama');

  // Hold llama on CPU
  if (mcpGpu) {
    try {
      await mcpGpu.callTool({
        name: 'mcp1_hold_llama',
        arguments: {}
      });
      console.log('Llama held on CPU');
    } catch (error) {
      console.error('Failed to hold llama:', error);
    }
  }

  // Run cogvideo generation
  const params = job.params;
  console.log('Running cogvideo generation with params:', params);

  // TODO: Implement cogvideo generation via MCP or direct API call
  // For now, this is a placeholder
  throw new Error('Cogvideo generation not yet implemented');

  // Resume llama on GPU (after implementation)
  if (mcpGpu) {
    try {
      await mcpGpu.callTool({
        name: 'mcp1_resume_llama',
        arguments: {}
      });
    } catch (error) {
      console.error('Failed to resume llama:', error);
    }
  }
}

// Process llama job
async function processLlamaJob(job) {
  console.log('Processing llama job');

  const params = job.params;
  console.log('Running llama with params:', params);

  if (mcpLlama) {
    try {
      const result = await mcpLlama.callTool({
        name: 'mcp2_chat',
        arguments: {
          prompt: params.prompt,
          max_tokens: params.max_tokens || 512,
          temperature: params.temperature || 0.7
        }
      });
      console.log('Llama chat completed');
      return result;
    } catch (error) {
      throw new Error(`Llama chat failed: ${error.message}`);
    }
  } else {
    throw new Error('MCP Llama client not available');
  }
}

// Process embedding job
async function processEmbeddingJob(job) {
  console.log('Processing embedding job');

  const params = job.params;
  console.log('Running embedding generation with params:', params);

  // Embeddings can run on CPU or GPU depending on configuration
  const useGpu = params.use_gpu || false;
  const embeddingServiceUrl = params.embedding_service_url || 'http://localhost:5000';

  if (useGpu) {
    console.log('Using GPU for embeddings');
    
    // Check VRAM availability before proceeding
    if (mcpGpu) {
      try {
        const gpuStatus = await mcpGpu.callTool({
          name: 'mcp1_gpu_status',
          arguments: {}
        });
        
        const vramFree = gpuStatus.vram_free_mb || 0;
        const vramRequired = 700; // MiniLM requires ~700MB
        
        if (vramFree < vramRequired) {
          console.warn(`Insufficient VRAM: ${vramFree}MB free, ${vramRequired}MB required. Falling back to CPU.`);
          // Override to CPU mode
          params.use_gpu = false;
        } else {
          console.log(`VRAM check passed: ${vramFree}MB free, ${vramRequired}MB required`);
        }
      } catch (error) {
        console.error('Failed to check VRAM:', error);
        // Continue anyway, let embedding service handle it
      }
    }
    
    // Hold llama if using GPU
    if (mcpGpu && params.use_gpu) {
      try {
        await mcpGpu.callTool({
          name: 'mcp1_hold_llama',
          arguments: {}
        });
        console.log('Llama held on CPU for GPU embeddings');
      } catch (error) {
        console.error('Failed to hold llama:', error);
      }
    }
  } else {
    console.log('Using CPU for embeddings');
  }

  // Call embedding service
  console.log('Generating embeddings for texts:', params.texts?.length || 1);
  
  const startTime = Date.now();
  let embeddings;
  
  try {
    if (params.texts && params.texts.length > 1) {
      // Batch embedding
      const response = await fetch(`${embeddingServiceUrl}/embed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          texts: params.texts,
          use_gpu: params.use_gpu
        })
      });
      
      if (!response.ok) {
        throw new Error(`Embedding service error: ${response.statusText}`);
      }
      
      const data = await response.json();
      embeddings = data.embeddings;
      console.log(`Generated ${data.count} embeddings in ${data.time_seconds}s (${data.device})`);
    } else {
      // Single embedding
      const text = params.text || params.texts?.[0] || '';
      const response = await fetch(`${embeddingServiceUrl}/embed-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          use_gpu: params.use_gpu
        })
      });
      
      if (!response.ok) {
        throw new Error(`Embedding service error: ${response.statusText}`);
      }
      
      const data = await response.json();
      embeddings = [data.embedding];
      console.log(`Generated embedding in ${data.time_seconds}s (${data.device})`);
    }
  } catch (error) {
    console.error('Embedding service call failed:', error);
    
    // Enhanced error context
    const errorContext = {
      service_url: embeddingServiceUrl,
      use_gpu: params.use_gpu,
      text_count: params.texts?.length || 1,
      error_type: error.name,
      error_message: error.message
    };
    
    console.error('Embedding error context:', errorContext);
    throw new Error(`Embedding generation failed: ${error.message} (service: ${embeddingServiceUrl}, gpu: ${params.use_gpu})`);
  }

  const endTime = Date.now();
  console.log(`Embeddings generated in ${endTime - startTime}ms (${params.use_gpu ? 'GPU' : 'CPU'})`);

  // Resume llama if we used GPU
  if (params.use_gpu && mcpGpu) {
    try {
      await mcpGpu.callTool({
        name: 'mcp1_resume_llama',
        arguments: {}
      });
      console.log('Llama resumed on GPU');
    } catch (error) {
      console.error('Failed to resume llama:', error);
    }
  }

  return {
    embedding_time: endTime - startTime,
    mode: params.use_gpu ? 'gpu' : 'cpu',
    text_count: params.texts?.length || 1,
    embeddings: embeddings
  };
}

// Main queue processor loop
export async function startQueueProcessor() {
  console.log('Starting queue processor');

  while (true) {
    try {
      // Check if GPU is busy
      const busy = await isGpuBusy();

      if (!busy) {
        // Get next pending job using current scheduler
        const job = await scheduler.getNextJob();

        if (job) {
          console.log(`Found pending job ${job.id} (${scheduler.getScheduler()} scheduler), processing...`);
          await processJob(job);
        } else {
          // No jobs, wait a bit
          await sleep(1000);
        }
      } else {
        // GPU busy, wait a bit
        await sleep(1000);
      }
    } catch (error) {
      console.error('Queue processor error:', error);
      await sleep(5000); // Wait longer on error
    }
  }
}

// Submit a new job to the queue
export async function submitJob(type, params) {
  const job = await db.createJob(type, params);
  console.log(`Job ${job.id} submitted: ${job.type}`);
  return job;
}

// Cancel a job
export async function cancelJob(id) {
  const job = await db.getJob(id);
  if (!job) {
    throw new Error('Job not found');
  }

  if (job.status === 'running') {
    // Can't cancel running jobs (let them finish)
    throw new Error('Cannot cancel running job');
  }

  await db.cancelJob(id);
  console.log(`Job ${id} cancelled`);
  return job;
}
