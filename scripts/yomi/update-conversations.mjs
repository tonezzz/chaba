import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
import { writeFileSync, readFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { categorize } from './categorize-conversations.mjs';
import { evaluateSummaryQuality, isMeaningfulSummary, retryWithBackoff, generateCacheKey, parseCacheKey } from './summary-utils.mjs';
import { summaryRateLimiter, dailyRateLimiter, summaryCircuitBreaker, dailyCircuitBreaker } from './llama-rate-limiter.mjs';
import { submitSummaryJob, submitDailySummaryJob, submitBatchDailySummaryJob, waitForJob } from './gpu-queue-integration.mjs';
import pool from './db.mjs';
import { geminiConversationSummary, geminiDailySummary, geminiBatchDailySummary } from './gemini-integration.mjs';

const USE_GEMINI = process.env.USE_GEMINI === 'true' || process.env.USE_GEMINI === '1'; // Default to false (use Llama)

const GEMINI_MAX_DATES = parseInt(process.env.GEMINI_MAX_DATES || '10', 10); // Limit dates per run for Gemini
const GEMINI_PRIORITY_MODE = process.env.GEMINI_PRIORITY_MODE || 'recent'; // 'recent', 'high-activity', 'all'
// Filter out messages that only contain encrypted keyMaterial/fileName data
function shouldFilterMessage(text) {
  if (!text) return true;
  if (text.startsWith('{') && text.includes('keyMaterial')) {
    return true;
  }
  // Also filter out messages that only contain fileName (no actual conversation)
  if (text.startsWith('{') && text.includes('fileName') && !text.includes('keyMaterial')) {
    return true;
  }
  return false;
}

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

function detectLanguage(text) {
  // Thai character ranges: U+0E00-U+0E7F
  const thaiChars = text.match(/[\u0E00-\u0E7F]/g);
  const totalChars = text.replace(/\s/g, '').length;
  
  if (totalChars === 0) return 'unknown';
  
  const thaiRatio = thaiChars ? thaiChars.length / totalChars : 0;
  
  // Adjusted thresholds for better mixed detection
  if (thaiRatio > 0.5) return 'thai';
  if (thaiRatio > 0.05) return 'mixed';
  return 'english';
}

function detectConversationLanguage(messages) {
  const textContent = messages
    .map(m => m.text || '')
    .filter(Boolean)
    .join(' ');
  
  if (!textContent) return 'english';
  
  return detectLanguage(textContent);
}

function getLanguageSpecificPrompt(language, name, lines) {
  const baseContent = lines.join('\n');
  
  switch (language) {
    case 'thai':
      return `สรุปการสนทนา LINE กับ ${name} เป็นประโยคเดียวสั้นๆ (ไม่เกิน 20 คำ) เน้นหัวข้อหลัก คำถาม หรือการตัดสินใจ\n\n${baseContent}\n\nสรุป:`;
    
    case 'mixed':
      return `Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Use the same language as the messages (Thai/English mix). Focus on the main topic, question, or decision.\n\n${baseContent}\n\nSummary:`;
    
    case 'english':
    default:
      return `Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision.\n\n${baseContent}\n\nSummary:`;
  }
}

const OUT = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/conversations.json';
const MESSAGES_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/messages';
const MEDIA_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/media';
const SUMMARY_CACHE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/summaries.json';
const LLAMA_URL = process.env.LLAMA_URL || 'http://localhost:8001/v1/chat/completions';

const transport = new StdioClientTransport({
  command: '/usr/bin/node',
  args: ['/home/tony/.yomi/mcpb/run.mjs'],
});

const client = new Client({ name: 'yomi-conversations-export', version: '0.1' });
await client.connect(transport);

function parseMessages(text) {
  const headerMatch = text.match(/^\s*\[\d+\]\{([^}]+)\}:/);
  if (headerMatch) return parseCSVMessages(text, headerMatch[1].split(','));
  const messages = [];
  let msg = null;
  let blockKey = null;
  let blockStyle = null;
  let blockIndent = null;
  const blockLines = [];

  function closeBlock() {
    if (!msg || !blockKey) return;
    msg[blockKey] = blockStyle === '>' ? blockLines.join(' ').trim() : blockLines.join('\n');
    blockKey = null;
    blockStyle = null;
    blockIndent = null;
    blockLines.length = 0;
  }

  function parseScalar(value) {
    const m = value.match(/^([|>])[+-]?\s*$/);
    if (m) return { isBlock: true, style: m[1] };
    return { isBlock: false, value };
  }

  function normalize(value) {
    if (value === 'null' || value === '~') return null;
    if (value === 'true') return true;
    if (value === 'false') return false;
    if (value.length >= 2 && value[0] === '"' && value[value.length - 1] === '"') {
      return value.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\');
    }
    if (/^-?\d+$/.test(value)) return parseInt(value, 10);
    return value;
  }

  for (const rawLine of text.split('\n')) {
    const trimmed = rawLine.trimStart();
    if (!trimmed) continue;
    const leading = rawLine.length - trimmed.length;

    if (leading === 0 && trimmed.startsWith('[')) continue; // header like [100]:

    if (leading === 2 && trimmed.startsWith('- ')) {
      closeBlock();
      if (msg) messages.push(msg);
      msg = {};
      const rest = trimmed.slice(2);
      const idx = rest.indexOf(':');
      if (idx === -1) continue;
      const key = rest.slice(0, idx);
      const value = rest.slice(idx + 1).trimStart();
      const parsed = parseScalar(value);
      if (parsed.isBlock) {
        blockKey = key;
        blockStyle = parsed.style;
        blockIndent = null;
        blockLines.length = 0;
      } else {
        msg[key] = normalize(value);
      }
      continue;
    }

    if (leading === 4 && msg) {
      const idx = trimmed.indexOf(':');
      if (idx !== -1) {
        closeBlock();
        const key = trimmed.slice(0, idx);
        const value = trimmed.slice(idx + 1).trimStart();
        const parsed = parseScalar(value);
        if (parsed.isBlock) {
          blockKey = key;
          blockStyle = parsed.style;
          blockIndent = null;
          blockLines.length = 0;
        } else {
          msg[key] = normalize(value);
        }
        continue;
      }
    }

    if (msg && blockKey && leading >= 6) {
      if (blockIndent === null) blockIndent = leading;
      const content = rawLine.slice(blockIndent);
      blockLines.push(content);
      continue;
    }

    if (msg && blockKey && leading < 6) {
      closeBlock();
    }
  }
  if (msg) {
    closeBlock();
    messages.push(msg);
  }
  return messages;
}

