import { readFileSync, existsSync, readdirSync, writeFileSync } from 'node:fs';
import { categorize } from './categorize-conversations.mjs';
import { evaluateSummaryQuality, isMeaningfulSummary, retryWithBackoff, generateCacheKey, parseCacheKey } from './summary-utils.mjs';
import { summaryRateLimiter, dailyRateLimiter, summaryCircuitBreaker, dailyCircuitBreaker } from './llama-rate-limiter.mjs';
import pool from './db.mjs';

const FETCH_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/fetch-data';
const SUMMARY_CACHE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/summaries.json';
const STATUS_FILE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json';
const LLAMA_URL = process.env.LLAMA_URL || 'http://localhost:8001/v1/chat/completions';
const BATCH_SIZE = parseInt(process.env.YOMI_BATCH_SIZE || '10', 10);

// Commercial/automated services to exclude from daily summarization
const COMMERCIAL_EXCLUDE_LIST = [
  'u1af0dd1cbe6d9105523d59cc4571c063', // LINE SHOPPING
  'u99658af1c968a8ce4bb64f6dcf32f9c5', // ShopeeTH
  'u928714709faadbd0f7a3a42afbe2b224', // KTC
  'u12c8fccff1226d68b9ca4eebfcea8871', // LINE for Business
  'u085311ecd9e3e3d74ae4c9f5437cbcb5', // LINE
  'u51f0f6960dc4c23e67329df872006a51', // LINE GAME
  'ue72e27967c86078c23a010df435a1ab9', // Big C TH
  'ua23f988a25b95baa3f6d3be7c429bd12', // KEX Thailand
  'uce372f6ada1d1a0855973fefc2942f9a', // Krungthai Connext
  // Add more commercial service IDs as needed
];

function isCommercialService(chatId, name) {
  // Check by chat ID
  if (COMMERCIAL_EXCLUDE_LIST.includes(chatId)) {
    console.log(`Excluding commercial service ${name} (${chatId}) from daily summarization`);
    return true;
  }
  
  // Check by name patterns
  const commercialPatterns = [
    /LINE\s*SHOPPING/i,
    /Shopee/i,
    /KTC/i,
    /LINE\s*for\s*Business/i,
    /Official\s*Account/i,
    /Promo/i,
    /Promotion/i,
    /Big C/i,
    /KEX/i,
    /Krungthai/i,
    /LINE\s*GAME/i,
    /Connext/i
  ];
  
  for (const pattern of commercialPatterns) {
    if (pattern.test(name)) {
      console.log(`Excluding commercial service ${name} (${chatId}) from daily summarization (pattern match)`);
      return true;
    }
  }
  
  return false;
}

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
          // Reset circuit breaker on retry to allow recovery
          if (error.message.includes('Circuit breaker')) {
            console.log('Resetting circuit breaker for retry');
            summaryCircuitBreaker.reset();
          }
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
  return await summaryRateLimiter.run(async () => {
    return await summaryCircuitBreaker.run(async () => {
      const res = await fetch(LLAMA_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'Phi-3-mini-4k-instruct-q4',
          messages: [{ role: 'user', content: prompt }],
          max_tokens: 150,
          temperature: 0.3,
        }),
      });
      if (!res.ok) throw new Error(`Llama API error: ${res.status}`);
      const data = await res.json();
      return data.choices?.[0]?.message?.content?.trim() || null;
    });
  });
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
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(messages);
  console.log(`Detected language for ${name}: ${language}`);
  
  return getLanguageSpecificPrompt(language, name, textOnlyLines);
}

function groupMessagesByDate(messages) {
  const byDate = new Map();
  for (const m of messages) {
    if (!m.deliveredTime) continue;
    try {
      // Convert string timestamp to number
      let timestamp = parseInt(m.deliveredTime, 10);
      if (isNaN(timestamp)) {
        console.warn(`Invalid deliveredTime (not a number): ${m.deliveredTime}, skipping`);
        continue;
      }
      
      // Handle both millisecond and microsecond timestamps
      if (timestamp > 2500000000000) {
        // If timestamp is in microseconds, convert to milliseconds
        timestamp = Math.floor(timestamp / 1000);
      }
      
      const date = new Date(timestamp).toISOString().split('T')[0];
      if (!byDate.has(date)) byDate.set(date, []);
      byDate.get(date).push(m);
    } catch (err) {
      console.warn(`Invalid deliveredTime for message: ${m.deliveredTime}, skipping`);
    }
  }
  return byDate;
}

