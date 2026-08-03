import * as db from './db.mjs';
import * as scheduler from './scheduler.mjs';

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

// Check if GPU is busy by checking running job
export async function isGpuBusy() {
  const runningJob = await db.getRunningJob();
  return runningJob !== null;
}

// Process a single job (orchestrator mode - no MCP calls)
export async function processJob(job) {
  console.log(`Processing job ${job.id}: ${job.type}`);

  const startTime = Date.now();
  const queueWaitTime = startTime - new Date(job.created_at).getTime();

  try {
    // Mark as running
    await db.updateJobStatus(job.id, 'running');

    // Track queue wait time
    await db.updateJobMetrics(job.id, { queue_wait_time_ms: queueWaitTime });

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
        // Llama can be CPU or GPU depending on state
        mode = job.params.mode || 'auto';
        result = await processLlamaJob(job);
        break;
      case 'embedding':
        mode = job.params.mode || 'cpu';
        gpuUsed = mode === 'gpu';
        result = await processEmbeddingJob(job);
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

    const endTime = Date.now();
    const executionTime = endTime - startTime;

    // Update job metrics
    await db.updateJobMetrics(job.id, {
      execution_time_ms: executionTime,
      gpu_used: gpuUsed,
      vram_used_mb: finalVRAM - initialVRAM,
      mode: mode,
      batch_size: job.params.batch_size || 1,
      result: result
    });

    // Mark as completed
    await db.updateJobStatus(job.id, 'completed');
    console.log(`Job ${job.id} completed successfully in ${executionTime}ms`);

  } catch (error) {
    console.error(`Job ${job.id} failed:`, error);
    await db.updateJobStatus(job.id, 'failed', error.message);
  }
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
  // For data collection, we'll track both modes
  const useGpu = params.use_gpu || false;

  if (useGpu) {
    console.log('Using GPU for embeddings');
    // Hold llama if using GPU
    if (mcpGpu) {
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

  // Call embedding service (placeholder for actual implementation)
  // This would call the weaviate-search embedding service
  console.log('Generating embeddings for texts:', params.texts?.length || 1);

  // Simulate embedding generation time for data collection
  const startTime = Date.now();
  const embeddingTime = useGpu ? 2000 : 8000; // GPU faster than CPU
  await sleep(embeddingTime);
  const endTime = Date.now();

  console.log(`Embeddings generated in ${endTime - startTime}ms (${useGpu ? 'GPU' : 'CPU'})`);

  // Resume llama if we used GPU
  if (useGpu && mcpGpu) {
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
    mode: useGpu ? 'gpu' : 'cpu',
    text_count: params.texts?.length || 1
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

// Helper: sleep
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
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