function parseCSVRow(line) {
  const values = [];
  let i = 0;
  while (i < line.length) {
    let value = '';
    if (line[i] === '"') {
      i++;
      while (i < line.length) {
        if (line[i] === '\\' && i + 1 < line.length) {
          value += line[i + 1];
          i += 2;
          continue;
        }
        if (line[i] === '"') { i++; break; }
        value += line[i];
        i++;
      }
      while (i < line.length && line[i] !== ',') i++;
      if (line[i] === ',') i++;
    } else {
      while (i < line.length && line[i] !== ',') { value += line[i]; i++; }
      if (line[i] === ',') i++;
    }
    values.push(value);
  }
  return values;
}

function parseCSVMessages(text, headers) {
  const messages = [];
  for (const rawLine of text.split('\n')) {
    const trimmed = rawLine.trim();
    if (!trimmed || /^\[\d+\]\{/.test(trimmed)) continue;
    const values = parseCSVRow(rawLine);
    if (values.length < headers.length) continue;
    const msg = {};
    for (let i = 0; i < headers.length; i++) {
      const key = headers[i];
      let value = values[i].trim();
      if (value === '' || value === 'null' || value === '~') value = null;
      else if (value === 'true') value = true;
      else if (value === 'false') value = false;
      else if (value.length >= 2 && value[0] === '"' && value[value.length - 1] === '"') {
        value = value.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\');
      }
      if (/^(createdTime|deliveredTime)$/.test(key) && typeof value === 'string' && /^-?\d+$/.test(value)) {
        value = normalizeTimestamp(value);
      }
      msg[key] = value;
    }
    messages.push(msg);
  }
  return messages;
}

const MIME_TO_EXT = {
  'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png', 'image/gif': 'gif',
  'image/webp': 'webp', 'image/heic': 'heic', 'image/heif': 'heif',
  'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov', 'video/3gpp': '3gp',
  'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/m4a': 'm4a', 'audio/ogg': 'ogg',
  'audio/aac': 'aac', 'audio/amr': 'amr',
  'application/pdf': 'pdf', 'application/zip': 'zip',
};

function extFromMime(mime) {
  if (!mime) return 'bin';
  if (MIME_TO_EXT[mime]) return MIME_TO_EXT[mime];
  return mime.split('/').pop().replace(/[^a-z0-9]/gi, '') || 'bin';
}

function extFromName(name) {
  if (!name || !name.includes('.')) return null;
  const ext = name.split('.').pop().replace(/[^a-z0-9]/gi, '');
  return ext || null;
}

function guessMime(part) {
  if (part.mimeType) return part.mimeType;
  if (part.resource?.mimeType) return part.resource.mimeType;
  const name = part.name || part.resource?.name;
  const ext = extFromName(name);
  for (const [mime, e] of Object.entries(MIME_TO_EXT)) {
    if (e === ext?.toLowerCase()) return mime;
  }
  if (part.type === 'image') return 'image/jpeg';
  if (part.type === 'audio') return 'audio/m4a';
  return 'application/octet-stream';
}

async function downloadMedia(chatId, messageId) {
  const dir = `${MEDIA_DIR}/${chatId}`;
  mkdirSync(dir, { recursive: true });
  const cached = existsSync(dir) ? (readdirSync(dir).find(f => f.startsWith(`${messageId}.`)) || null) : null;
  if (cached) {
    const ext = cached.split('.').pop().toLowerCase();
    const mime = Object.keys(MIME_TO_EXT).find(k => MIME_TO_EXT[k] === ext) || 'application/octet-stream';
    return { fileName: cached, mime };
  }
  const result = await client.callTool({ name: 'get_message_media', arguments: { chatId, messageId, preview: false } });
  const part = result.content?.[0];
  if (!part || part.type === 'text') return { unavailable: true, error: 'media unavailable' };
  let buffer;
  let mime = guessMime(part);
  if (part.type === 'image' || part.type === 'audio') {
    if (!part.data) return { unavailable: true, error: 'media unavailable' };
    buffer = Buffer.from(part.data, 'base64');
  } else if (part.type === 'resource' || part.blob) {
    const payload = part.data || part.blob;
    if (!payload) return { unavailable: true, error: 'media unavailable' };
    buffer = Buffer.from(payload, 'base64');
    if (part.resource?.name) {
      const ext = extFromName(part.resource.name);
      for (const [m, e] of Object.entries(MIME_TO_EXT)) if (e === ext?.toLowerCase()) mime = m;
    }
  } else {
    return { unavailable: true, error: 'unsupported media type' };
  }
  const nameHint = part.name || part.resource?.name;
  const ext = extFromName(nameHint) || extFromMime(mime);
  const fileName = `${messageId}.${ext}`;
  const filePath = `${dir}/${fileName}`;
  writeFileSync(filePath, buffer);
  return { fileName, mime };
}

async function getChatMessages(chatId, pageSize = 100) {
  const all = [];
  const seen = new Set();
  let before = null;
  let iterations = 0;
  const MAX_PAGES = 200;

  while (iterations < MAX_PAGES) {
    const args = { chatId, count: pageSize };
    if (before) args.before = before;
    const result = await client.callTool({ name: 'get_chat_messages', arguments: args });
    let raw = '';
    if (Array.isArray(result.content)) {
      raw = result.content.map(c => (typeof c === 'string' ? c : c?.text ?? '')).join('');
    } else if (typeof result.content === 'string') {
      raw = result.content;
    } else if (result.content && result.content.text) {
      raw = result.content.text;
    }
    let page;
    try {
      const parsed = JSON.parse(raw);
      page = Array.isArray(parsed) ? parsed : [];
    } catch {
      page = parseMessages(raw);
    }
    if (!Array.isArray(page)) page = [];
    const newMessages = page.filter(m => !seen.has(m.id));
    if (newMessages.length === 0) break;
    newMessages.forEach(m => seen.add(m.id));
    all.push(...newMessages);
    const oldest = newMessages.reduce((min, m) => {
      const t = m.deliveredTime || 0;
      return !min || t < (min.deliveredTime || 0) ? m : min;
    }, null);
    if (!oldest) break;
    before = { messageId: oldest.id, deliveredTime: oldest.deliveredTime || 0 };
    iterations++;
  }

  const MAX_CONCURRENCY = 3;
  const BATCH_DELAY_MS = 100;
  const mediaMessages = all.filter(m => /^(image|video|audio|file)$/.test(String(m.mediaType || '').toLowerCase()));
  for (let i = 0; i < mediaMessages.length; i += MAX_CONCURRENCY) {
    const batch = mediaMessages.slice(i, i + MAX_CONCURRENCY);
    await Promise.all(batch.map(async (m) => {
      try {
        const info = await downloadMedia(chatId, m.id);
        if (info) {
          if (info.unavailable) {
            m.mediaType = 'unavailable';
          } else {
            m.mediaFile = info.fileName;
            m.mediaMime = info.mime;
          }
        }
      } catch (err) {
        console.error(`Failed to download media ${chatId}/${m.id}: ${err.message}`);
      }
    }));
    if (i + MAX_CONCURRENCY < mediaMessages.length) {
      await new Promise(resolve => setTimeout(resolve, BATCH_DELAY_MS));
    }
  }
  return all;
}

function loadSummaryCache() {
  if (!existsSync(SUMMARY_CACHE)) return {};
  try {
    return JSON.parse(readFileSync(SUMMARY_CACHE, 'utf8'));
  } catch {
    return {};
  }
}

const summaryCache = loadSummaryCache();

function saveSummaryCache() {
  mkdirSync(dirname(SUMMARY_CACHE), { recursive: true });
  writeFileSync(SUMMARY_CACHE, JSON.stringify(summaryCache, null, 2));
}

function mediaLabel(m) {
  if (!m.mediaType) return '[unknown]';
  const t = String(m.mediaType).toLowerCase();
  if (t === 'image') return '[image]';
  if (t === 'video') return '[video]';
  if (t === 'audio') return '[audio]';
  if (t === 'file') return `[file: ${m.mediaFile || 'attachment'}]`;
  return `[${t}]`;
}

function buildPrompt(name, messages) {
  const sorted = [...messages].sort((a, b) => (normalizeTimestamp(a.deliveredTime) || 0) - (normalizeTimestamp(b.deliveredTime) || 0));
  const lines = sorted.slice(-40).map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = m.text || mediaLabel(m);
    if (!text) return null;
    
    // Filter out messages that only contain encrypted keyMaterial/fileName data
    if (shouldFilterMessage(text)) {
      return null;
    }
    
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  
  // Enhanced content validation
  if (lines.length === 0) {
    console.log(`No content available for summarization of ${name}`);
    return null;
  }
  
  if (lines.length < 2) {
    console.log(`Insufficient content for summarization: ${lines.length} items (need at least 2)`);
    return null;
  }
  
  // Check for meaningful content (not just media)
  const textOnlyLines = lines.filter(line => !line.includes('['));
  if (textOnlyLines.length === 0) {
    console.log(`No text content available for summarization, only media: ${name}`);
    return null;
  }
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(messages);
  console.log(`Detected language for ${name}: ${language}`);
  
  return getLanguageSpecificPrompt(language, name, textOnlyLines);
}

async function summarizeWithLlama(prompt, chatId = 'unknown') {
  // Validate and truncate context length before API call
  const validatedPrompt = validateAndTruncateContext(prompt, chatId);
  const contextStatus = getContextLengthStatus(prompt);
  
  if (!contextStatus.valid) {
    console.error(`Context length validation failed: ${contextStatus.length} > ${contextStatus.limit}`);
    throw new Error(`Context length ${contextStatus.length} exceeds maximum ${contextStatus.limit}`);
  }
  
  // Try GPU queue first, fallback to direct API
  try {
    console.log(`Attempting GPU queue for summary of ${chatId}`);
    const jobId = await submitSummaryJob(chatId, validatedPrompt, 'yomi_summary');
    const { result } = await waitForJob(jobId, 120000); // 2 minute timeout for queue
    console.log(`GPU queue completed summary for ${chatId}`);
    return result;
  } catch (queueError) {
    console.log(`GPU queue failed for ${chatId}: ${queueError.message}, falling back to direct API`);
    
    // Fallback to direct API with rate limiting
    return await summaryRateLimiter.run(async () => {
      return await summaryCircuitBreaker.run(async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), LLAMA_REQUEST_TIMEOUT);
        
        try {
          const res = await fetch(LLAMA_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: 'Phi-3-mini-4k-instruct-q4',
              messages: [
                { role: 'system', content: 'You write concise one-sentence summaries of chat conversations.' },
                { role: 'user', content: validatedPrompt }
              ],
              temperature: 0.4,
              max_tokens: 60,
              stop: ['\n']
            }),
            signal: controller.signal
          });
          
          clearTimeout(timeout);
          
          if (!res.ok) throw new Error('llama ' + res.status);
          const data = await res.json();
          const content = data.choices?.[0]?.message?.content?.trim();
          if (!content) throw new Error('empty llama response');
          return content.replace(/\\n/g, ' ').replace(/\s+/g, ' ');
        } catch (error) {
          clearTimeout(timeout);
          if (error.name === 'AbortError') {
            throw new Error(`Llama API timeout after ${LLAMA_REQUEST_TIMEOUT}ms`);
          }
          throw error;
        }
      });
    });
  }
}

