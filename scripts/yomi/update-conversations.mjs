import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const OUT = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/conversations.json';
const MESSAGES_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/messages';

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

async function getChatMessages(chatId, count = 20) {
  const result = await client.callTool({ name: 'get_chat_messages', arguments: { chatId, count } });
  const text = result.content?.[0]?.text ?? '';
  const rows = parseRows(text, 9);
  return rows.map(r => ({
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
    const lastTextMsg = [...messages].sort((a, b) => (b.deliveredTime || 0) - (a.deliveredTime || 0)).find(m => m.text != null);
    c.lastPreview = lastTextMsg ? lastTextMsg.text : null;
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

await client.close();