function buildDailyPrompt(date, messages, name) {
  const lines = messages.map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = m.text || (m.mediaType ? `[${m.mediaType}]` : null);
    if (!text) return null;
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  if (lines.length === 0) return null;
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(messages);
  console.log(`Detected language for daily summary ${name} on ${date}: ${language}`);
  
  return getLanguageSpecificDailyPrompt(language, date, name, lines);
}

function getLanguageSpecificDailyPrompt(language, date, name, lines) {
  const baseContent = lines.join('\n');
  
  switch (language) {
    case 'thai':
      return `สกัดข้อมูลจากข้อความ LINE วันที่ ${date} ในการสนทนากับ ${name}:
- เหตุการณ์ (สิ่งที่เกิดขึ้น)
- การกระทำ (สิ่งที่คนทำหรือวางแผนจะทำ)
- หัวข้อ (เรื่องหลักที่พูดคุย)

รูปแบบ JSON:
{
  "events": ["เหตุการณ์1", "เหตุการณ์2"],
  "actions": ["การกระทำ1", "การกระทำ2"],
  "topics": ["หัวข้อ1", "หัวข้อ2"]
}

ข้อความ:
${baseContent}`;

    case 'mixed':
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
${baseContent}`;

    case 'english':
    default:
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
${baseContent}`;
  }
}

function buildBatchDailyPrompt(dateGroups, name) {
  const dateSections = [];
  const allMessages = [];
  
  for (const [date, messages] of dateGroups) {
    const lines = messages.map(m => {
      const from = m.fromName || m.from || 'Unknown';
      const text = m.text || (m.mediaType ? `[${m.mediaType}]` : null);
      if (!text) return null;
      return `${from}: ${String(text).replace(/\n/g, ' ')}`;
    }).filter(Boolean);
    
    if (lines.length > 0) {
      dateSections.push(`=== ${date} ===\n${lines.join('\n')}`);
      allMessages.push(...messages);
    }
  }
  
  if (dateSections.length === 0) return null;
  
  const dates = Array.from(dateGroups.keys()).join(', ');
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(allMessages);
  console.log(`Detected language for batch daily summary ${name}: ${language}`);
  
  return getLanguageSpecificBatchDailyPrompt(language, name, dates, dateSections);
}

function getLanguageSpecificBatchDailyPrompt(language, name, dates, dateSections) {
  const baseContent = dateSections.join('\n\n');
  
  switch (language) {
    case 'thai':
      return `สกัดข้อมูลจากข้อความ LINE ในการสนทนากับ ${name} หลายวัน (${dates}):
- เหตุการณ์ (สิ่งที่เกิดขึ้น)
- การกระทำ (สิ่งที่คนทำหรือวางแผนจะทำ)
- หัวข้อ (เรื่องหลักที่พูดคุย)

รูปแบบ JSON พร้อมคีย์วันที่:
{
  "YYYY-MM-DD": {
    "events": ["เหตุการณ์1", "เหตุการณ์2"],
    "actions": ["การกระทำ1", "การกระทำ2"],
    "topics": ["หัวข้อ1", "หัวข้อ2"]
  },
  "YYYY-MM-DD": {
    "events": ["เหตุการณ์1"],
    "actions": ["การกระทำ1"],
    "topics": ["หัวข้อ1"]
  }
}

ข้อความ:
${baseContent}`;

    case 'mixed':
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
${baseContent}`;

    case 'english':
    default:
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
${baseContent}`;
  }
}

