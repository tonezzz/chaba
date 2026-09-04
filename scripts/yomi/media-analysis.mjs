/**
 * Media analysis module for Yomi
 * Handles media analysis job creation, status tracking, and listing
 * Consolidated from yomi-api.mjs for better separation of concerns
 */

import { spawn } from 'node:child_process';
import pool from './db.mjs';

const SCRIPT_DIR = process.env.SCRIPT_DIR || '/home/tony/CascadeProjects/chaba-tony-dell/scripts/yomi';

/**
 * Spawn a Node.js script with the given arguments and environment
 * @param {string} script - Path to the script to run
 * @param {Array} args - Arguments to pass to the script
 * @param {Object} options - Options including env variables
 * @returns {Promise<{code: number, out: string, err: string}>}
 */
function spawnNode(script, args, options = {}) {
  return new Promise((resolve, reject) => {
    const nodePath = process.env.NODE_BINARY_PATH || '/usr/local/bin/node';
    const child = spawn(nodePath, [script, ...args], {
      cwd: SCRIPT_DIR,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: options.env || process.env,
    });
    let out = '';
    let err = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', d => { out += d; });
    child.stderr.on('data', d => { err += d; });
    child.on('error', reject);
    child.on('close', code => resolve({ code, out, err }));
  });
}

/**
 * Validate media analysis request parameters
 * @param {Object} params - Request parameters
 * @returns {Object} - Validation result with isValid and error
 */
function validateMediaRequest(params) {
  const { chatId, messageId, mediaType } = params;
  
  if (!chatId || !messageId || !mediaType) {
    return { 
      isValid: false, 
      error: 'chatId, messageId, and mediaType required' 
    };
  }
  
  return { isValid: true };
}

/**
 * Check if a message exists and has media
 * @param {string} messageId - Message ID
 * @param {string} chatId - Chat ID
 * @returns {Promise<Object>} - Message data or error
 */
async function checkMessageMedia(messageId, chatId) {
  const { rows } = await pool.query(
    'SELECT media_type, media_path FROM messages WHERE message_id = $1 AND chat_id = $2',
    [messageId, chatId]
  );
  
  if (rows.length === 0) {
    return { exists: false, error: 'message not found' };
  }
  
  if (!rows[0].media_type || !rows[0].media_path) {
    return { exists: false, error: 'message has no media' };
  }
  
  return { exists: true, message: rows[0] };
}

/**
 * Create a media analysis job
 * @param {string} chatId - Chat ID
 * @param {string} messageId - Message ID
 * @param {string} mediaType - Media type (image/video)
 * @returns {Promise<Object>} - Job data with ID
 */
async function createAnalysisJob(chatId, messageId, mediaType) {
  const { rows } = await pool.query(
    `INSERT INTO media_analysis_jobs (chat_id, message_id, media_type, status)
     VALUES ($1, $2, $3, 'pending')
     RETURNING id`,
    [chatId, messageId, mediaType]
  );
  
  return { jobId: rows[0].id };
}

/**
 * Build environment variables for the analysis worker
 * @param {number} jobId - Job ID
 * @returns {Object} - Environment variables
 */
function buildWorkerEnv(jobId) {
  return {
    ...process.env,
    JOB_ID: String(jobId),
    GEMINI_API_KEY: process.env.GEMINI_API_KEY,
    GEMINI_VISION_MODEL_PRIMARY: process.env.GEMINI_VISION_MODEL_PRIMARY || 'gemma-4-31b-it',
    GEMINI_VISION_MODEL_FALLBACK: process.env.GEMINI_VISION_MODEL_FALLBACK || 'gemma-4-26b-a4b-it',
    CONTEXT_MESSAGES_BEFORE: process.env.CONTEXT_MESSAGES_BEFORE || '3',
    CONTEXT_MESSAGES_AFTER: process.env.CONTEXT_MESSAGES_AFTER || '3',
    POSTGRES_USER: process.env.POSTGRES_USER,
    POSTGRES_PASSWORD: process.env.POSTGRES_PASSWORD,
    POSTGRES_DB: process.env.POSTGRES_DB,
    POSTGRES_HOST: process.env.POSTGRES_HOST,
    POSTGRES_PORT: process.env.POSTGRES_PORT
  };
}

/**
 * Spawn the background analysis worker
 * @param {number} jobId - Job ID
 * @param {Object} envVars - Environment variables
 * @returns {Promise<void>}
 */
async function spawnAnalysisWorker(jobId, envVars) {
  console.log('Spawning analyze-media with env:', {
    GEMINI_API_KEY: envVars.GEMINI_API_KEY ? 'SET' : 'NOT SET',
    GEMINI_VISION_MODEL_PRIMARY: envVars.GEMINI_VISION_MODEL_PRIMARY,
    GEMINI_VISION_MODEL_FALLBACK: envVars.GEMINI_VISION_MODEL_FALLBACK,
    CONTEXT_MESSAGES_BEFORE: envVars.CONTEXT_MESSAGES_BEFORE,
    CONTEXT_MESSAGES_AFTER: envVars.CONTEXT_MESSAGES_AFTER,
    POSTGRES_USER: envVars.POSTGRES_USER,
    POSTGRES_DB: envVars.POSTGRES_DB
  });
  
  try {
    await spawnNode(`${SCRIPT_DIR}/analyze-media.mjs`, [String(jobId)], { 
      env: envVars
    });
  } catch (err) {
    console.error(`Media analysis job ${jobId} failed to start:`, err);
  }
}