async function getSummary(chatId, messages, name, forceRefresh = false) {
  const lastTime = messages.reduce((max, m) => Math.max(max, normalizeTimestamp(m.deliveredTime) || 0), 0);
  const cacheKey = generateCacheKey(chatId);
  const cached = summaryCache[cacheKey];
  
  // Return cached summary if valid and not forcing refresh
  if (!forceRefresh && cached && cached.lastMessageTime === lastTime && cached.summary) {
    // Check if cached summary is still meaningful
    if (isMeaningfulSummary(cached.summary)) {
      return cached.summary;
    }
    // Cache has low-quality summary, re-summarize
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
          // Reset circuit breaker on retry to allow recovery
          if (error.message.includes('Circuit breaker')) {
            console.log('Resetting circuit breaker for retry');
            summaryCircuitBreaker.reset();
          }
        }
      }
    );
    
    // Validate summary quality
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
    
    // Cache the error
    summaryCache[cacheKey] = { 
      lastMessageTime: lastTime, 
      summary: cached?.summary || null, 
      quality: cached?.quality || 0,
      generatedAt: cached?.generatedAt || null,
      error: err.message
    };
    
    // Return cached summary if available, even if low quality
    return cached?.summary || null;
  }
}

function groupMessagesByDate(messages) {
  const byDate = new Map();
  for (const m of messages) {
    const normalizedTime = normalizeTimestamp(m.deliveredTime);
    if (!normalizedTime) continue;
    // Group by Thailand calendar day (UTC+7)
    const thailandDate = new Date(normalizedTime + (7 * 60 * 60 * 1000)); // Add 7 hours for Thailand timezone
    const date = thailandDate.toISOString().split('T')[0];
    if (!byDate.has(date)) byDate.set(date, []);
    byDate.get(date).push(m);
  }
  return byDate;
}