async function extractDailyWithLlama(prompt) {
  return await dailyRateLimiter.run(async () => {
    return await dailyCircuitBreaker.run(async () => {
      const res = await fetch(LLAMA_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'Phi-3-mini-4k-instruct-q4',
          messages: [
            { role: 'system', content: 'You extract structured information from chat conversations and return valid JSON.' },
            { role: 'user', content: prompt }
          ],
          temperature: 0.3,
          max_tokens: 300,
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
    });
  });
}

async function extractBatchDailyWithLlama(prompt) {
  return await dailyRateLimiter.run(async () => {
    return await dailyCircuitBreaker.run(async () => {
      const res = await fetch(LLAMA_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'Phi-3-mini-4k-instruct-q4',
          messages: [
            { role: 'system', content: 'You extract structured information from chat conversations and return valid JSON with date keys.' },
            { role: 'user', content: prompt }
          ],
          temperature: 0.3,
          max_tokens: 600,
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
    });
  });
}

async function saveDailySummary(chatId, date, events, actions, topics, messageCount) {
  await pool.query(`
    INSERT INTO daily_summaries (chat_id, date, events, actions, topics, message_count)
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (chat_id, date) DO UPDATE SET
      events = EXCLUDED.events,
      actions = EXCLUDED.actions,
      topics = EXCLUDED.topics,
      message_count = EXCLUDED.message_count,
      updated_at = NOW()
  `, [chatId, date, events, actions, topics, messageCount]);
}

async function generateDailySummaries(chatId, messages, name) {
  const byDate = groupMessagesByDate(messages);
  console.log(`generateDailySummaries for ${chatId}: ${byDate.size} dates with messages`);
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
  
  // Convert to array and sort by date
  const datesArray = Array.from(filteredDates.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  
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
      if (err.message.includes('Llama API error')) {
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
    if (err.message.includes('Llama API error')) {
      console.log('Resetting daily circuit breaker after API error');
      dailyCircuitBreaker.reset();
    }
    
    console.log(`Skipping ${date} due to error, continuing with next date`);
  }
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
  
  // Generate daily summaries
  await generateDailySummaries(chatId, messages, conv.name);
  
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
      conversations.push({ 
        chatId, 
        lastMessageTime: data.lastMessageTime,
        isGroup: data.isGroup || false
      });
    }
  }
  
  // Prioritize conversations: one-on-one > recent > older
  const thirtyDaysAgo = Date.now() - (30 * 24 * 60 * 60 * 1000);
  conversations.sort((a, b) => {
    // One-on-one conversations first
    if (a.isGroup !== b.isGroup) {
      return a.isGroup ? 1 : -1;
    }
    
    // Recent conversations (last 30 days) next
    const aRecent = (a.lastMessageTime || 0) > thirtyDaysAgo;
    const bRecent = (b.lastMessageTime || 0) > thirtyDaysAgo;
    if (aRecent !== bRecent) {
      return aRecent ? -1 : 1;
    }
    
    // Within same priority, newest first
    return (b.lastMessageTime || 0) - (a.lastMessageTime || 0);
  });
  
  console.log(`Processing ${conversations.length} conversations (prioritized: one-on-one + recent first)...`);
  console.log(`Rate limiter status: ${JSON.stringify(summaryRateLimiter.getStats())}`);
  console.log(`Circuit breaker status: ${JSON.stringify(summaryCircuitBreaker.getState())}`);
  
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
    
    // Process conversations in parallel for daily summaries (up to 3 concurrent)
    const parallelLimit = 3;
    for (let j = 0; j < batch.length; j += parallelLimit) {
      const parallelBatch = batch.slice(j, j + parallelLimit);
      const results = await Promise.allSettled(
        parallelBatch.map(({ chatId }) => processSingle(chatId, forceSummarize))
      );
      
      for (const result of results) {
        if (result.status === 'fulfilled' && result.value.success) {
          successCount++;
          totalQuality += result.value.quality || 0;
        } else {
          failCount++;
        }
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
      console.log(`Rate limiter status: ${JSON.stringify(summaryRateLimiter.getStats())}`);
      console.log(`Circuit breaker status: ${JSON.stringify(summaryCircuitBreaker.getState())}`);
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