/**
 * Handle media analysis job creation
 * @param {Object} req - HTTP request object
 * @param {Object} res - HTTP response object
 * @param {Function} sendJson - Function to send JSON responses
 */
export async function handleMediaAnalysis(req, res, sendJson) {
  const body = await new Promise(resolve => {
    let data = '';
    req.on('data', chunk => data += chunk);
    req.on('end', () => resolve(data));
  });
  
  let params;
  try {
    params = JSON.parse(body);
  } catch {
    return sendJson(res, 400, { ok: false, error: 'invalid JSON body' });
  }
  
  // Validate request
  const validation = validateMediaRequest(params);
  if (!validation.isValid) {
    return sendJson(res, 400, { ok: false, error: validation.error });
  }
  
  const { chatId, messageId, mediaType } = params;
  
  // Check message exists and has media
  const messageCheck = await checkMessageMedia(messageId, chatId);
  if (!messageCheck.exists) {
    const statusCode = messageCheck.error === 'message not found' ? 404 : 400;
    return sendJson(res, statusCode, { ok: false, error: messageCheck.error });
  }
  
  // Create job record
  const { jobId } = await createAnalysisJob(chatId, messageId, mediaType);
  
  // Trigger background analysis
  const envVars = buildWorkerEnv(jobId);
  spawnAnalysisWorker(jobId, envVars);
  
  sendJson(res, 200, { ok: true, jobId, status: 'pending' });
}

/**
 * Handle media analysis job status query
 * @param {string} jobId - Job ID
 * @param {Object} res - HTTP response object
 * @param {Function} sendJson - Function to send JSON responses
 */
export async function handleMediaAnalysisStatus(jobId, res, sendJson) {
  const { rows } = await pool.query(
    'SELECT * FROM media_analysis_jobs WHERE id = $1',
    [parseInt(jobId, 10)]
  );
  
  if (rows.length === 0) {
    return sendJson(res, 404, { ok: false, error: 'job not found' });
  }
  
  const job = rows[0];
  
  // If job failed, return error response
  if (job.status === 'failed') {
    return sendJson(res, 500, { 
      ok: false, 
      error: job.error_message || 'Analysis failed',
      job: {
        id: job.id,
        status: job.status,
        errorMessage: job.error_message
      }
    });
  }
  
  // If job is still running, return pending status
  if (job.status === 'running' || job.status === 'pending') {
    return sendJson(res, 200, {
      ok: true,
      job: {
        id: job.id,
        chatId: job.chat_id,
        messageId: job.message_id,
        mediaType: job.media_type,
        status: job.status,
        startedAt: job.started_at,
        createdAt: job.created_at,
        updatedAt: job.updated_at
      }
    });
  }
  
  // Job completed successfully
  sendJson(res, 200, {
    ok: true,
    job: {
      id: job.id,
      chatId: job.chat_id,
      messageId: job.message_id,
      mediaType: job.media_type,
      status: job.status,
      analysisResult: job.analysis_result,
      modelUsed: job.model_used,
      startedAt: job.started_at,
      completedAt: job.completed_at,
      errorMessage: job.error_message,
      tokensUsed: job.tokens_used,
      costUsd: job.cost_usd,
      createdAt: job.created_at,
      updatedAt: job.updated_at
    }
  });
}

/**
 * Handle media analysis jobs listing
 * @param {Object} url - URL object with search parameters
 * @param {Object} res - HTTP response object
 * @param {Function} sendJson - Function to send JSON responses
 */
export async function handleMediaAnalysisJobs(url, res, sendJson) {
  const limit = Math.min(parseInt(url.searchParams.get('limit') || '50', 10), 200);
  const status = url.searchParams.get('status');
  const chatId = url.searchParams.get('chat');
  
  let query = 'SELECT * FROM media_analysis_jobs';
  const params = [];
  const conditions = [];
  
  if (status) {
    conditions.push('status = $' + (params.length + 1));
    params.push(status);
  }
  
  if (chatId) {
    conditions.push('chat_id = $' + (params.length + 1));
    params.push(chatId);
  }
  
  if (conditions.length > 0) {
    query += ' WHERE ' + conditions.join(' AND ');
  }
  
  query += ' ORDER BY created_at DESC LIMIT $' + (params.length + 1);
  params.push(limit);
  
  const { rows } = await pool.query(query, params);
  
  sendJson(res, 200, {
    ok: true,
    jobs: rows.map(job => ({
      id: job.id,
      chatId: job.chat_id,
      messageId: job.message_id,
      mediaType: job.media_type,
      status: job.status,
      analysisResult: job.analysis_result,
      modelUsed: job.model_used,
      startedAt: job.started_at,
      completedAt: job.completed_at,
      errorMessage: job.error_message,
      tokensUsed: job.tokens_used,
      costUsd: job.cost_usd,
      createdAt: job.created_at,
      updatedAt: job.updated_at
    }))
  });
}
