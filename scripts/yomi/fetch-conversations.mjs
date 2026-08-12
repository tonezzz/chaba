import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
import { writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs';
import pool from './db.mjs';

function normalizeTimestamp(deliveredTime) {
  if (!deliveredTime) return null;
  try {
    let timestamp = parseInt(deliveredTime, 10);
    if (isNaN(timestamp)) {
      console.warn(`Invalid deliveredTime (not a number): ${deliveredTime}`);
      return null;
    }
    if (timestamp > 2500000000000) {
      timestamp = Math.floor(timestamp / 1000);
    }
    return timestamp;
  } catch (err) {
    console.warn(`Invalid deliveredTime: ${deliveredTime}`);
    return null;
  }
}

const FETCH_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/fetch-data';
const BATCH_SIZE = 10;
const BATCH_DELAY_MS = 2000;
const YOMI_MCP_PATH = process.env.YOMI_MCP_PATH || '/home/tony/.yomi/mcpb/run.mjs';
const LOGIN_ATTEMPT_FILE = `${FETCH_DIR}/login-attempts.json`;
const MAX_LOGIN_ATTEMPTS_PER_HOUR = 1;

const nodePath = process.env.NODE_BINARY_PATH || '/usr/bin/node';
const transport = new StdioClientTransport({
  command: nodePath,
  args: [YOMI_MCP_PATH],
});

const client = new Client({ name: 'yomi-conversations-fetch', version: '0.1' });
await client.connect(transport);

async function getChatMessages(chatId, count = 100) {
  const result = await client.callTool({ 
    name: 'get_chat_messages', 
    arguments: { chatId, count } 
  });
  const text = result.content?.[0]?.text ?? '';
  return parseMessages(text);
}

function parseMessages(text) {
  const headerMatch = text.match(/^\s*\[\d+\]\{([^}]+)\}:/);
  if (headerMatch) return parseCSVMessages(text, headerMatch[1].split(','));
  const messages = [];
  let msg = null;
  let blockKey = null;
  let blockStyle = null;
  let blockIndent = null;
  for (const line of text.split('\n')) {
    if (line.startsWith('  ')) {
      if (msg) msg.content += line.slice(2) + '\n';
      continue;
    }
    if (line.match(/^\s*\[\d+\]\{/)) {
      if (msg) messages.push(msg);
      const match = line.match(/^\s*\[(\d+)\]\{([^}]+)\}:\s*(.*)$/);
      if (match) {
        const [, seq, header, content] = match;
        msg = { seq: parseInt(seq, 10), header, content: content + '\n' };
      }
    }
  }
  if (msg) messages.push(msg);
  return messages.map(m => ({
    id: m.header.split(',')[0],
    from: m.header.split(',')[1],
    fromName: m.header.split(',')[2],
    deliveredTime: normalizeTimestamp(m.header.split(',')[3]),
    text: m.content.trim() || null,
  }));
}

function parseCSVMessages(text, columns) {
  const messages = [];
  const lines = text.split('\n');
  let headerIdx = lines.findIndex(l => l.includes('{'));
  for (let i = headerIdx + 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('[')) continue;
    const values = line.split(',');
    if (values.length === columns.length) {
      const msg = {};
      columns.forEach((col, idx) => msg[col.trim()] = values[idx]?.trim() || null);
      messages.push(msg);
    }
  }
  return messages;
}

async function saveFetchData(chatId, data) {
  mkdirSync(FETCH_DIR, { recursive: true });
  const filePath = `${FETCH_DIR}/${chatId}.json`;
  writeFileSync(filePath, JSON.stringify(data, null, 2));
}

async function loadFetchData(chatId) {
  const filePath = `${FETCH_DIR}/${chatId}.json`;
  if (!existsSync(filePath)) return null;
  const data = readFileSync(filePath, 'utf-8');
  return JSON.parse(data);
}

async function saveConversationToDB(conv) {
  await pool.query(`
    INSERT INTO conversations (chat_id, name, is_group, category, category_source, unread, last_message_time, last_preview, summary, summary_quality, summary_generated_at, meta, updated_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
    ON CONFLICT (chat_id) DO UPDATE SET
      name = EXCLUDED.name,
      is_group = COALESCE(EXCLUDED.is_group, conversations.is_group),
      category = COALESCE(EXCLUDED.category, conversations.category),
      category_source = COALESCE(EXCLUDED.category_source, conversations.category_source),
      unread = EXCLUDED.unread,
      last_message_time = EXCLUDED.last_message_time,
      last_preview = EXCLUDED.last_preview,
      summary = EXCLUDED.summary,
      summary_quality = EXCLUDED.summary_quality,
      summary_generated_at = COALESCE(EXCLUDED.summary_generated_at, conversations.summary_generated_at),
      meta = EXCLUDED.meta,
      updated_at = NOW()
  `, [conv.id, conv.name, conv.isGroup, conv.category, conv.categorySource, conv.unread, conv.lastMessageTime, conv.lastPreview, conv.summary, conv.summaryQuality, conv.summaryGeneratedAt || new Date(), JSON.stringify(conv.meta || {})]);
}

