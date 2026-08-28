import { createJob, getJob, updateJobStatus } from '../gpu-queue/db.mjs';

const LLAMA_URL = process.env.LLAMA_URL || 'http://localhost:8001/v1/chat/completions';

// Submit a summary job to GPU queue
export async function submitSummaryJob(chatId, prompt, type = 'yomi_summary') {
  const params = {
    chatId,
    prompt,
    type: 'summary',
    model: 'Phi-3-mini-4k-instruct-q4',
    maxTokens: 50,
    temperature: 0.3
  };
  
  const job = await createJob(type, params);
  console.log(`Submitted ${type} job for ${chatId}: job #${job.id}`);
  return job.id;
}

// Submit a daily summary job to GPU queue
export async function submitDailySummaryJob(chatId, date, prompt, type = 'yomi_daily') {
  const params = {
    chatId,
    date,
    prompt,
    type: 'daily_summary',
    model: 'Phi-3-mini-4k-instruct-q4',
    maxTokens: 300,
    temperature: 0.3
  };
  
  const job = await createJob(type, params);
  console.log(`Submitted ${type} job for ${chatId} on ${date}: job #${job.id}`);
  return job.id;
}

// Submit a batch daily summary job to GPU queue
export async function submitBatchDailySummaryJob(chatId, dates, prompt, type = 'yomi_daily_batch') {
  const params = {
    chatId,
    dates,
    prompt,
    type: 'batch_daily_summary',
    model: 'Phi-3-mini-4k-instruct-q4',
    maxTokens: 600,
    temperature: 0.3
  };
  
  const job = await createJob(type, params);
  console.log(`Submitted ${type} job for ${chatId} (${dates.length} dates): job #${job.id}`);
  return job.id;
}

// Wait for job completion and return result
export async function waitForJob(jobId, timeout = 300000) {
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeout) {
    const job = await getJob(jobId);
    
    if (!job) {
      throw new Error(`Job ${jobId} not found`);
    }
    
    if (job.status === 'completed') {
      const result = job.result ? JSON.parse(job.result) : null;
      return { success: true, result, job };
    }
    
    if (job.status === 'failed') {
      throw new Error(`Job ${jobId} failed: ${job.error || 'Unknown error'}`);
    }
    
    if (job.status === 'cancelled') {
      throw new Error(`Job ${jobId} was cancelled`);
    }
    
    // Wait 2 seconds before checking again
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  
  throw new Error(`Job ${jobId} timed out after ${timeout}ms`);
}

// Direct Llama API call (fallback when GPU queue not available)
export async function directLlamaCall(prompt, options = {}) {
  const {
    model = 'Phi-3-mini-4k-instruct-q4',
    maxTokens = 300,
    temperature = 0.3,
    systemPrompt = 'You extract structured information from chat conversations and return valid JSON.'
  } = options;
  
  const res = await fetch(LLAMA_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: prompt }
      ],
      temperature,
      max_tokens: maxTokens,
      stop: ['\n\n']
    })
  });
  
  if (!res.ok) throw new Error(`Llama API error: ${res.status}`);
  
  const data = await res.json();
  const content = data.choices?.[0]?.message?.content?.trim();
  if (!content) throw new Error('empty llama response');
  
  const jsonMatch = content.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error('no json in response');
  
  try {
    return JSON.parse(jsonMatch[0]);
  } catch {
    throw new Error('invalid json in response');
  }
}

// Hybrid approach: try GPU queue first, fallback to direct API
export async function smartLlamaCall(prompt, options = {}, useQueue = true) {
  if (!useQueue) {
    return await directLlamaCall(prompt, options);
  }
  
  try {
    // Try GPU queue approach
    const jobId = await submitSummaryJob('temp', prompt, 'yomi_summary');
    const { result } = await waitForJob(jobId, 60000); // 1 minute timeout
    return result;
  } catch (queueError) {
    console.log(`GPU queue failed: ${queueError.message}, falling back to direct API`);
    // Fallback to direct API
    return await directLlamaCall(prompt, options);
  }
}