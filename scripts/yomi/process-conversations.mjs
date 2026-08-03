import { readFileSync, existsSync, readdirSync, writeFileSync } from 'node:fs';
import { categorize } from './categorize-conversations.mjs';
import { evaluateSummaryQuality, isMeaningfulSummary, retryWithBackoff, generateCacheKey, parseCacheKey } from './summary-utils.mjs';
import pool from './db.mjs';

const FETCH_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/fetch-data';
const SUMMARY_CACHE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/summaries.json';
const STATUS_FILE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json';
const LLAMA_URL = process.env.LLAMA_URL || 'http://localhost:8001/v1/chat/completions';
const BATCH_SIZE = parseInt(process.env.YOMI_BATCH_SIZE || '10', 10);

let summaryCache = {};
if (existsSync(SUMMARY_CACHE)) {
  try {
    summaryCache = JSON.parse(readFileSync(SUMMARY_CACHE, 'utf-8'));
  } catch {
    console.warn('Failed to load summary cache, starting fresh');
  }
}

function saveSummaryCache() {
  writeFileSync(SUMMARY_CACHE, JSON.stringify(summaryCache, null, 2));
}

function saveProcessStatus(status) {
  writeFileSync(STATUS_FILE, JSON.stringify({
    ...status,
    timestamp: new Date().toISOString()
  }, null, 2));
}

function loadProcessStatus() {
  if (!existsSync(STATUS_FILE)) return null;
  try {
    return JSON.parse(readFileSync(STATUS_FILE, 'utf-8'));
  } catch {
    return null;
  }
}

function clearProcessStatus() {
  if (existsSync(STATUS_FILE)) {
    try {
      writeFileSync(STATUS_FILE, JSON.stringify({
        status: 'idle',
        timestamp: new Date().toISOString()
      }, null, 2));
    } catch {}
  }
}

function loadFetchData(chatId) {
  const filePath = `${FETCH_DIR}/${chatId}.json`;
  if (!existsSync(filePath)) return null;
  const data = readFileSync(filePath, 'utf-8');
  return JSON.parse(data);
}

function loadFetchMetadata() {
  const filePath = `${FETCH_DIR}/fetch-metadata.json`;
  if (!existsSync(filePath)) return null;
  const data = readFileSync(filePath, 'utf-8');
  return JSON.parse(data);
}

async function getSummary(chatId, messages, name, forceRefresh = false) {
  const lastTime = messages.reduce((max, m) => Math.max(max, m.deliveredTime || 0), 0);
  const cacheKey = generateCacheKey(chatId);
  const cached = summaryCache[cacheKey];

  if (!forceRefresh && cached && cached.lastMessageTime === lastTime && cached.summary) {
    if (isMeaningfulSummary(cached.summary)) {
      return cached.summary;
    }
    console.log(`Low-quality cached summary for ${chatId}, re-summarizing...`);
  }

  const prompt = buildPrompt(name, messages);
  if (!prompt) {
    summaryCache[cacheKey] = { lastMessageTime: lastTime, summary: null, quality: 0 };
    return null;
  }

  try {
    const summary = await retryWithBackoff(
      () => summarizeWithLlama(prompt),
      {
        maxRetries: 3,
        baseDelay: 1000,
        maxDelay: 10000,
        onRetry: (attempt, delay, error) => {
          console.log(`Summary retry ${attempt}/3 for ${chatId} after ${delay}ms (error: ${error.message})`);
        }
      }
    );
    
    const quality = evaluateSummaryQuality(summary);
    if (quality === 0) {
      console.warn(`Low-quality summary generated for ${chatId}: "${summary.substring(0, 50)}..."`);
    }
    
    summaryCache[cacheKey] = { 
      lastMessageTime: lastTime, 
      summary, 
      quality,
      generatedAt: new Date().toISOString(),
      error: null
    };
    
    return summary;
  } catch (err) {
    const errorMessage = `Summary failed for ${chatId} after retries: ${err.message}`;
    console.error(errorMessage);
    
    summaryCache[cacheKey] = { 
      lastMessageTime: lastTime, 
      summary: cached?.summary || null, 
      quality: cached?.quality || 0,
      generatedAt: cached?.generatedAt || null,
      error: err.message
    };
    
    return cached?.summary || null;
  }
}

async function summarizeWithLlama(prompt) {
  const res = await fetch(LLAMA_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'Phi-3-mini-4k-instruct-q4',
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 50,
      temperature: 0.3,
    }),
  });
  if (!res.ok) throw new Error(`Llama API error: ${res.status}`);
  const data = await res.json();
  return data.choices?.[0]?.message?.content?.trim() || null;
}