async function fetchSingle(chatId, retryCount = 0, maxRetries = 5) {
  console.log(`Fetching conversation ${chatId}...`);
  
  const backoffDelays = [60000, 300000, 900000, 3600000, 14400000]; // 1min, 5min, 15min, 1hr, 4hr
  
  try {
    const messages = await getChatMessages(chatId, 100);
    const lastMessageTime = messages.reduce((max, m) => Math.max(max, normalizeTimestamp(m.deliveredTime) || 0), 0);
    
    const data = {
      chatId,
      messages,
      lastMessageTime,
      fetchedAt: new Date().toISOString()
    };
    
    await saveFetchData(chatId, data);
    console.log(`Fetched ${messages.length} messages for ${chatId}`);
    
    return { success: true, messageCount: messages.length, lastMessageTime };
  } catch (err) {
    if (isRateLimitError(err) && retryCount < maxRetries) {
      const delay = backoffDelays[Math.min(retryCount, backoffDelays.length - 1)];
      console.error(`Rate limit detected for ${chatId}. Retrying in ${Math.floor(delay / 60000)} minutes (attempt ${retryCount + 1}/${maxRetries})...`);
      await sleep(delay);
      return fetchSingle(chatId, retryCount + 1, maxRetries);
    }
    
    console.error(`Failed to fetch ${chatId}: ${err.message}`);
    return { success: false, error: err.message };
  }
}

async function fetchAll(limit = 200, retryCount = 0, maxRetries = 5) {
  console.log('Fetching conversation list...');
  
  const backoffDelays = [60000, 300000, 900000, 3600000, 14400000]; // 1min, 5min, 15min, 1hr, 4hr
  
  try {
    const result = await client.callTool({ name: 'list_conversations', arguments: { limit } });
    const text = result.content?.[0]?.text ?? '';

    const records = [];
    let header = true;
    for (const line of text.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (header) {
        if (trimmed.includes('{id,lastMessagePreview,name,unreadCount}')) {
          header = false;
        }
        continue;
      }
      const match = trimmed.match(/^(\S+),(null|"(?:[^"\\]|\\.)*"|[^,]+),(.*),(\d+)$/);
      if (!match) continue;
      const [, id, rawPreview, rawName, unread] = match;
      let preview;
      try {
        preview = rawPreview === 'null' ? null : JSON.parse(rawPreview);
      } catch {
        preview = rawPreview;
      }
      records.push({ id, name: rawName.trim(), unread: parseInt(unread, 10), preview });
    }

    console.log(`Found ${records.length} conversations to fetch`);
    
    let successCount = 0;
    let failCount = 0;
    
    for (let i = 0; i < records.length; i += BATCH_SIZE) {
      const batch = records.slice(i, i + BATCH_SIZE);
      console.log(`Processing batch ${Math.floor(i / BATCH_SIZE) + 1}/${Math.ceil(records.length / BATCH_SIZE)}...`);
      
      const results = await Promise.all(batch.map(c => fetchSingle(c.id)));
      
      results.forEach(r => {
        if (r.success) successCount++;
        else failCount++;
      });
      
      if (i + BATCH_SIZE < records.length) {
        console.log(`Waiting ${BATCH_DELAY_MS}ms before next batch...`);
        await new Promise(resolve => setTimeout(resolve, BATCH_DELAY_MS));
      }
    }
    
    console.log(`Fetch complete: ${successCount} succeeded, ${failCount} failed`);
    
    // Save fetch metadata
    const metadata = {
      fetchedAt: new Date().toISOString(),
      totalConversations: records.length,
      successCount,
      failCount
    };
    
    mkdirSync(FETCH_DIR, { recursive: true });
    writeFileSync(`${FETCH_DIR}/fetch-metadata.json`, JSON.stringify(metadata, null, 2));
    
    return metadata;
  } catch (err) {
    if (isRateLimitError(err) && retryCount < maxRetries) {
      const delay = backoffDelays[Math.min(retryCount, backoffDelays.length - 1)];
      console.error(`Rate limit detected fetching conversation list. Retrying in ${Math.floor(delay / 60000)} minutes (attempt ${retryCount + 1}/${maxRetries})...`);
      await sleep(delay);
      return fetchAll(limit, retryCount + 1, maxRetries);
    }
    
    console.error(`Failed to fetch conversation list: ${err.message}`);
    throw err;
  }
}