function buildDailyPrompt(date, messages, name) {
  const lines = messages.map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = m.text || mediaLabel(m);
    if (!text) return null;
    
    // Filter out messages that only contain encrypted keyMaterial/fileName data
    if (shouldFilterMessage(text)) {
      return null;
    }
    
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  if (lines.length === 0) return null;
  return `Extract from these LINE messages for ${date} in conversation with ${name}:
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)

Format as JSON:
{
  "events": ["event1", "event2"],
  "actions": ["action1", "action2"],
  "topics": ["topic1", "topic2"]
}

Messages:
${lines.join('\n')}`;
}

function buildBatchDailyPrompt(dateGroups, name) {
  const dateSections = [];
  for (const [date, messages] of dateGroups) {
    const lines = messages.map(m => {
      const from = m.fromName || m.from || 'Unknown';
      const text = m.text || mediaLabel(m);
      if (!text) return null;
      
      // Filter out messages that only contain encrypted keyMaterial/fileName data
      if (shouldFilterMessage(text)) {
        return null;
      }
      
      return `${from}: ${String(text).replace(/\n/g, ' ')}`;
    }).filter(Boolean);
    
    if (lines.length > 0) {
      dateSections.push(`=== ${date} ===\n${lines.join('\n')}`);
    }
  }
  
  if (dateSections.length === 0) return null;
  
  const dates = Array.from(dateGroups.keys()).join(', ');
  
  return `Extract structured information from these LINE messages for conversation with ${name} across multiple dates (${dates}):
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)

Format as JSON with date keys:
{
  "YYYY-MM-DD": {
    "events": ["event1", "event2"],
    "actions": ["action1", "action2"],
    "topics": ["topic1", "topic2"]
  },
  "YYYY-MM-DD": {
    "events": ["event1"],
    "actions": ["action1"],
    "topics": ["topic1"]
  }
}

Messages:
${dateSections.join('\n\n')}`;
}

