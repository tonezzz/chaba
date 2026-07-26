import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
import { writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname } from 'node:path';

const OUT = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/conversations.json';
const MESSAGES_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/messages';
const MEDIA_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/media';
const SUMMARY_CACHE = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/summaries.json';
const LLAMA_URL = process.env.LLAMA_URL || 'http://localhost:8008/v1/chat/completions';

const transport = new StdioClientTransport({
  command: '/usr/bin/node',
  args: ['/home/tony/.yomi/mcpb/run.mjs'],
});

const client = new Client({ name: 'yomi-conversations-export', version: '0.1' });
await client.connect(transport);

function tokenize(csv) {
  const tokens = [];
  let i = 0;
  while (i < csv.length) {
    while (i < csv.length && /\s/.test(csv[i])) i++;
    if (i >= csv.length) break;
    if (csv[i] === '"') {
      i++;
      let value = '';
      while (i < csv.length) {
        if (csv[i] === '\\' && i + 1 < csv.length) {
          const next = csv[i + 1];
          value += next === 'n' ? '\n' : next === 't' ? '\t' : next;
          i += 2;
          continue;
        }
        if (csv[i] === '"') { i++; break; }
        value += csv[i];
        i++;
      }
      tokens.push(value);
    } else {
      let value = '';
      while (i < csv.length && csv[i] !== ',' && csv[i] !== '\n') {
        value += csv[i];
        i++;
      }
      tokens.push(value);
    }
    if (i < csv.length && csv[i] === ',') i++;
  }
  return tokens;
}

function parseRows(text, fieldCount) {
  const firstNewline = text.indexOf('\n');
  const body = firstNewline >= 0 ? text.slice(firstNewline + 1) : text;
  const tokens = tokenize(body);
  const rows = [];
  for (let j = 0; j + fieldCount <= tokens.length; j += fieldCount) {
    rows.push(tokens.slice(j, j + fieldCount));
  }
  return rows;
}

async function downloadImage(chatId, messageId) {
  const dir = `${MEDIA_DIR}/${chatId}`;
  mkdirSync(dir, { recursive: true });
  const result = await client.callTool({ name: 'get_message_media', arguments: { chatId, messageId, preview: false } });
  const part = result.content?.[0];
  if (!part || part.type !== 'image' || !part.data) return null;
  const mime = part.mimeType || 'image/jpeg';
  let ext = mime.split('/').pop().replace(/[^a-z0-9]/gi, '') || 'jpg';
  if (ext === 'jpeg') ext = 'jpg';
  const fileName = `${messageId}.${ext}`;
  const filePath = `${dir}/${fileName}`;
  if (existsSync(filePath)) return { fileName, mime };
  writeFileSync(filePath, Buffer.from(part.data, 'base64'));
  return { fileName, mime };
}

async function getChatMessages(chatId, count = 20) {
  const result = await client.callTool({ name: 'get_chat_messages', arguments: { chatId, count } });
  const text = result.content?.[0]?.text ?? '';
  const rows = parseRows(text, 9);
  const messages = rows.map(r => ({
    createdTime: parseInt(r[0], 10),
    deliveredTime: parseInt(r[1], 10),
    from: r[2],
    fromName: r[3],
    id: r[4],
    mediaType: r[5] === 'null' ? null : r[5],
    mentions: r[6] === 'null' ? null : r[6],
    text: r[7] === 'null' ? null : r[7],
    e2eeDecrypted: r[8] === 'null' ? null : r[8] === 'true',
  }));
  await Promise.all(messages.map(async m => {
    if (String(m.mediaType).toLowerCase() !== 'image') return;
    try {
      const info = await downloadImage(chatId, m.id);
      if (info) {
        m.mediaFile = info.fileName;
        m.mediaMime = info.mime;
      }
    } catch (err) {
      console.error(`Failed to download image ${chatId}/${m.id}: ${err.message}`);
    }
  }));
  return messages;
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
  const sorted = [...messages].sort((a, b) => (a.deliveredTime || 0) - (b.deliveredTime || 0));
  const lines = sorted.slice(-40).map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = m.text || mediaLabel(m);
    if (!text) return null;
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  if (lines.length === 0) return null;
  return `Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision.\n\n${lines.join('\n')}\n\nSummary:`;
}

async function summarizeWithLlama(prompt) {
  const res = await fetch(LLAMA_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [
        { role: 'system', content: 'You write concise one-sentence summaries of chat conversations.' },
        { role: 'user', content: prompt }
      ],
      temperature: 0.4,
      max_tokens: 60,
      stop: ['\n']
    })
  });
  if (!res.ok) throw new Error('llama ' + res.status);
  const data = await res.json();
  const content = data.choices?.[0]?.message?.content?.trim();
  if (!content) throw new Error('empty llama response');
  return content.replace(/\s+/g, ' ');
}

async function getSummary(chatId, messages, name) {
  const lastTime = messages.reduce((max, m) => Math.max(max, m.deliveredTime || 0), 0);
  const cached = summaryCache[chatId];
  if (cached && cached.lastMessageTime === lastTime && cached.summary) {
    return cached.summary;
  }
  const prompt = buildPrompt(name, messages);
  if (!prompt) {
    summaryCache[chatId] = { lastMessageTime: lastTime, summary: null };
    return null;
  }
  try {
    const summary = await summarizeWithLlama(prompt);
    summaryCache[chatId] = { lastMessageTime: lastTime, summary };
    return summary;
  } catch (err) {
    console.error(`Summary failed for ${chatId}: ${err.message}`);
    return cached?.summary || null;
  }
}

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
  const match = trimmed.match(/^(\S+),(null|"(?:[^"\\]|\\.)*"),(.*),(\d+)$/);
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
    const messages = await getChatMessages(c.id, 20);
    c.lastMessageTime = messages.reduce((max, m) => Math.max(max, m.deliveredTime || 0), 0);
    const byTimeDesc = [...messages].sort((a, b) => (b.deliveredTime || 0) - (a.deliveredTime || 0));
    const lastTextMsg = byTimeDesc.find(m => m.text != null);
    const lastMsg = byTimeDesc[0];
    c.lastPreview = lastTextMsg ? lastTextMsg.text : (lastMsg?.mediaType ? `[${lastMsg.mediaType.toLowerCase()}]` : null);
    c.summary = await getSummary(c.id, messages, c.name);
    const msgPath = `${MESSAGES_DIR}/${c.id}.json`;
    writeFileSync(msgPath, JSON.stringify({
      generatedAt: new Date().toISOString(),
      messages,
    }, null, 2));
    messagesWritten++;
  } catch (err) {
    console.error(`Failed to fetch messages for ${c.id}: ${err.message}`);
  }
}

mkdirSync(dirname(OUT), { recursive: true });
const generatedAt = new Date().toISOString();
writeFileSync(OUT, JSON.stringify({
  generatedAt,
  conversations: records,
}, null, 2));
console.log(`Wrote ${records.length} conversations to ${OUT}`);
console.log(`Wrote ${messagesWritten} message files to ${MESSAGES_DIR}`);

saveSummaryCache();
await client.close();
