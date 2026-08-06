#!/usr/bin/env node
import * as db from './db.mjs';

// GPU Queue Orchestrator
// This script processes jobs from the queue using MCP tools
// Run this from Cascade or a cron job

// Llama server URL - using direct IP to avoid Docker DNS issues
// Container IP: 172.19.0.14 (thai-legal-inference in web_default network)
const LLAMA_URL = 'http://172.19.0.14:8000/v1/chat/completions';

async function processNextJob() {
  // Get next pending job
  const job = await db.getNextPendingJob();

  if (!job) {
    console.log('No pending jobs');
    return null;
  }

  console.log(`Processing job ${job.id}: ${job.type}`);

  // Mark as running
  await db.updateJobStatus(job.id, 'running');

  return job;
}

async function completeJob(jobId, success = true, error = null) {
  if (success) {
    await db.updateJobStatus(jobId, 'completed');
    console.log(`Job ${jobId} completed`);
  } else {
    await db.updateJobStatus(jobId, 'failed', error);
    console.log(`Job ${jobId} failed: ${error}`);
  }
}

async function getQueueStatus() {
  const status = await db.getQueueStatus();
  const running = await db.getRunningJob();
  return { status, running };
}

// Call imagen2-inference API directly
async function callImagen2Inference(params) {
  const response = await fetch('http://localhost:8000/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      prompt: params.prompt,
      width: params.width || 512,
      height: params.height || 512,
      steps: params.steps || 4,
      guidance_scale: params.guidance_scale || 1.0,
      mode: params.mode || 'lightning_txt2img',
    }),
  });

  if (!response.ok) {
    throw new Error(`Imagen2 inference failed: ${response.status} ${response.statusText}`);
  }

  return await response.json();
}

// Call txt2vid-inference API directly
async function callTxt2vidInference(params) {
  const response = await fetch('http://localhost:8002/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      prompt: params.prompt,
      negative_prompt: params.negative_prompt || '',
      width: params.width || 256,
      height: params.height || 256,
      num_frames: params.num_frames || 16,
      num_inference_steps: params.num_inference_steps || 25,
      guidance_scale: params.guidance_scale || 9.0,
      seed: params.seed || -1,
      fps: params.fps || 8,
    }),
  });

  if (!response.ok) {
    throw new Error(`Txt2vid inference failed: ${response.status} ${response.statusText}`);
  }

  return await response.json();
}