async function extractDailyWithLlama(prompt, chatId = 'unknown', date = 'unknown') {
  // Use Gemini if enabled
  if (USE_GEMINI) {
    console.log(`Using Gemini for daily summary of ${chatId} on ${date}`);
    // Detect language from prompt
    const language = detectLanguage(prompt);
    const response = await geminiDailySummary(chatId, date, prompt, language);
    // Parse JSON response from Gemini
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('no json in response');
    return JSON.parse(jsonMatch[0]);
  }

  // Validate and truncate context length before API call
  const validatedPrompt = validateAndTruncateContext(prompt, chatId);
  const contextStatus = getContextLengthStatus(prompt);
  
  if (!contextStatus.valid) {
    console.error(`Context length validation failed: ${contextStatus.length} > ${contextStatus.limit}`);
    throw new Error(`Context length ${contextStatus.length} exceeds maximum ${contextStatus.limit}`);
  }
  
  // Try GPU queue first, fallback to direct API
  try {
    console.log(`Attempting GPU queue for daily summary of ${chatId} on ${date}`);
    const jobId = await submitDailySummaryJob(chatId, date, validatedPrompt, 'yomi_daily');
    const { result } = await waitForJob(jobId, 180000); // 3 minute timeout for daily summaries
    console.log(`GPU queue completed daily summary for ${chatId} on ${date}`);
    return result;
  } catch (queueError) {
    console.log(`GPU queue failed for daily summary ${chatId} on ${date}: ${queueError.message}, falling back to direct API`);
    
    // Fallback to direct API with rate limiting
    return await dailyRateLimiter.run(async () => {
      return await dailyCircuitBreaker.run(async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), LLAMA_REQUEST_TIMEOUT);
        
        try {
          const res = await fetch(LLAMA_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: 'Phi-3-mini-4k-instruct-q4',
              messages: [
                { role: 'system', content: 'You extract structured information from chat conversations and return valid JSON.' },
                { role: 'user', content: validatedPrompt }
              ],
              temperature: 0.3,
              max_tokens: 300,
              stop: ['\n\n']
            }),
            signal: controller.signal
          });
          
          clearTimeout(timeout);
          
          if (!res.ok) throw new Error('llama ' + res.status);
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
        } catch (error) {
          clearTimeout(timeout);
          if (error.name === 'AbortError') {
            throw new Error(`Llama API timeout after ${LLAMA_REQUEST_TIMEOUT}ms`);
          }
          throw error;
        }
      });
    });
  }
}

async function extractBatchDailyWithLlama(prompt, chatId = 'unknown', dates = []) {
  // Use Gemini if enabled
  if (USE_GEMINI) {
    console.log(`Using Gemini for batch daily summary of ${chatId} (${dates.length} dates)`);
    // Detect language from prompt
    const language = detectLanguage(prompt);
    console.log(`Detected language: ${language}`);
    const response = await geminiBatchDailySummary(chatId, dates, prompt, language);
    // Parse JSON response from Gemini
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('no json in response');
    return JSON.parse(jsonMatch[0]);
  }

  // Validate and truncate context length before API call
  const validatedPrompt = validateAndTruncateContext(prompt, chatId);
  const contextStatus = getContextLengthStatus(prompt);
  
  if (!contextStatus.valid) {
    console.error(`Context length validation failed: ${contextStatus.length} > ${contextStatus.limit}`);
    throw new Error(`Context length ${contextStatus.length} exceeds maximum ${contextStatus.limit}`);
  }
  
  // Try GPU queue first, fallback to direct API
  try {
    console.log(`Attempting GPU queue for batch daily summary of ${chatId} (${dates.length} dates)`);
    const jobId = await submitBatchDailySummaryJob(chatId, dates, validatedPrompt, 'yomi_daily_batch');
    const { result } = await waitForJob(jobId, 300000); // 5 minute timeout for batch summaries
    console.log(`GPU queue completed batch daily summary for ${chatId}`);
    return result;
  } catch (queueError) {
    console.log(`GPU queue failed for batch daily summary ${chatId}: ${queueError.message}, falling back to direct API`);
    
    // Fallback to direct API with rate limiting
    return await dailyRateLimiter.run(async () => {
      return await dailyCircuitBreaker.run(async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), LLAMA_REQUEST_TIMEOUT);
        
        try {
          const res = await fetch(LLAMA_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: 'Phi-3-mini-4k-instruct-q4',
              messages: [
                { role: 'system', content: 'You extract structured information from chat conversations and return valid JSON with date keys.' },
                { role: 'user', content: validatedPrompt }
              ],
              temperature: 0.3,
              max_tokens: 600,
              stop: ['\n\n']
            }),
            signal: controller.signal
          });
          
          clearTimeout(timeout);
          
          if (!res.ok) throw new Error('llama ' + res.status);
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
        } catch (error) {
          clearTimeout(timeout);
          if (error.name === 'AbortError') {
            throw new Error(`Llama API timeout after ${LLAMA_REQUEST_TIMEOUT}ms`);
          }
          throw error;
        }
      });
    });
  }
}

async function saveDailySummary(chatId, date, events, actions, topics, messageCount) {
  // Store Thailand calendar date as 17:00 UTC (midnight Thailand time)
  // date is Thailand calendar date (e.g., "2026-08-03")
  // Thailand midnight = UTC 17:00 previous day
  const [year, month, day] = date.split('-').map(Number);
  // Create date as if it were UTC, then subtract 7 hours to get Thailand midnight in UTC
  const utcDate = new Date(Date.UTC(year, month - 1, day, 17, 0, 0)); // 17:00 UTC = midnight Thailand
  const dateWithTime = utcDate.toISOString();
  
  await pool.query(`
    INSERT INTO daily_summaries (chat_id, date, events, actions, topics, message_count)
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (chat_id, date) DO UPDATE SET
      events = EXCLUDED.events,
      actions = EXCLUDED.actions,
      topics = EXCLUDED.topics,
      message_count = EXCLUDED.message_count,
      updated_at = NOW()
  `, [chatId, dateWithTime, events, actions, topics, messageCount]);
}

