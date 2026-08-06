import { createServer } from 'node:http';
import { spawn, execSync } from 'node:child_process';
import { existsSync, createReadStream, readdirSync } from 'node:fs';
import { summaryRateLimiter, dailyRateLimiter, summaryCircuitBreaker, dailyCircuitBreaker } from './llama-rate-limiter.mjs';
import pool from './db.mjs';

const PORT = parseInt(process.env.YOMI_API_PORT || '3000', 10);
const HOST = process.env.YOMI_API_HOST || '0.0.0.0';
const SCRIPT_DIR = '/home/tony/CascadeProjects/chaba/scripts/yomi';
const MEDIA_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/media';
const WEAVIATE_SEARCH_URL = process.env.WEAVIATE_SEARCH_URL || 'http://localhost:3002';
const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const EMBEDDING_URL = process.env.EMBEDDING_SERVICE_URL || 'http://localhost:5000';

const EXT_TO_MIME = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif',
  webp: 'image/webp', heic: 'image/heic', heif: 'image/heif',
  mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime', '3gp': 'video/3gpp',
  mp3: 'audio/mpeg', m4a: 'audio/mp4', ogg: 'audio/ogg', aac: 'audio/aac', amr: 'audio/amr',
  pdf: 'application/pdf', zip: 'application/zip',
};

function mimeFromExt(ext) {
  return EXT_TO_MIME[(ext || '').toLowerCase()] || 'application/octet-stream';
}

