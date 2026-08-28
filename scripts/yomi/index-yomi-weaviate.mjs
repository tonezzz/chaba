#!/usr/bin/env node
/**
 * Index Yomi (LINE) messages into Weaviate for semantic search.
 *
 * Creates/updates a YomiMessage collection then batch-indexes
 * text messages from Postgres using GPU embeddings.
 *
 * Usage:
 *   node scripts/yomi/index-yomi-weaviate.mjs            # full re-index
 *   node scripts/yomi/index-yomi-weaviate.mjs --since 7  # last N days only
 */

import pg from 'pg';
import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const EMBEDDING_URL = process.env.EMBEDDING_SERVICE_URL || 'http://localhost:5000';
const BATCH_SIZE = 50;
const COLLECTION = 'YomiMessage';

// --- Postgres ---
const envPath = join(__dirname, '../../stacks/web/.env');
const envVars = {};
try {
  readFileSync(envPath, 'utf8').split('\n').forEach(line => {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m) envVars[m[1].trim()] = m[2].trim();
  });
} catch (_) {}

const pgClient = new pg.Client({
  host: envVars.POSTGRES_HOST || 'localhost',
  port: parseInt(envVars.POSTGRES_PORT || '5432'),
  database: envVars.POSTGRES_DB || 'chaba',
  user: envVars.POSTGRES_USER || 'chaba',
  password: envVars.POSTGRES_PASSWORD || 'chabapass',
});

// --- Helpers ---
async function weaviatePost(path, body) {
  const res = await fetch(`${WEAVIATE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Weaviate ${path} ${res.status}: ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : {};
}

async function weaviateGet(path) {
  const res = await fetch(`${WEAVIATE_URL}${path}`);
  if (!res.ok) throw new Error(`Weaviate GET ${path} ${res.status}`);
  return res.json();
}

async function embedBatch(texts) {
  const res = await fetch(`${EMBEDDING_URL}/embed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texts }),
  });
  if (!res.ok) throw new Error(`Embedding service ${res.status}`);
  const data = await res.json();
  return data.embeddings;
}

// --- Schema ---
async function ensureCollection() {
  try {
    await weaviateGet(`/v1/schema/${COLLECTION}`);
    console.log(`Collection ${COLLECTION} already exists`);
    return;
  } catch (_) {}

  console.log(`Creating collection ${COLLECTION}...`);
  await weaviatePost('/v1/schema', {
    class: COLLECTION,
    vectorizer: 'none',
    vectorIndexConfig: { distance: 'cosine' },
    properties: [
      { name: 'messageId',    dataType: ['text'],   tokenization: 'field' },
      { name: 'chatId',       dataType: ['text'],   tokenization: 'field' },
      { name: 'chatName',     dataType: ['text'],   tokenization: 'word' },
      { name: 'category',     dataType: ['text'],   tokenization: 'field' },
      { name: 'fromName',     dataType: ['text'],   tokenization: 'word' },
      { name: 'text',         dataType: ['text'],   tokenization: 'word' },
      { name: 'deliveredTime',dataType: ['int'] },
      { name: 'isGroup',      dataType: ['boolean'] },
    ],
  });
  console.log(`Collection ${COLLECTION} created`);
}

// --- Already-indexed set ---
async function fetchIndexedIds() {
  const ids = new Set();
  let cursor = null;
  while (true) {
    const after = cursor ? `&after=${cursor}` : '';
    const res = await fetch(
      `${WEAVIATE_URL}/v1/objects?class=${COLLECTION}&limit=250&properties=messageId${after}`
    );
    const data = await res.json();
    const objects = data.objects || [];
    if (objects.length === 0) break;
    for (const obj of objects) ids.add(obj.properties?.messageId);
    cursor = objects[objects.length - 1].id;
    if (objects.length < 250) break;
  }
  return ids;
}

// --- Main ---
async function main() {
  const sinceArg = process.argv.indexOf('--since');
  const sinceDays = sinceArg >= 0 ? parseInt(process.argv[sinceArg + 1] || '7') : null;

  await pgClient.connect();

  await ensureCollection();

  console.log('Fetching already-indexed message IDs...');
  const indexed = await fetchIndexedIds();
  console.log(`Already indexed: ${indexed.size}`);

  const sinceClause = sinceDays
    ? `AND m.delivered_time > ${Date.now() - sinceDays * 86400000}`
    : '';

  const { rows } = await pgClient.query(`
    SELECT m.message_id, m.chat_id, m.from_name, m.delivered_time, m.text,
           c.name AS chat_name, c.category, c.is_group
    FROM messages m
    JOIN conversations c ON c.chat_id = m.chat_id
    WHERE m.text IS NOT NULL AND m.text != '' ${sinceClause}
    ORDER BY m.delivered_time DESC
  `);

  const toIndex = rows.filter(r => !indexed.has(r.message_id));
  console.log(`Messages with text: ${rows.length}, new to index: ${toIndex.length}`);

  if (toIndex.length === 0) {
    console.log('Nothing to index.');
    await pgClient.end();
    return;
  }

  let indexed_count = 0;
  for (let i = 0; i < toIndex.length; i += BATCH_SIZE) {
    const batch = toIndex.slice(i, i + BATCH_SIZE);
    const texts = batch.map(r => r.text);

    let vectors;
    try {
      vectors = await embedBatch(texts);
    } catch (e) {
      console.error(`Embedding failed for batch ${i}: ${e.message}`);
      continue;
    }

    const objects = batch.map((r, idx) => ({
      class: COLLECTION,
      vector: vectors[idx],
      properties: {
        messageId:     r.message_id,
        chatId:        r.chat_id,
        chatName:      r.chat_name || '',
        category:      r.category || '',
        fromName:      r.from_name || '',
        text:          r.text,
        deliveredTime: Number(r.delivered_time) || 0,
        isGroup:       r.is_group || false,
      },
    }));

    const result = await weaviatePost('/v1/batch/objects', { objects });
    const errors = (result || []).filter(r => r.result?.errors);
    if (errors.length) console.warn(`Batch ${i}: ${errors.length} errors`);
    indexed_count += objects.length - errors.length;
    process.stdout.write(`\rIndexed ${indexed_count}/${toIndex.length}...`);
  }

  console.log(`\nDone. Indexed ${indexed_count} new messages.`);
  await pgClient.end();
}

main().catch(e => { console.error(e); process.exit(1); });