/**
 * Prioritize dates for Gemini summarization based on mode
 * @param {Array} datesArray - Array of [date, messages] tuples
 * @param {string} mode - Priority mode: 'recent', 'high-activity', 'all'
 * @param {number} limit - Maximum number of dates to process
 * @returns {Array} - Prioritized dates array
 */
function prioritizeDates(datesArray, mode, limit) {
  if (mode === 'all') {
    return datesArray.sort((a, b) => a[0].localeCompare(b[0]));
  }
  
  if (mode === 'recent') {
    // Sort by date descending (most recent first)
    return datesArray
      .sort((a, b) => b[0].localeCompare(a[0]))
      .slice(0, limit);
  }
  
  if (mode === 'high-activity') {
    // Sort by message count descending (most active first)
    return datesArray
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, limit);
  }
  
  // Default: chronological
  return datesArray.sort((a, b) => a[0].localeCompare(b[0]));
}

async function generateDailySummaries(chatId, messages, name, targetDate = null) {
  const byDate = groupMessagesByDate(messages);
  console.log(`generateDailySummaries for ${chatId}: ${byDate.size} dates with messages`);
  console.log(`Available dates: ${Array.from(byDate.keys()).join(', ')}`);
  if (targetDate) {
    console.log(`Target date requested: ${targetDate}`);
  }
  let processed = 0;
  
  // Filter to only process dates within last 30 days
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
  const thirtyDaysAgoStr = thirtyDaysAgo.toISOString().split('T')[0];
  
  const filteredDates = new Map();
  for (const [date, msgs] of byDate) {
    if (date >= thirtyDaysAgoStr) {
      filteredDates.set(date, msgs);
    }
  }
  
  console.log(`Filtered to ${filteredDates.size} dates within last 30 days (skipped ${byDate.size - filteredDates.size} older dates)`);
  console.log(`Filtered dates: ${Array.from(filteredDates.keys()).join(', ')}`);
  
  // If targetDate specified, only process that date
  if (targetDate) {
    const targetKey = targetDate.split('T')[0]; // Extract date part if ISO string
    const targetMessages = filteredDates.get(targetKey);
    if (targetMessages) {
      console.log(`Processing single date: ${targetKey} (${targetMessages.length} messages)`);
      filteredDates.clear();
      filteredDates.set(targetKey, targetMessages);
    } else {
      console.log(`Target date ${targetKey} not found in messages. Available dates: ${Array.from(filteredDates.keys()).join(', ')}`);
      // Don't return - still process other dates if target not found
      console.log(`Target date not found, processing all available dates instead`);
    }
  }
  
  // Apply Gemini-specific prioritization if enabled
  let datesArray = Array.from(filteredDates.entries());
  if (USE_GEMINI && GEMINI_PRIORITY_MODE !== 'all') {
    datesArray = prioritizeDates(datesArray, GEMINI_PRIORITY_MODE, GEMINI_MAX_DATES);
    console.log(`Gemini priority mode: ${GEMINI_PRIORITY_MODE}, processing ${datesArray.length} dates (limit: ${GEMINI_MAX_DATES})`);
  } else {
    // Sort by date chronologically
    datesArray.sort((a, b) => a[0].localeCompare(b[0]));
  }
  
  // Process in batches of 3-5 dates to reduce API calls
  const batchSize = 4;
  for (let i = 0; i < datesArray.length; i += batchSize) {
    const batch = datesArray.slice(i, i + batchSize);
    const batchDates = batch.map(([date]) => date);
    
    try {
      // Try batch processing first
      if (batch.length > 1) {
        console.log(`Processing batch for ${chatId}: ${batchDates.join(', ')} (${batch.length} dates)`);
        const dateGroups = new Map(batch);
        const prompt = buildBatchDailyPrompt(dateGroups, name);
        
        if (prompt) {
          try {
            const extracted = await extractBatchDailyWithLlama(prompt);
            
            // Save each date from the batch response
            for (const [date, dayMessages] of batch) {
              const dateData = extracted[date];
              if (dateData) {
                await saveDailySummary(
                  chatId,
                  date,
                  dateData.events || [],
                  dateData.actions || [],
                  dateData.topics || [],
                  dayMessages.length
                );
                processed++;
                console.log(`Daily summary generated for ${chatId} on ${date} (batch: ${processed}/${byDate.size} complete)`);
              } else {
                console.log(`No data for ${date} in batch response, falling back to single processing`);
                // Fall back to single processing for this date
                await processSingleDate(chatId, date, dayMessages, name, byDate.size, processed);
                processed++;
              }
            }
            continue; // Skip to next batch if successful
          } catch (batchErr) {
            console.log(`Batch processing failed: ${batchErr.message}, falling back to single-date processing`);
            // Fall through to single-date processing
          }
        }
      }
      
      // Fallback to single-date processing
      for (const [date, dayMessages] of batch) {
        await processSingleDate(chatId, date, dayMessages, name, byDate.size, processed);
        processed++;
      }
      
    } catch (err) {
      console.error(`Batch processing failed for ${chatId}: ${err.message}`);
      
      // Handle circuit breaker errors
      if (err.message.includes('Circuit breaker')) {
        console.log('Circuit breaker triggered, skipping remaining daily summaries');
        break;
      }
      
      if (err.message.includes('fetch failed') || err.message.includes('ECONNREFUSED')) {
        console.log('Llama server not available, skipping remaining daily summaries');
        break;
      }
      
      // Reset circuit breaker on other errors to allow recovery
      if (err.message.includes('llama') || err.message.includes('Llama API error')) {
        console.log('Resetting daily circuit breaker after API error');
        dailyCircuitBreaker.reset();
      }
      
      console.log(`Skipping batch due to error, continuing with next batch`);
    }
  }
  
  console.log(`Daily summary generation complete for ${chatId}: ${processed}/${filteredDates.size} days processed`);
}