function sendJson(res, status, obj) {
  if (res.writableEnded) return;
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function serveCached(chatId, messageId, res) {
  const dir = `${MEDIA_DIR}/${chatId}`;
  if (!existsSync(dir)) return false;
  const file = readdirSync(dir).find(f => f.startsWith(`${messageId}.`));
  if (!file) return false;
  const ext = file.split('.').pop();
  const mime = mimeFromExt(ext);
  const filePath = `${dir}/${file}`;
  res.writeHead(200, {
    'Content-Type': mime,
    'Cache-Control': 'public, max-age=31536000, immutable',
  });
  createReadStream(filePath).pipe(res);
  return true;
}

function spawnNode(script, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn('/usr/bin/node', [script, ...args], {
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

async function handleRefresh(chatId, res, force = false) {
  const args = ['--chat', chatId];
  if (force) args.push('--force');
  
  const { code, err } = await spawnNode(`${SCRIPT_DIR}/update-conversations.mjs`, args);
  if (code === 0) {
    sendJson(res, 200, { ok: true, forced: force });
  } else {
    sendJson(res, 500, { ok: false, error: err.trim() || 'export failed' });
  }
}

async function handleRefreshAll(res, force = false) {
  const args = force ? [] : ['--recent'];
  
  const { code, out, err } = await spawnNode(`${SCRIPT_DIR}/update-conversations.mjs`, args);
  if (code === 0) {
    sendJson(res, 200, { ok: true, forced: force, output: out });
  } else {
    sendJson(res, 500, { ok: false, error: err.trim() || 'export failed' });
  }
}

async function handleFetch(chatId, res) {
  const args = chatId ? ['--chat', chatId] : [];
  const limitIdx = process.argv.indexOf('--limit');
  if (limitIdx !== -1) {
    args.push('--limit', process.argv[limitIdx + 1]);
  }
  
  const { code, out, err } = await spawnNode(`${SCRIPT_DIR}/fetch-conversations.mjs`, args);
  if (code === 0) {
    sendJson(res, 200, { ok: true, output: out });
  } else {
    sendJson(res, 500, { ok: false, error: err.trim() || 'fetch failed' });
  }
}

async function handleProcess(chatId, res, force = false) {
  const args = chatId ? ['--chat', chatId] : [];
  if (force) args.push('--force');
  
  const { code, out, err } = await spawnNode(`${SCRIPT_DIR}/process-conversations.mjs`, args);
  if (code === 0) {
    sendJson(res, 200, { ok: true, forced: force, output: out });
  } else {
    sendJson(res, 500, { ok: false, error: err.trim() || 'process failed' });
  }
}

async function handleConversations(res) {
  const { rows } = await pool.query(`
    SELECT chat_id AS id, name, is_group AS "isGroup", category, category_source AS "categorySource",
           unread, last_message_time AS "lastMessageTime", last_preview AS "lastPreview", summary
    FROM conversations
    ORDER BY last_message_time DESC NULLS LAST
  `);
  sendJson(res, 200, { generatedAt: new Date().toISOString(), conversations: rows });
}

async function handleLastUpdated(res) {
  const { rows } = await pool.query(`
    SELECT MAX(updated_at) AS last_updated
    FROM conversations
  `);
  const lastUpdated = rows[0]?.last_updated || null;
  sendJson(res, 200, { lastUpdated });
}

async function handleSendMessage(req, res) {
  let body = '';
  for await (const chunk of req) body += chunk.toString();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    return sendJson(res, 400, { ok: false, error: 'invalid JSON' });
  }
  const { chatId, text } = data;
  if (!chatId || !text) {
    return sendJson(res, 400, { ok: false, error: 'chatId and text required' });
  }
  const { code, err } = await spawnNode(`${SCRIPT_DIR}/send-message.mjs`, [chatId, text]);
  if (code === 0) {
    sendJson(res, 200, { ok: true });
  } else {
    sendJson(res, 500, { ok: false, error: err.trim() || 'send failed' });
  }
}

async function handleDailySummaries(url, res) {
  const chatId = url.searchParams.get('chat');
  if (!chatId) return sendJson(res, 400, { ok: false, error: 'chat parameter required' });
  
  const startDate = url.searchParams.get('startDate');
  const endDate = url.searchParams.get('endDate');
  
  let query = `
    SELECT date::text, events, actions, topics, message_count, updated_at
    FROM daily_summaries
    WHERE chat_id = $1
  `;
  let params = [chatId];
  let paramIndex = 2;
  
  if (startDate) {
    query += ` AND date >= $${paramIndex}`;
    params.push(startDate);
    paramIndex++;
  }
  
  if (endDate) {
    query += ` AND date <= $${paramIndex}`;
    params.push(endDate);
    paramIndex++;
  }
  
  query += ` ORDER BY date DESC`;
  
  const { rows } = await pool.query(query, params);
  
  // Database stores Thailand calendar dates as DATE type (YYYY-MM-DD)
  // No conversion needed - return date as-is
  const summaries = rows.map(r => ({
    ...r,
    date: r.date // Return Thailand calendar date as-is
  }));
  
  sendJson(res, 200, { chatId, summaries });
}

async function handleResummarize(req, res) {
  let body = '';
  for await (const chunk of req) body += chunk.toString();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    return sendJson(res, 400, { ok: false, error: 'invalid JSON' });
  }
  
  const { chatIds, forceAll, targetDate } = data;
  
  try {
    // Trigger re-summarization by calling update-conversations with Gemini enabled
    const env = { ...process.env, USE_GEMINI: '1' };
    const args = chatIds ? chatIds.map(id => ['--chat', id]).flat() : (forceAll ? [] : ['--recent']);
    
    // Add target date if specified
    if (targetDate) {
      args.push('--date', targetDate);
    }
    
    const { code, out, err } = await spawnNode(`${SCRIPT_DIR}/update-conversations.mjs`, args, { env });
    
    if (code === 0) {
      sendJson(res, 200, { ok: true, message: 'Re-summarization initiated with Gemini' });
    } else {
      sendJson(res, 500, { ok: false, error: err.trim() || 're-summarization failed' });
    }
  } catch (error) {
    sendJson(res, 500, { ok: false, error: error.message });
  }
}

async function handleSummaryQuality(res) {
  try {
    const { rows: qualityStats } = await pool.query(`
      SELECT 
        chat_id,
        name,
        summary,
        summary_quality,
        summary_generated_at,
        summary_retry_count,
        summary_error_message
      FROM conversations
      WHERE summary IS NOT NULL
      ORDER BY summary_quality ASC NULLS LAST
    `);

    const { rows: overallStats } = await pool.query(`
      SELECT 
        COUNT(*) as total,
        COUNT(CASE WHEN summary_quality >= 80 THEN 1 END) as excellent,
        COUNT(CASE WHEN summary_quality >= 60 AND summary_quality < 80 THEN 1 END) as good,
        COUNT(CASE WHEN summary_quality >= 30 AND summary_quality < 60 THEN 1 END) as medium,
        COUNT(CASE WHEN summary_quality > 0 AND summary_quality < 30 THEN 1 END) as poor,
        COUNT(CASE WHEN summary_quality = 0 THEN 1 END) as failed,
        AVG(summary_quality) as avg_quality
      FROM conversations
      WHERE summary IS NOT NULL
    `);

    sendJson(res, 200, {
      overall: overallStats[0] || {},
      conversations: qualityStats,
      generatedAt: new Date().toISOString()
    });
  } catch (err) {
    sendJson(res, 500, { ok: false, error: err.message });
  }
}

async function handleActivityStatus(res) {
  try {
    // Get process info
    const processInfo = {
      pid: process.pid,
      uptime: process.uptime(),
      memory: process.memoryUsage(),
      platform: process.platform,
      nodeVersion: process.version
    };

    // Get recent database activity
    const { rows: recentUpdates } = await pool.query(`
      SELECT 
        chat_id,
        name,
        updated_at,
        summary_quality
      FROM conversations
      ORDER BY updated_at DESC
      LIMIT 10
    `);

    // Get activity metrics
    const { rows: activityMetrics } = await pool.query(`
      SELECT 
        COUNT(*) as total_updates,
        COUNT(CASE WHEN updated_at > NOW() - INTERVAL '1 hour' THEN 1 END) as updates_last_hour,
        COUNT(CASE WHEN updated_at > NOW() - INTERVAL '24 hours' THEN 1 END) as updates_last_day,
        MAX(updated_at) as last_update
      FROM conversations
    `);

    // Get daily summary activity
    const { rows: dailyActivity } = await pool.query(`
      SELECT 
        COUNT(*) as total_summaries,
        COUNT(DISTINCT chat_id) as unique_chats,
        MAX(updated_at) as last_summary_update
      FROM daily_summaries
    `);

    // Get system health
    const { rows: systemHealth } = await pool.query(`
      SELECT 
        COUNT(*) as total_conversations,
        COUNT(CASE WHEN summary IS NOT NULL THEN 1 END) as with_summary,
        COUNT(CASE WHEN category IS NOT NULL THEN 1 END) as with_category,
        MAX(last_message_time) as latest_message
      FROM conversations
    `);

    // Get process status from file
    let processStatus = null;
    try {
      const STATUS_FILE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json';
      const { existsSync, readFileSync } = await import('node:fs');
      if (existsSync(STATUS_FILE)) {
        processStatus = JSON.parse(readFileSync(STATUS_FILE, 'utf-8'));
      }
    } catch (err) {
      // Ignore errors reading status file
    }

    // Get rate limiter and circuit breaker status
    const rateLimiterStatus = {
      summary: {
        rateLimiter: summaryRateLimiter.getStats(),
        circuitBreaker: summaryCircuitBreaker.getState()
      },
      daily: {
        rateLimiter: dailyRateLimiter.getStats(),
        circuitBreaker: dailyCircuitBreaker.getState()
      }
    };

    // Get processing statistics from database
    let processingStats = null;
    try {
      const { rows } = await pool.query(`
        SELECT 
          COUNT(*) as total_conversations,
          COUNT(CASE WHEN summary IS NOT NULL THEN 1 END) as with_summary,
          COUNT(CASE WHEN summary_quality >= 80 THEN 1 END) as high_quality,
          COUNT(CASE WHEN summary_quality < 50 THEN 1 END) as low_quality,
          AVG(summary_quality) as avg_quality,
          MAX(summary_generated_at) as last_summary_time,
          COUNT(CASE WHEN updated_at > NOW() - INTERVAL '1 hour' THEN 1 END) as updated_last_hour,
          COUNT(CASE WHEN updated_at > NOW() - INTERVAL '24 hours' THEN 1 END) as updated_last_day
        FROM conversations
      `);
      processingStats = rows[0];
    } catch (err) {
      processingStats = { error: 'Processing stats unavailable' };
    }

    // Get GPU status
    let gpuStatus = null;
    try {
      const { execSync } = await import('node:child_process');
      const gpuOutput = execSync('nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits', { encoding: 'utf8' });
      const [util, memUsed, memTotal, temp] = gpuOutput.trim().split(',').map(s => s.trim());
      gpuStatus = {
        utilization: parseInt(util) || 0,
        memoryUsed: parseInt(memUsed) || 0,
        memoryTotal: parseInt(memTotal) || 0,
        memoryPercent: Math.round((parseInt(memUsed) / parseInt(memTotal)) * 100) || 0,
        temperature: parseInt(temp) || null
      };
    } catch (err) {
      gpuStatus = { error: 'GPU monitoring unavailable' };
    }

    // Determine overall health
    const anyCircuitBreakerOpen = rateLimiterStatus.summary.circuitBreaker.state === 'open' || 
                              rateLimiterStatus.daily.circuitBreaker.state === 'open';
    const highGpuTemp = gpuStatus.temperature && gpuStatus.temperature > 85;
    const elevatedGpuTemp = gpuStatus.temperature && gpuStatus.temperature > 80;
    const highGpuMemory = gpuStatus.memoryPercent && gpuStatus.memoryPercent > 90;

    const healthStatus = {
      healthy: !anyCircuitBreakerOpen && !highGpuTemp && !highGpuMemory,
      message: anyCircuitBreakerOpen ? 'Circuit breaker active - GPU overloaded' :
               highGpuTemp ? 'High GPU temperature' :
               elevatedGpuTemp ? 'Elevated GPU temperature' :
               highGpuMemory ? 'High GPU memory usage' :
               'All systems operational'
    };

    sendJson(res, 200, {
      process: processInfo,
      recentActivity: recentUpdates,
      metrics: {
        database: activityMetrics[0] || {},
        dailySummaries: dailyActivity[0] || {},
        system: systemHealth[0] || {},
        processing: processingStats
      },
      processStatus,
      rateLimiter: rateLimiterStatus,
      gpu: gpuStatus,
      status: healthStatus,
      generatedAt: new Date().toISOString()
    });
  } catch (err) {
    sendJson(res, 500, { ok: false, error: err.message });
  }
}

async function handleSummarizationStatus(res) {
  try {
    // Get overall statistics with quality metrics
    const { rows: totalStats } = await pool.query(`
      SELECT 
        COUNT(*) as total_conversations,
        COUNT(CASE WHEN summary IS NOT NULL AND summary != '' THEN 1 END) as with_summary,
        COUNT(CASE WHEN summary_quality > 0 THEN 1 END) as with_meaningful_summary,
        COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as with_category,
        MAX(last_message_time) as latest_message_time,
        AVG(summary_quality) as avg_summary_quality
      FROM conversations
    `);

    // Get daily summary statistics
    const { rows: dailyStats } = await pool.query(`
      SELECT 
        COUNT(DISTINCT chat_id) as conversations_with_summaries,
        COUNT(*) as total_summaries,
        MAX(date) as latest_summary_date,
        MAX(updated_at) as last_updated
      FROM daily_summaries
    `);

    // Get recent summarization activity
    const { rows: recentActivity } = await pool.query(`
      SELECT chat_id, date, message_count, updated_at
      FROM daily_summaries
      ORDER BY updated_at DESC
      LIMIT 5
    `);

    // Get quality distribution
    const { rows: qualityDist } = await pool.query(`
      SELECT 
        summary_quality,
        COUNT(*) as count
      FROM conversations
      WHERE summary_quality IS NOT NULL
      GROUP BY summary_quality
      ORDER BY summary_quality
    `);

    const stats = totalStats[0] || {};
    const daily = dailyStats[0] || {};

    sendJson(res, 200, {
      conversations: {
        total: parseInt(stats.total_conversations) || 0,
        withSummary: parseInt(stats.with_summary) || 0,
        withMeaningfulSummary: parseInt(stats.with_meaningful_summary) || 0,
        withCategory: parseInt(stats.with_category) || 0,
        latestMessageTime: stats.latest_message_time,
        avgSummaryQuality: Math.round(stats.avg_summary_quality) || 0
      },
      dailySummaries: {
        conversationsWithSummaries: parseInt(daily.conversations_with_summaries) || 0,
        totalSummaries: parseInt(daily.total_summaries) || 0,
        latestSummaryDate: daily.latest_summary_date,
        lastUpdated: daily.last_updated
      },
      recentActivity: recentActivity,
      qualityDistribution: qualityDist,
      generatedAt: new Date().toISOString()
    });
  } catch (err) {
    sendJson(res, 500, { ok: false, error: err.message });
  }
}

async function handleRateLimiterStatus(res) {
  try {
    const summaryStats = summaryRateLimiter.getStats();
    const dailyStats = dailyRateLimiter.getStats();
    const summaryCB = summaryCircuitBreaker.getState();
    const dailyCB = dailyCircuitBreaker.getState();
    
    // Get GPU status
    let gpuStatus = null;
    try {
      const { execSync } = await import('node:child_process');
      const gpuOutput = execSync('nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits', { encoding: 'utf8' });
      const [util, memUsed, memTotal, temp] = gpuOutput.trim().split(',').map(s => s.trim());
      gpuStatus = {
        utilization: parseInt(util) || 0,
        memoryUsed: parseInt(memUsed) || 0,
        memoryTotal: parseInt(memTotal) || 0,
        memoryPercent: Math.round((parseInt(memUsed) / parseInt(memTotal)) * 100) || 0,
        temperature: parseInt(temp) || null
      };
    } catch (err) {
      gpuStatus = { error: 'GPU monitoring unavailable' };
    }
    
    sendJson(res, 200, {
      summary: {
        rateLimiter: summaryStats,
        circuitBreaker: summaryCB
      },
      daily: {
        rateLimiter: dailyStats,
        circuitBreaker: dailyCB
      },
      gpu: gpuStatus,
      generatedAt: new Date().toISOString()
    });
  } catch (err) {
    sendJson(res, 500, { ok: false, error: err.message });
  }
}

async function handleMessages(chatId, url, res) {
  const before = url.searchParams.get('before');
  const limit = Math.min(parseInt(url.searchParams.get('limit') || '10000', 10), 10000);
  const startDate = url.searchParams.get('startDate');
  const endDate = url.searchParams.get('endDate');
  
  let query = `SELECT data, media_analysis FROM messages WHERE chat_id = $1`;
  let params = [chatId];
  let paramIndex = 2;
  
  // Add date range filtering for daily2 page
  if (startDate) {
    query += ` AND delivered_time >= $${paramIndex}`;
    params.push(parseInt(startDate, 10));
    paramIndex++;
  }
  
  if (endDate) {
    query += ` AND delivered_time <= $${paramIndex}`;
    params.push(parseInt(endDate, 10));
    paramIndex++;
  }
  
  // Only add before clause if it's provided (for pagination)
  if (before) {
    query += ` AND delivered_time < $${paramIndex}`;
    params.push(parseInt(before, 10));
    paramIndex++;
  }
  
  query += ` ORDER BY delivered_time DESC LIMIT $${paramIndex}`;
  params.push(limit);
  
  const { rows } = await pool.query(query, params);
  
  // Merge media_analysis into data objects
  const messages = rows.map(r => {
    const data = r.data;
    if (r.media_analysis && !data.mediaAnalysis) {
      data.mediaAnalysis = r.media_analysis;
    }
    return data;
  });
  
  sendJson(res, 200, { generatedAt: new Date().toISOString(), messages });
}

async function handleMedia(chatId, messageId, res) {
  if (serveCached(chatId, messageId, res)) return;
  const { code, out, err } = await spawnNode(`${SCRIPT_DIR}/download-media.mjs`, [chatId, messageId]);
  if (code !== 0) {
    sendJson(res, 500, { ok: false, error: err.trim() || 'media download failed' });
    return;
  }
  let info;
  try {
    info = JSON.parse(out.split('\n').filter(Boolean).pop());
  } catch {
    sendJson(res, 500, { ok: false, error: 'invalid media response' });
    return;
  }
  if (info.unavailable) {
    sendJson(res, 404, { ok: false, error: info.error || 'media unavailable' });
    return;
  }
  if (info.error || !info.fileName) {
    sendJson(res, 500, { ok: false, error: info.error || 'missing media filename' });
    return;
  }
  const filePath = `${MEDIA_DIR}/${chatId}/${info.fileName}`;
  if (!existsSync(filePath)) {
    sendJson(res, 500, { ok: false, error: 'media file not found after download' });
    return;
  }
  const ext = info.fileName.split('.').pop();
  const mime = info.mime || mimeFromExt(ext);
  res.writeHead(200, {
    'Content-Type': mime,
    'Cache-Control': 'public, max-age=31536000, immutable',
  });
  createReadStream(filePath).pipe(res);
}

async function handleMediaAnalysis(req, res) {
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
  
  const { chatId, messageId, mediaType } = params;
  if (!chatId || !messageId || !mediaType) {
    return sendJson(res, 400, { ok: false, error: 'chatId, messageId, and mediaType required' });
  }
  
  // Check if message exists and has media
  const { rows } = await pool.query(
    'SELECT media_type, media_path FROM messages WHERE message_id = $1 AND chat_id = $2',
    [messageId, chatId]
  );
  
  if (rows.length === 0) {
    return sendJson(res, 404, { ok: false, error: 'message not found' });
  }
  
  if (!rows[0].media_type || !rows[0].media_path) {
    return sendJson(res, 400, { ok: false, error: 'message has no media' });
  }
  
  // Create job record
  const { rows: jobRows } = await pool.query(
    `INSERT INTO media_analysis_jobs (chat_id, message_id, media_type, status)
     VALUES ($1, $2, $3, 'pending')
     RETURNING id`,
    [chatId, messageId, mediaType]
  );
  
  const jobId = jobRows[0].id;
  
  // Trigger background analysis
  spawnNode(`${SCRIPT_DIR}/analyze-media.mjs`, [String(jobId)], { 
    env: { ...process.env, JOB_ID: String(jobId) } 
  }).catch(err => {
    console.error(`Media analysis job ${jobId} failed to start:`, err);
  });
  
  sendJson(res, 200, { ok: true, jobId, status: 'pending' });
}

async function handleMediaAnalysisStatus(jobId, res) {
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

async function handleMediaAnalysisJobs(url, res) {
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

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (url.pathname === '/api/yomi/health') {
    return sendJson(res, 200, { ok: true });
  }

  if (url.pathname === '/api/yomi/last-updated' && req.method === 'GET') {
    try {
      await handleLastUpdated(res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/send' && req.method === 'POST') {
    try {
      await handleSendMessage(req, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/daily' && req.method === 'GET') {
    try {
      await handleDailySummaries(url, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/summarization-status' && req.method === 'GET') {
    try {
      await handleSummarizationStatus(res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/resummarize' && req.method === 'POST') {
    try {
      await handleResummarize(req, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/summary-quality' && req.method === 'GET') {
    try {
      await handleSummaryQuality(res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/activity-status' && req.method === 'GET') {
    try {
      await handleActivityStatus(res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/rate-limiter-status' && req.method === 'GET') {
    try {
      await handleRateLimiterStatus(res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/refresh' && (req.method === 'GET' || req.method === 'POST')) {
    const chatId = url.searchParams.get('chat');
    const force = url.searchParams.get('force') === 'true';
    
    if (chatId) {
      try {
        await handleRefresh(chatId, res, force);
      } catch (err) {
        sendJson(res, 500, { ok: false, error: err.message });
      }
    } else {
      try {
        await handleRefreshAll(res, force);
      } catch (err) {
        sendJson(res, 500, { ok: false, error: err.message });
      }
    }
    return;
  }

  if (url.pathname === '/api/yomi/fetch' && (req.method === 'GET' || req.method === 'POST')) {
    const chatId = url.searchParams.get('chat');
    try {
      await handleFetch(chatId, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/process' && (req.method === 'GET' || req.method === 'POST')) {
    const chatId = url.searchParams.get('chat');
    const force = url.searchParams.get('force') === 'true';
    try {
      await handleProcess(chatId, res, force);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  const mediaMatch = url.pathname.match(/^\/api\/yomi\/media\/([^/]+)\/([^/]+)$/);
  if (mediaMatch && req.method === 'GET') {
    const [, chatId, messageId] = mediaMatch;
    try {
      await handleMedia(chatId, messageId, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/conversations' && req.method === 'GET') {
    try {
      await handleConversations(res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/messages' && req.method === 'GET') {
    const chatId = url.searchParams.get('chat');
    if (!chatId) return sendJson(res, 400, { error: 'chat parameter required' });
    try {
      await handleMessages(chatId, url, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/media/analyze' && req.method === 'POST') {
    try {
      await handleMediaAnalysis(req, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/media/analyze/status' && req.method === 'GET') {
    const jobId = url.searchParams.get('job');
    if (!jobId) return sendJson(res, 400, { error: 'job parameter required' });
    try {
      await handleMediaAnalysisStatus(jobId, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/media/analyze/jobs' && req.method === 'GET') {
    try {
      await handleMediaAnalysisJobs(url, res);
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (url.pathname === '/api/yomi/search' && req.method === 'GET') {
    try {
      const q = url.searchParams.get('q') || '';
      const limit = Math.min(parseInt(url.searchParams.get('limit') || '20', 10), 50);
      const chatId = url.searchParams.get('chat') || '';
      if (!q.trim()) { sendJson(res, 400, { error: 'q is required' }); return; }

      // Embed the query
      const embedRes = await fetch(`${EMBEDDING_URL}/embed-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: q }),
      });
      if (!embedRes.ok) throw new Error(`embedding service ${embedRes.status}`);
      const { embedding } = await embedRes.json();

      // Build optional where filter
      const whereClause = chatId
        ? `where:{path:["chatId"] operator:Equal valueText:${JSON.stringify(chatId)}}`
        : '';

      const gql = `{
        Get {
          YomiMessage(
            hybrid: {
              query: ${JSON.stringify(q)}
              vector: ${JSON.stringify(embedding)}
              alpha: 0.5
            }
            limit: ${limit}
            ${whereClause}
          ) {
            messageId chatId chatName fromName text deliveredTime isGroup
            _additional { score }
          }
        }
      }`;

      const wvRes = await fetch(`${WEAVIATE_URL}/v1/graphql`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: gql }),
      });
      if (!wvRes.ok) throw new Error(`Weaviate ${wvRes.status}`);
      const wvData = await wvRes.json();
      if (wvData.errors) throw new Error(wvData.errors.map(e => e.message).join('; '));

      const raw = wvData.data?.Get?.YomiMessage || [];
      const results = raw.map(r => ({
        messageId:     r.messageId,
        chatId:        r.chatId,
        chatName:      r.chatName,
        fromName:      r.fromName,
        text:          r.text,
        deliveredTime: r.deliveredTime,
        isGroup:       r.isGroup,
        similarity:    parseFloat(parseFloat(r._additional?.score || 0).toFixed(4)),
      }));

      sendJson(res, 200, { results, total: results.length });
    } catch (e) {
      sendJson(res, 500, { error: e.message });
    }
    return;
  }

  sendJson(res, 404, { error: 'not found' });
});

process.on('uncaughtException', (err) => {
  console.error('uncaughtException', err);
  process.exit(1);
});
process.on('unhandledRejection', (err) => {
  console.error('unhandledRejection', err);
});

function shutdown(signal) {
  console.log(`${signal} received, shutting down...`);
  server.close(() => {
    console.log('server closed');
    process.exit(0);
  });
  setTimeout(() => {
    console.error('forced shutdown');
    process.exit(1);
  }, 10000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

server.listen(PORT, HOST, () => {
  console.log(`yomi-api listening on http://${HOST}:${PORT}`);
});