// Process imagen2 job (MCP hold/resume must be called by Cascade)
async function processImagen2Job(job) {
  console.log(`Processing imagen2 job ${job.id}`);

  try {
    // Generate image
    console.log('Generating image...');
    const result = await callImagen2Inference(job.params);
    console.log('Image generated:', result.id);

    await completeJob(job.id, true);
    return result;
  } catch (error) {
    console.error('Imagen2 job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Process llama job (MCP chat to be called by Cascade)
async function processLlamaJob(job) {
  console.log(`Processing llama job ${job.id}`);

  try {
    // mcp2_chat would be called here by Cascade
    console.log('Llama chat would be called by Cascade with params:', job.params);

    await completeJob(job.id, true);
    return { response: 'Llama response placeholder' };
  } catch (error) {
    console.error('Llama job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Process txt2vid job (MCP hold/resume must be called by Cascade)
async function processTxt2vidJob(job) {
  console.log(`Processing txt2vid job ${job.id}`);

  try {
    // Generate video
    console.log('Generating video...');
    const result = await callTxt2vidInference(job.params);
    console.log('Video generated:', result.job_id);

    await completeJob(job.id, true);
    return result;
  } catch (error) {
    console.error('Txt2vid job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Process embedding job
async function processEmbeddingJob(job) {
  console.log(`Processing embedding job ${job.id}`);

  try {
    const params = job.params;
    const embeddingServiceUrl = params.embedding_service_url || 'http://localhost:5000';
    const useGpu = params.use_gpu !== false; // default to GPU

    // Determine endpoint based on single or batch
    const isBatch = params.texts && Array.isArray(params.texts);
    const endpoint = isBatch ? '/embed' : '/embed-single';
    const payload = isBatch 
      ? { texts: params.texts, use_gpu: useGpu }
      : { text: params.text, use_gpu: useGpu };

    console.log(`Calling embedding service at ${embeddingServiceUrl}${endpoint}`);
    console.log(`GPU mode: ${useGpu}, Batch: ${isBatch}, Text count: ${isBatch ? params.texts.length : 1}`);

    const startTime = Date.now();
    const response = await fetch(`${embeddingServiceUrl}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Embedding service failed: ${response.status} ${response.statusText}`);
    }

    const result = await response.json();
    const duration = Date.now() - startTime;

    console.log(`Embeddings generated in ${duration}ms`);
    console.log(`Dimensions: ${result.dimensions || result.embeddings?.[0]?.length || 'unknown'}`);
    console.log(`Model: ${result.model || params.model || 'unknown'}`);

    // Update job with embedding metadata
    await db.updateJobMetadata(job.id, {
      embedding_dimensions: result.dimensions || result.embeddings?.[0]?.length,
      embedding_model: result.model || params.model,
      text_count: isBatch ? params.texts.length : 1,
      processing_time_ms: duration,
      gpu_used: useGpu
    });

    await completeJob(job.id, true);
    return result;
  } catch (error) {
    console.error('Embedding job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Improved context management with smart chunking
function manageContextLength(prompt, jobType = 'default') {
  const MAX_CONTEXT_LENGTH = 6000;
  const WARNING_THRESHOLD = 5000;
  
  if (prompt.length <= MAX_CONTEXT_LENGTH) {
    return { prompt, truncated: false, originalLength: prompt.length };
  }
  
  console.log(`Context length ${prompt.length} exceeds ${MAX_CONTEXT_LENGTH}, applying smart chunking`);
  
  // For daily summaries, prioritize recent messages
  if (jobType === 'yomi_daily' || jobType === 'yomi_daily_batch') {
    // Split by date sections and keep most recent
    const dateSections = prompt.split(/(\d{4}-\d{2}-\d{2}:)/);
    const recentSections = dateSections.slice(-10); // Keep last 10 sections
    const chunked = recentSections.join('');
    
    if (chunked.length <= MAX_CONTEXT_LENGTH) {
      return { prompt: chunked, truncated: true, originalLength: prompt.length };
    }
    
    // If still too long, truncate from end
    return { 
      prompt: chunked.slice(-MAX_CONTEXT_LENGTH), 
      truncated: true, 
      originalLength: prompt.length 
    };
  }
  
  // For summaries, keep most recent content
  return { 
    prompt: prompt.slice(-MAX_CONTEXT_LENGTH), 
    truncated: true, 
    originalLength: prompt.length 
  };
}

// Process Yomi summary job
async function processYomiSummaryJob(job) {
  console.log(`Processing Yomi summary job ${job.id}`);

  try {
    const params = job.params;
    const llamaUrl = LLAMA_URL;
    
    // Smart context management
    const { prompt: validatedPrompt, truncated, originalLength } = manageContextLength(params.prompt, 'yomi_summary');
    
    if (truncated) {
      console.log(`Context truncated from ${originalLength} to ${validatedPrompt.length} characters`);
    }
    
    console.log(`Calling Llama API for chat ${params.chatId}`);
    
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000); // 30 second timeout
    
    try {
      const response = await fetch(llamaUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'Phi-3-mini-4k-instruct-q4',
          messages: [{ role: 'user', content: validatedPrompt }],
          max_tokens: params.maxTokens || 50,
          temperature: params.temperature || 0.3,
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeout);
      
      if (!response.ok) {
        throw new Error(`Llama API failed: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      const result = data.choices?.[0]?.message?.content?.trim() || null;
      
      console.log(`Summary generated for chat ${params.chatId}`);
      
      // Store result using updateJobMetrics
      await db.updateJobMetrics(job.id, { result });
      await completeJob(job.id, true);
      return result;
    } catch (error) {
      clearTimeout(timeout);
      if (error.name === 'AbortError') {
        throw new Error('Llama API timeout after 60s');
      }
      throw error;
    }
  } catch (error) {
    console.error('Yomi summary job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Process Yomi daily summary job
async function processYomiDailyJob(job) {
  console.log(`Processing Yomi daily summary job ${job.id}`);

  try {
    const params = job.params;
    const llamaUrl = LLAMA_URL;
    
    // Smart context management for daily summaries
    const { prompt: validatedPrompt, truncated, originalLength } = manageContextLength(params.prompt, 'yomi_daily');
    
    if (truncated) {
      console.log(`Context truncated from ${originalLength} to ${validatedPrompt.length} characters`);
    }
    
    console.log(`Calling Llama API for daily summary of ${params.chatId} on ${params.date}`);
    
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000); // 60 second timeout for daily summaries
    
    try {
      const response = await fetch(llamaUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'Phi-3-mini-4k-instruct-q4',
          messages: [
            { role: 'system', content: 'You extract structured information from chat conversations and return valid JSON.' },
            { role: 'user', content: validatedPrompt }
          ],
          max_tokens: params.maxTokens || 300,
          temperature: params.temperature || 0.3,
          stop: ['\n\n']
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeout);
      
      if (!response.ok) {
        throw new Error(`Llama API failed: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      const content = data.choices?.[0]?.message?.content?.trim();
      if (!content) throw new Error('empty llama response');
      
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (!jsonMatch) throw new Error('no json in response');
      
      const result = JSON.parse(jsonMatch[0]);
      
      console.log(`Daily summary generated for ${params.chatId} on ${params.date}`);
      
      // Store result using updateJobMetrics
      await db.updateJobMetrics(job.id, { result: JSON.stringify(result) });
      await completeJob(job.id, true);
      return result;
    } catch (error) {
      clearTimeout(timeout);
      if (error.name === 'AbortError') {
        throw new Error('Llama API timeout after 60s');
      }
      throw error;
    }
  } catch (error) {
    console.error('Yomi daily summary job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Process Yomi batch daily summary job
async function processYomiDailyBatchJob(job) {
  console.log(`Processing Yomi batch daily summary job ${job.id}`);

  try {
    const params = job.params;
    const llamaUrl = LLAMA_URL;
    
    // Smart context management for batch daily summaries
    const { prompt: validatedPrompt, truncated, originalLength } = manageContextLength(params.prompt, 'yomi_daily_batch');
    
    if (truncated) {
      console.log(`Context truncated from ${originalLength} to ${validatedPrompt.length} characters`);
    }
    
    console.log(`Calling Llama API for batch daily summary of ${params.chatId} (${params.dates?.length || 0} dates)`);
    
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000); // 90 second timeout for batch summaries
    
    try {
      const response = await fetch(llamaUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'Phi-3-mini-4k-instruct-q4',
          messages: [
            { role: 'system', content: 'You extract structured information from chat conversations and return valid JSON with date keys.' },
            { role: 'user', content: validatedPrompt }
          ],
          max_tokens: params.maxTokens || 600,
          temperature: params.temperature || 0.3,
          stop: ['\n\n']
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeout);
      
      if (!response.ok) {
        throw new Error(`Llama API failed: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      const content = data.choices?.[0]?.message?.content?.trim();
      if (!content) throw new Error('empty llama response');
      
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (!jsonMatch) throw new Error('no json in response');
      
      const result = JSON.parse(jsonMatch[0]);
      
      console.log(`Batch daily summary generated for ${params.chatId}`);
      
      // Store result using updateJobMetrics
      await db.updateJobMetrics(job.id, { result: JSON.stringify(result) });
      await completeJob(job.id, true);
      return result;
    } catch (error) {
      clearTimeout(timeout);
      if (error.name === 'AbortError') {
        throw new Error('Llama API timeout after 90s');
      }
      throw error;
    }
  } catch (error) {
    console.error('Yomi batch daily summary job failed:', error);
    await completeJob(job.id, false, error.message);
    throw error;
  }
}

// Export functions for use by queue processor
export { processNextJob, completeJob, getQueueStatus, processImagen2Job, processLlamaJob, processTxt2vidJob, processEmbeddingJob, processYomiSummaryJob, processYomiDailyJob, processYomiDailyBatchJob };

// CLI interface
const args = process.argv.slice(2);
const command = args[0];

switch (command) {
  case 'next':
    processNextJob().then(job => {
      if (job) {
        console.log(JSON.stringify(job, null, 2));
      }
    });
    break;

  case 'complete':
    const jobId = parseInt(args[1], 10);
    const success = args[2] !== 'false';
    const error = args[3] || null;
    completeJob(jobId, success, error);
    break;

  case 'status':
    getQueueStatus().then(status => {
      console.log(JSON.stringify(status, null, 2));
    });
    break;

  case 'process':
    processNextJob().then(job => {
      if (job) {
        if (job.type === 'imagen2') {
          processImagen2Job(job);
        } else if (job.type === 'llama') {
          processLlamaJob(job);
        } else if (job.type === 'txt2vid') {
          processTxt2vidJob(job);
        } else if (job.type === 'embedding') {
          processEmbeddingJob(job);
        } else if (job.type === 'yomi_summary') {
          processYomiSummaryJob(job);
        } else if (job.type === 'yomi_daily') {
          processYomiDailyJob(job);
        } else if (job.type === 'yomi_daily_batch') {
          processYomiDailyBatchJob(job);
        } else {
          console.log(`Unknown job type: ${job.type}`);
          completeJob(job.id, false, `Unknown job type: ${job.type}`);
        }
      }
    });
    break;

  default:
    console.log('Usage:');
    console.log('  node orchestrator.mjs next       - Get next pending job');
    console.log('  node orchestrator.mjs complete <id> [success] [error] - Mark job complete');
    console.log('  node orchestrator.mjs status     - Get queue status');
    console.log('  node orchestrator.mjs process    - Process next job (imagen2 only)');
}