async function shouldSkipFetch() {
  const skipIntervalMinutes = parseInt(process.env.YOMI_FETCH_SKIP_MINUTES || '30', 10);
  const metadataPath = `${FETCH_DIR}/fetch-metadata.json`;
  
  if (!existsSync(metadataPath)) {
    return false;
  }
  
  const metadata = JSON.parse(readFileSync(metadataPath, 'utf-8'));
  
  if (!metadata || !metadata.fetchedAt) {
    return false;
  }
  
  const lastFetchTime = new Date(metadata.fetchedAt);
  const now = new Date();
  const minutesSinceLastFetch = (now - lastFetchTime) / (1000 * 60);
  
  if (minutesSinceLastFetch < skipIntervalMinutes) {
    console.log(`Skipping fetch - last successful fetch was ${Math.floor(minutesSinceLastFetch)} minutes ago (skip interval: ${skipIntervalMinutes} minutes)`);
    return true;
  }
  
  return false;
}

function recordLoginAttempt() {
  mkdirSync(FETCH_DIR, { recursive: true });
  const now = new Date().toISOString();
  let attempts = [];
  
  if (existsSync(LOGIN_ATTEMPT_FILE)) {
    attempts = JSON.parse(readFileSync(LOGIN_ATTEMPT_FILE, 'utf-8'));
  }
  
  // Remove attempts older than 1 hour
  const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
  attempts = attempts.filter(t => new Date(t) > oneHourAgo);
  
  attempts.push(now);
  writeFileSync(LOGIN_ATTEMPT_FILE, JSON.stringify(attempts, null, 2));
}

function shouldAttemptLogin() {
  if (!existsSync(LOGIN_ATTEMPT_FILE)) {
    return true;
  }
  
  const attempts = JSON.parse(readFileSync(LOGIN_ATTEMPT_FILE, 'utf-8'));
  const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
  const recentAttempts = attempts.filter(t => new Date(t) > oneHourAgo);
  
  if (recentAttempts.length >= MAX_LOGIN_ATTEMPTS_PER_HOUR) {
    console.log(`Skipping login - ${recentAttempts.length} login attempts in the last hour (max: ${MAX_LOGIN_ATTEMPTS_PER_HOUR})`);
    return false;
  }
  
  return true;
}

function isRateLimitError(error) {
  if (!error) return false;
  const errorStr = error.toString().toLowerCase();
  return errorStr.includes('103') || 
         errorStr.includes('rate limit') || 
         errorStr.includes('temporarily restricted') ||
         errorStr.includes('認証が一時的に制限されています');
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function sendNotification(title, message) {
  try {
    const { exec } = await import('node:child_process');
    exec(`notify-send "${title}" "${message}"`, (err) => {
      if (err) console.warn('Failed to send desktop notification:', err.message);
    });
  } catch (err) {
    console.warn('notify-send not available:', err.message);
  }
}

async function validateSession() {
  try {
    const result = await client.callTool({ name: 'list_conversations', arguments: { limit: 1 } });
    const text = result.content?.[0]?.text ?? '';
    // If we get a response (even empty), session is valid
    return true;
  } catch (err) {
    const errorStr = err.toString().toLowerCase();
    if (errorStr.includes('no persisted line session') || 
        errorStr.includes('logged out') ||
        errorStr.includes('authentication')) {
      console.error('Session validation failed: LINE session is invalid or expired');
      console.error('Please re-login manually: npx @rikaidev/yomi login');
      await sendNotification('Yomi Session Expired', 'LINE session expired. Run: npx @rikaidev/yomi login');
      return false;
    }
    // Other errors might be transient, try to proceed
    console.warn('Session validation encountered non-auth error, proceeding:', err.message);
    return true;
  }
}

async function main() {
  const args = process.argv.slice(2);
  const forceIdx = args.indexOf('--force');
  
  // Validate session before attempting fetch
  const sessionValid = await validateSession();
  if (!sessionValid) {
    console.error('Aborting fetch due to invalid session');
    process.exit(1);
  }
  
  // Skip fetch if recent successful fetch exists, unless --force is specified
  if (forceIdx === -1 && await shouldSkipFetch()) {
    return;
  }
  
  const chatIdx = args.indexOf('--chat');
  const limitIdx = args.indexOf('--limit');
  
  if (chatIdx !== -1) {
    const chatId = args[chatIdx + 1];
    await fetchSingle(chatId);
  } else {
    const limit = limitIdx !== -1 ? parseInt(args[limitIdx + 1], 10) : 200;
    await fetchAll(limit);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().then(() => client.close()).catch(err => {
    console.error(err);
    client.close();
    process.exit(1);
  });
}