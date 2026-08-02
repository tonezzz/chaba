import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, createReadStream, readdirSync } from 'node:fs';
import pool from './db.mjs';

const PORT = parseInt(process.env.YOMI_API_PORT || '3000', 10);
const HOST = process.env.YOMI_API_HOST || '0.0.0.0';
const SCRIPT_DIR = '/home/tony/CascadeProjects/chaba/scripts/yomi';
const MEDIA_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/media';

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

function spawnNode(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn('/usr/bin/node', [script, ...args], {
      cwd: SCRIPT_DIR,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: process.env,
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

async function handleRefresh(chatId, res) {
  const { code, err } = await spawnNode(`${SCRIPT_DIR}/update-conversations.mjs`, ['--chat', chatId]);
  if (code === 0) {
    sendJson(res, 200, { ok: true });
  } else {
    sendJson(res, 500, { ok: false, error: err.trim() || 'export failed' });
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
  const { rows } = await pool.query(`
    SELECT date, events, actions, topics, message_count, updated_at
    FROM daily_summaries
    WHERE chat_id = $1
    ORDER BY date DESC
  `, [chatId]);
  sendJson(res, 200, { chatId, summaries: rows });
}

async function handleMessages(chatId, url, res) {
  const before = url.searchParams.get('before');
  const limit = Math.min(parseInt(url.searchParams.get('limit') || '10000', 10), 10000);
  const { rows } = await pool.query(`
    SELECT data FROM messages
    WHERE chat_id = $1
      AND ($2::bigint IS NULL OR delivered_time < $2)
    ORDER BY delivered_time DESC
    LIMIT $3
  `, [chatId, before ? parseInt(before, 10) : null, limit]);
  sendJson(res, 200, { generatedAt: new Date().toISOString(), messages: rows.map(r => r.data) });
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

  if (url.pathname === '/api/yomi/refresh' && (req.method === 'GET' || req.method === 'POST')) {
    const chatId = url.searchParams.get('chat');
    if (!chatId) return sendJson(res, 400, { error: 'chat parameter required' });
    try {
      await handleRefresh(chatId, res);
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
