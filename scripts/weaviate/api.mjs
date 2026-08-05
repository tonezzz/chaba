#!/usr/bin/env node

/**
 * Weaviate Search API
 *
 * Hybrid semantic search (BM25 + vector) over SSOTDocument collection.
 * Embeds the query via the local GPU embedding service, then runs
 * Weaviate's hybrid search (alpha=0.5 balances keyword vs vector).
 */

import { createServer } from 'http';

const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const EMBEDDING_URL = process.env.EMBEDDING_SERVICE_URL || 'http://localhost:5000';
const PORT = process.env.PORT || 3002;

console.log('Weaviate Search API starting...');
console.log('Weaviate URL:', WEAVIATE_URL);
console.log('Embedding URL:', EMBEDDING_URL);

async function embedQuery(text) {
  const res = await fetch(`${EMBEDDING_URL}/embed-single`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`Embedding service error: ${res.status}`);
  const data = await res.json();
  return data.embedding;
}

async function hybridSearch(query, vector, limit, filters) {
  const whereClause = buildWhereClause(filters);
  const gql = `{
    Get {
      SSOTDocument(
        hybrid: {
          query: ${JSON.stringify(query)}
          vector: ${JSON.stringify(vector)}
          alpha: 0.5
        }
        limit: ${limit}
        ${whereClause ? `where: ${whereClause}` : ''}
      ) {
        title
        content
        path
        type
        category
        tags
        language
        _additional { score }
      }
    }
  }`;

  const res = await fetch(`${WEAVIATE_URL}/v1/graphql`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: gql }),
  });
  if (!res.ok) throw new Error(`Weaviate error: ${res.status}`);
  const data = await res.json();
  if (data.errors) throw new Error(data.errors.map(e => e.message).join('; '));
  return data.data.Get.SSOTDocument || [];
}

function buildWhereClause(filters) {
  if (!filters || Object.keys(filters).length === 0) return '';
  const operands = [];
  if (filters.type) {
    operands.push(`{path:["type"] operator:Equal valueText:${JSON.stringify(filters.type)}}`);
  }
  if (filters.category) {
    operands.push(`{path:["category"] operator:Equal valueText:${JSON.stringify(filters.category)}}`);
  }
  if (operands.length === 0) return '';
  if (operands.length === 1) return operands[0];
  return `{operator:And operands:[${operands.join(',')}]}`;
}

async function handleSearch(req, res) {
  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Method not allowed' }));
    return;
  }

  try {
    const body = await getRequestBody(req);
    const { query, limit = 20, filters = {} } = JSON.parse(body);
    if (!query || !query.trim()) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'query is required' }));
      return;
    }

    console.log('Search query:', query, filters);

    const vector = await embedQuery(query);
    const raw = await hybridSearch(query, vector, limit, filters);

    const results = raw.map(r => ({
      title: r.title,
      content: r.content,
      path: r.path,
      type: r.type,
      category: r.category,
      tags: r.tags || [],
      language: r.language,
      similarity: parseFloat(parseFloat(r._additional?.score || 0).toFixed(4)),
    }));

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ results, total: results.length, mode: 'hybrid' }));

  } catch (error) {
    console.error('Search error:', error);
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: error.message }));
  }
}

async function handleHealth(req, res) {
  let weaviateOk = false;
  let embeddingOk = false;
  let docCount = 0;

  try {
    const r = await fetch(`${WEAVIATE_URL}/v1/.well-known/ready`);
    weaviateOk = r.ok;
  } catch (_) {}

  try {
    const r = await fetch(`${EMBEDDING_URL}/health`);
    embeddingOk = r.ok;
  } catch (_) {}

  try {
    const r = await fetch(`${WEAVIATE_URL}/v1/graphql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '{Aggregate{SSOTDocument{meta{count}}}}' }),
    });
    const d = await r.json();
    docCount = d?.data?.Aggregate?.SSOTDocument?.[0]?.meta?.count || 0;
  } catch (_) {}

  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    status: weaviateOk && embeddingOk ? 'healthy' : 'degraded',
    mode: 'hybrid',
    weaviate: weaviateOk ? 'ok' : 'error',
    embedding: embeddingOk ? 'ok' : 'error',
    total_documents: docCount,
  }));
}

function getRequestBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  if (url.pathname === '/search') {
    await handleSearch(req, res);
  } else if (url.pathname === '/health') {
    await handleHealth(req, res);
  } else {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('Weaviate Search API running on port', PORT);
  console.log('Endpoints:');
  console.log('  POST http://localhost:' + PORT + '/search');
  console.log('  GET  http://localhost:' + PORT + '/health');
});
