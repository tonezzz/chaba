import * as db from './db.mjs';

// MCP tool call helpers (will be called via stdio MCP interface)
// For now, we'll use placeholder functions that will be replaced with actual MCP calls
let mcpGpu = null;
let mcpLlama = null;

export function setMcpClients(gpuClient, llamaClient) {
  mcpGpu = gpuClient;
  mcpLlama = llamaClient;
}

// Check if GPU is busy by checking running job
export async function isGpuBusy() {
  const runningJob = await db.getRunningJob();
  return runningJob !== null;
}

// Process a single job (orchestrator mode - no MCP calls)
export async function processJob(job) {
  console.log(`Processing job ${job.id}: ${job.type}`);

  try {
    // Mark as running
    await db.updateJobStatus(job.id, 'running');

    // Job processing is now handled by external orchestrator
    // This function just marks jobs as running
    console.log(`Job ${job.id} marked as running, waiting for orchestrator`);

    // Return job for orchestrator to process
    return job;
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

// Main queue processor loop
export async function startQueueProcessor() {
  console.log('Starting queue processor');

  while (true) {
    try {
      // Check if GPU is busy
      const busy = await isGpuBusy();

      if (!busy) {
        // Get next pending job
        const job = await db.getNextPendingJob();

        if (job) {
          console.log(`Found pending job ${job.id}, processing...`);
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