function buildPrompt(name, messages) {
  const sorted = [...messages].sort((a, b) => (a.deliveredTime || 0) - (b.deliveredTime || 0));
  const lines = sorted.slice(-40).map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = m.text || (m.mediaType ? `[${m.mediaType}]` : null);
    if (!text) return null;
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  
  if (lines.length === 0) {
    console.log(`No content available for summarization of ${name}`);
    return null;
  }
  
  if (lines.length < 2) {
    console.log(`Insufficient content for summarization: ${lines.length} items (need at least 2)`);
    return null;
  }
  
  const textOnlyLines = lines.filter(line => !line.includes('['));
  if (textOnlyLines.length === 0) {
    console.log(`No text content available for summarization, only media: ${name}`);
    return null;
  }
  
  return `Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision.\n\n${lines.join('\n')}\n\nSummary:`;
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

async function processSingle(chatId, forceSummarize = false) {
  console.log(`Processing conversation ${chatId}...`);
  
  saveProcessStatus({
    status: 'processing',
    currentChat: chatId,
    total: 1,
    completed: 0
  });
  
  const fetchData = loadFetchData(chatId);
  if (!fetchData) {
    console.error(`No fetch data found for ${chatId}`);
    return { success: false, error: 'No fetch data' };
  }
  
  const { messages, lastMessageTime } = fetchData;
  
  // Get existing conversation data
  const { rows } = await pool.query(
    'SELECT * FROM conversations WHERE chat_id = $1',
    [chatId]
  );
  const existing = rows[0] || null;
  
  // Build conversation object
  const conv = {
    id: chatId,
    name: existing?.name || 'Unknown',
    isGroup: existing?.is_group || false,
    category: existing?.category || null,
    categorySource: existing?.category_source || null,
    unread: existing?.unread || 0,
    lastMessageTime,
    lastPreview: null,
    summary: null,
    summaryQuality: 0,
    summaryGeneratedAt: null,
    meta: existing?.meta || {}
  };
  
  // Calculate last preview
  const byTimeDesc = [...messages].sort((a, b) => (b.deliveredTime || 0) - (a.deliveredTime || 0));
  const lastPreviewMsg = byTimeDesc.find(m => m.text != null || (m.mediaType && m.mediaType !== 'unavailable'));
  conv.lastPreview = lastPreviewMsg ? (lastPreviewMsg.text ?? `[${lastPreviewMsg.mediaType?.toLowerCase() || 'media'}]`) : null;
  
  // Generate summary
  conv.summary = await getSummary(chatId, messages, conv.name, forceSummarize);
  conv.summaryQuality = conv.summary ? evaluateSummaryQuality(conv.summary) : 0;
  conv.summaryGeneratedAt = new Date();
  
  // Categorize
  const result = categorize(conv);
  conv.category = result.category;
  conv.categorySource = result.source;
  conv.isGroup = result.isGroup;
  
  // Save to database
  await saveConversationToDB(conv);
  
  console.log(`Processed ${chatId}: ${messages.length} messages, quality: ${conv.summaryQuality}`);
  
  saveProcessStatus({
    status: 'idle',
    lastCompleted: chatId,
    timestamp: new Date().toISOString()
  });
  
  return { success: true, messageCount: messages.length, quality: conv.summaryQuality };
}

async function processAll(forceSummarize = false) {
  const metadata = loadFetchMetadata();
  if (!metadata) {
    console.error('No fetch metadata found. Run fetch-conversations.mjs first.');
    return { success: false, error: 'No fetch metadata' };
  }
  
  const files = readdirSync(FETCH_DIR).filter(f => f.endsWith('.json') && f !== 'fetch-metadata.json');
  
  // Sort by last message time (oldest first) to prioritize stale conversations
  const conversations = [];
  for (const file of files) {
    const chatId = file.replace('.json', '');
    const data = loadFetchData(chatId);
    if (data) {
      conversations.push({ chatId, lastMessageTime: data.lastMessageTime });
    }
  }
  conversations.sort((a, b) => (a.lastMessageTime || 0) - (b.lastMessageTime || 0));
  
  console.log(`Processing ${conversations.length} conversations (oldest first)...`);
  
  saveProcessStatus({
    status: 'starting',
    total: conversations.length,
    completed: 0,
    timestamp: new Date().toISOString()
  });
  
  // Process in batches to avoid overwhelming Llama
  let successCount = 0;
  let failCount = 0;
  let totalQuality = 0;
  
  for (let i = 0; i < conversations.length; i += BATCH_SIZE) {
    const batch = conversations.slice(i, i + BATCH_SIZE);
    console.log(`Processing batch ${Math.floor(i / BATCH_SIZE) + 1}/${Math.ceil(conversations.length / BATCH_SIZE)} (${batch.length} conversations)...`);
    
    saveProcessStatus({
      status: 'processing_batch',
      batch: Math.floor(i / BATCH_SIZE) + 1,
      totalBatches: Math.ceil(conversations.length / BATCH_SIZE),
      batchSize: batch.length,
      total: conversations.length,
      completed: i,
      timestamp: new Date().toISOString()
    });
    
    for (const { chatId } of batch) {
      const result = await processSingle(chatId, forceSummarize);
      
      if (result.success) {
        successCount++;
        totalQuality += result.quality || 0;
      } else {
        failCount++;
      }
    }
    
    saveSummaryCache();
    
    saveProcessStatus({
      status: 'batch_complete',
      batch: Math.floor(i / BATCH_SIZE) + 1,
      totalBatches: Math.ceil(conversations.length / BATCH_SIZE),
      total: conversations.length,
      completed: i + batch.length,
      successCount,
      failCount,
      timestamp: new Date().toISOString()
    });
    
    if (i + BATCH_SIZE < conversations.length) {
      console.log(`Batch complete. ${successCount} total processed so far.`);
    }
  }
  
  const avgQuality = successCount > 0 ? Math.round(totalQuality / successCount) : 0;
  
  console.log(`Processing complete: ${successCount} succeeded, ${failCount} failed, avg quality: ${avgQuality}`);
  
  saveProcessStatus({
    status: 'complete',
    total: conversations.length,
    successCount,
    failCount,
    avgQuality,
    timestamp: new Date().toISOString()
  });
  
  return {
    success: true,
    totalConversations: conversations.length,
    successCount,
    failCount,
    avgQuality
  };
}

async function main() {
  const args = process.argv.slice(2);
  const chatIdx = args.indexOf('--chat');
  const forceIdx = args.indexOf('--force');
  const forceSummarize = forceIdx !== -1;
  
  if (chatIdx !== -1) {
    const chatId = args[chatIdx + 1];
    await processSingle(chatId, forceSummarize);
  } else {
    await processAll(forceSummarize);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(err => {
    console.error(err);
    process.exit(1);
  });
}