async function processSingleDate(chatId, date, dayMessages, name, total, processed) {
  try {
    console.log(`Processing ${chatId} on ${date}: ${dayMessages.length} messages`);
    const prompt = buildDailyPrompt(date, dayMessages, name);
    if (!prompt) {
      console.log(`Skipping ${date}: no text content`);
      return;
    }
    const extracted = await extractDailyWithLlama(prompt);
    await saveDailySummary(
      chatId,
      date,
      extracted.events || [],
      extracted.actions || [],
      extracted.topics || [],
      dayMessages.length
    );
    console.log(`Daily summary generated for ${chatId} on ${date} (${processed + 1}/${total} complete)`);
  } catch (err) {
    console.error(`Daily summary failed for ${chatId} on ${date}: ${err.message}`);
    
    // Handle circuit breaker errors
    if (err.message.includes('Circuit breaker')) {
      throw err; // Re-throw to break outer loop
    }
    
    if (err.message.includes('fetch failed') || err.message.includes('ECONNREFUSED')) {
      throw err; // Re-throw to break outer loop
    }
    
    // Reset circuit breaker on other errors to allow recovery
    if (err.message.includes('llama') || err.message.includes('Llama API error')) {
      console.log('Resetting daily circuit breaker after API error');
      dailyCircuitBreaker.reset();
    }
    
    console.log(`Skipping ${date} due to error, continuing with next date`);
  }
}

function isEmptyMessage(m) {
  const text = m.text;
  return (text == null || text === '') && !m.mediaType && m.e2eeDecrypted === true;
}

function markUnavailable(messages) {
  for (const m of messages) {
    if (m.text == null && !m.mediaType) m.mediaType = 'unavailable';
  }
  return messages;
}

function normalizeMessages(messages) {
  const kept = messages.filter(m => !isEmptyMessage(m)).sort((a, b) => (normalizeTimestamp(a.deliveredTime) || 0) - (normalizeTimestamp(b.deliveredTime) || 0));
  return markUnavailable(kept);
}

function mergeMessages(oldMessages = [], newMessages = []) {
  const byId = new Map();
  for (const m of oldMessages) byId.set(m.id, m);
  for (const m of newMessages) byId.set(m.id, m);
  return normalizeMessages([...byId.values()]);
}

async function loadMessages(chatId) {
  const { rows } = await pool.query('SELECT data FROM messages WHERE chat_id = $1 ORDER BY delivered_time ASC', [chatId]);
  return rows.map(r => r.data);
}

async function loadConversations() {
  const { rows } = await pool.query('SELECT chat_id AS id, name, is_group AS "isGroup", category, category_source AS "categorySource", unread, last_message_time AS "lastMessageTime", last_preview AS "lastPreview", summary, meta FROM conversations');
  return rows;
}

async function loadConversation(chatId) {
  const { rows } = await pool.query('SELECT chat_id AS id, name, is_group AS "isGroup", category, category_source AS "categorySource", unread, last_message_time AS "lastMessageTime", last_preview AS "lastPreview", summary, meta FROM conversations WHERE chat_id = $1', [chatId]);
  return rows[0] || null;
}

async function saveMessages(chatId, messages) {
  if (!messages.length) return;
  const ids = messages.map(m => m.id);
  const chatIds = Array(messages.length).fill(chatId);
  const fromNames = messages.map(m => m.fromName || null);
  const deliveredTimes = messages.map(m => normalizeTimestamp(m.deliveredTime) || null);
  const texts = messages.map(m => m.text || null);
  const mediaTypes = messages.map(m => m.mediaType || null);
  const mediaPaths = messages.map(m => m.mediaFile || null);
  const e2ees = messages.map(m => JSON.stringify(m.e2ee ?? null));
  const datas = messages.map(m => JSON.stringify(m));
  await pool.query(`
    INSERT INTO messages (message_id, chat_id, from_name, delivered_time, text, media_type, media_path, e2ee, data)
    SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::bigint[], $5::text[], $6::text[], $7::text[], $8::jsonb[], $9::jsonb[])
    ON CONFLICT (message_id) DO UPDATE SET
      chat_id = EXCLUDED.chat_id,
      from_name = EXCLUDED.from_name,
      delivered_time = EXCLUDED.delivered_time,
      text = EXCLUDED.text,
      media_type = EXCLUDED.media_type,
      media_path = EXCLUDED.media_path,
      e2ee = EXCLUDED.e2ee,
      data = EXCLUDED.data
  `, [ids, chatIds, fromNames, deliveredTimes, texts, mediaTypes, mediaPaths, e2ees, datas]);
}

