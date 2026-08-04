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
    const metrics = {
      execution_time_ms: executionTime,
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
    throw new Error(`Embedding generation failed: ${error.message}`);
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