async function saveConversation(conv) {
  const summaryQuality = conv.summary ? evaluateSummaryQuality(conv.summary) : 0;
  
  await pool.query(`
    INSERT INTO conversations (chat_id, name, is_group, category, category_source, unread, last_message_time, last_preview, summary, summary_quality, summary_generated_at, meta)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    ON CONFLICT (chat_id) DO UPDATE SET
      name = EXCLUDED.name,
      is_group = EXCLUDED.is_group,
      category = EXCLUDED.category,
      category_source = EXCLUDED.category_source,
      unread = EXCLUDED.unread,
      last_message_time = EXCLUDED.last_message_time,
      last_preview = EXCLUDED.last_preview,
      summary = EXCLUDED.summary,
      summary_quality = EXCLUDED.summary_quality,
      summary_generated_at = COALESCE(EXCLUDED.summary_generated_at, conversations.summary_generated_at),
      meta = EXCLUDED.meta,
      updated_at = NOW()
  `, [conv.id, conv.name, conv.isGroup, conv.category, conv.categorySource, conv.unread, conv.lastMessageTime, conv.lastPreview, conv.summary, summaryQuality, conv.summaryGeneratedAt || new Date(), JSON.stringify(conv.meta || {})]);
}

const isMain = process.argv[1] === new URL(import.meta.url).pathname;

async function refreshSingle(chatId, forceRefresh = false, targetDate = null) {
  const messages = mergeMessages(await loadMessages(chatId), await getChatMessages(chatId, 100));
  await saveMessages(chatId, messages);
  const conv = await loadConversation(chatId);
  if (conv) {
    conv.lastMessageTime = messages.reduce((max, m) => Math.max(max, normalizeTimestamp(m.deliveredTime) || 0), 0);
    const byTimeDesc = [...messages].sort((a, b) => (normalizeTimestamp(b.deliveredTime) || 0) - (normalizeTimestamp(a.deliveredTime) || 0));
    const lastPreviewMsg = byTimeDesc.find(m => m.text != null || (m.mediaType && m.mediaType !== 'unavailable'));
    conv.lastPreview = lastPreviewMsg ? (lastPreviewMsg.text ?? `[${lastPreviewMsg.mediaType.toLowerCase()}]`) : null;
    conv.summary = await getSummary(chatId, messages, conv.name, forceRefresh);
    conv.summaryQuality = conv.summary ? evaluateSummaryQuality(conv.summary) : 0;
    conv.summaryGeneratedAt = new Date();
    const result = categorize(conv);
    conv.category = result.category;
    conv.categorySource = result.source;
    await generateDailySummaries(chatId, messages, conv.name, targetDate);
    conv.isGroup = result.isGroup;
    await saveConversation(conv);
  }
  saveSummaryCache();
  console.log(`Refreshed ${chatId}: ${messages.length} messages`);
}

async function exportAll() {
  const result = await client.callTool({ name: 'list_conversations', arguments: { limit: 200 } });
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

  records.sort((a, b) => b.unread - a.unread);

  mkdirSync(MESSAGES_DIR, { recursive: true });
  let messagesWritten = 0;
  for (const c of records) {
    try {
      const messages = mergeMessages(await loadMessages(c.id), await getChatMessages(c.id, 100));
      c.lastMessageTime = messages.reduce((max, m) => Math.max(max, normalizeTimestamp(m.deliveredTime) || 0), 0);
      const byTimeDesc = [...messages].sort((a, b) => (normalizeTimestamp(b.deliveredTime) || 0) - (normalizeTimestamp(a.deliveredTime) || 0));
      const lastPreviewMsg = byTimeDesc.find(m => m.text != null || (m.mediaType && m.mediaType !== 'unavailable'));
      c.lastPreview = lastPreviewMsg ? (lastPreviewMsg.text ?? `[${lastPreviewMsg.mediaType.toLowerCase()}]`) : null;
      c.summary = await getSummary(c.id, messages, c.name);
      c.summaryQuality = c.summary ? evaluateSummaryQuality(c.summary) : 0;
      c.summaryGeneratedAt = new Date();
      await saveMessages(c.id, messages);
      messagesWritten++;
    } catch (err) {
      console.error(`Failed to fetch messages for ${c.id}: ${err.message}`);
    }
  }

  const oldById = {};
  for (const c of await loadConversations()) oldById[c.id] = c;

  for (const c of records) {
    const old = oldById[c.id];
    if (old) {
      if (old.category != null) c.category = old.category;
      if (old.categorySource != null) c.categorySource = old.categorySource;
      if (old.isGroup != null) c.isGroup = old.isGroup;
    }
    const result = categorize(c);
    c.category = result.category;
    c.categorySource = result.source;
    c.isGroup = result.isGroup;
  }

  const generatedAt = new Date().toISOString();
  for (const c of records) await saveConversation(c);
  console.log(`Wrote ${records.length} conversations to Postgres`);
  console.log(`Wrote ${messagesWritten} message chats to Postgres`);

  saveSummaryCache();
}

async function main() {
  const i = process.argv.indexOf('--chat');
  const singleChat = i !== -1 ? process.argv[i + 1] : null;
  const forceIdx = process.argv.indexOf('--force');
  const forceRefresh = forceIdx !== -1;
  const dateIdx = process.argv.indexOf('--date');
  const targetDate = dateIdx !== -1 ? process.argv[dateIdx + 1] : null;
  
  if (singleChat) {
    await refreshSingle(singleChat, forceRefresh, targetDate);
  } else {
    await exportAll();
  }
}

if (isMain) {
  main()
    .then(() => client.close())
    .catch(err => {
      console.error(err);
      client.close().catch(() => {});
      process.exit(1);
    });
}
