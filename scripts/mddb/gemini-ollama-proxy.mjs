#!/usr/bin/env node
import { createServer } from 'node:http';

const PORT = parseInt(process.env.GEMINI_PROXY_PORT || '11435', 10);
const HOST = process.env.GEMINI_PROXY_HOST || '0.0.0.0';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_EMBEDDING_MODEL = process.env.GEMINI_EMBEDDING_MODEL || 'gemini-embedding-002';
const GEMINI_EMBEDDING_FALLBACK_MODEL = process.env.GEMINI_EMBEDDING_FALLBACK_MODEL || (GEMINI_EMBEDDING_MODEL === 'gemini-embedding-001' ? 'gemini-embedding-002' : 'gemini-embedding-001');
const DEFAULT_DIMENSIONS = parseInt(process.env.GEMINI_EMBEDDING_DIMENSIONS || '768', 10);
const MAX_RPM = parseInt(process.env.GEMINI_PROXY_MAX_RPM || '100', 10);
const BATCH_SIZE = parseInt(process.env.GEMINI_PROXY_BATCH_SIZE || '100', 10);
const MAX_RETRIES = parseInt(process.env.GEMINI_PROXY_MAX_RETRIES || '5', 10);
const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 30000;

const MODEL_ALIASES = {
  'text-embedding-004': 'gemini-embedding-002',
  'nomic-embed-text': 'gemini-embedding-002',
  'gemini-embedding-001': 'gemini-embedding-001',
  'gemini-embedding-1': 'gemini-embedding-001',
  'gemini-embedding-002': 'gemini-embedding-002',
  'gemini-embedding-2': 'gemini-embedding-002',
  'gemini-embedding-2-preview': 'gemini-embedding-002',
};

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function sendJson(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(body);
}

function resolveGeminiModel(requested) {
  const key = (requested || '').toLowerCase().trim();
  return MODEL_ALIASES[key] || GEMINI_EMBEDDING_MODEL;
}

class RateLimiter {
  constructor(rpm) {
    this.minInterval = 60000 / rpm;
    this.nextAvailable = 0;
    this.tail = Promise.resolve();
  }

  acquire() {
    const p = this.tail;
    this.tail = p.then(async () => {
      const now = Date.now();
      const wait = Math.max(0, this.nextAvailable - now);
      if (wait > 0) await sleep(wait);
      this.nextAvailable = Date.now() + this.minInterval;
    });
    return this.tail;
  }
}

const geminiRateLimiter = new RateLimiter(MAX_RPM);

function retryAfterMs(response) {
  const raw = response.headers.get('retry-after') || response.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = parseInt(raw, 10);
  return isNaN(seconds) ? null : seconds * 1000;
}

function parseGeminiBatch(data, count) {
  if (!data.embeddings || !Array.isArray(data.embeddings)) {
    if (data.embedding && Array.isArray(data.embedding.values)) {
      return [data.embedding.values];
    }
    throw new Error('unexpected Gemini response: missing embeddings array');
  }
  if (data.embeddings.length !== count) {
    throw new Error(`expected ${count} embeddings, got ${data.embeddings.length}`);
  }
  return data.embeddings.map((entry, i) => {
    if (Array.isArray(entry.values)) return entry.values;
    if (entry.embedding && Array.isArray(entry.embedding.values)) return entry.embedding.values;
    throw new Error(`unexpected embedding shape at index ${i}`);
  });
}

async function _fetchGeminiBatchForModel(texts, geminiModel, outputDimensionality) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${geminiModel}:batchEmbedContents?key=${GEMINI_API_KEY}`;
  const requests = texts.map(text => ({
    model: `models/${geminiModel}`,
    content: { parts: [{ text }] },
    outputDimensionality,
  }));

  let lastError;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      const backoff = Math.min(INITIAL_BACKOFF_MS * (2 ** (attempt - 1)), MAX_BACKOFF_MS);
      await sleep(backoff);
    }

    await geminiRateLimiter.acquire();

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requests }),
    });

    if (response.ok) {
      const data = await response.json();
      return parseGeminiBatch(data, texts.length);
    }

    const errorText = await response.text();
    lastError = `Gemini API error: ${response.status} - ${errorText}`;

    if (response.status === 429) {
      const retryMs = retryAfterMs(response);
      if (retryMs && retryMs > 0) {
        await sleep(Math.min(retryMs, MAX_BACKOFF_MS));
      }
      continue;
    }

    if (response.status >= 500) {
      continue;
    }

    throw new Error(lastError);
  }

  throw new Error(lastError);
}

async function fetchGeminiBatch(texts, geminiModel, outputDimensionality, fallbackModel = null) {
  try {
    return await _fetchGeminiBatchForModel(texts, geminiModel, outputDimensionality);
  } catch (err) {
    if (fallbackModel && String(err).includes('429')) {
      console.log(`Primary Gemini model ${geminiModel} rate-limited; trying fallback ${fallbackModel}`);
      return await _fetchGeminiBatchForModel(texts, fallbackModel, outputDimensionality);
    }
    throw err;
  }
}

async function handleEmbed(req, res) {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk.toString();
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return sendJson(res, 400, { error: 'invalid JSON' });
  }

  const requestedModel = payload.model || 'text-embedding-004';
  const geminiModel = resolveGeminiModel(requestedModel);

  let isSingle;
  let inputs;
  if (typeof payload.input === 'string') {
    isSingle = true;
    inputs = [payload.input];
  } else if (Array.isArray(payload.input)) {
    isSingle = false;
    inputs = payload.input;
  } else if (typeof payload.prompt === 'string') {
    isSingle = true;
    inputs = [payload.prompt];
  } else if (Array.isArray(payload.prompts)) {
    isSingle = false;
    inputs = payload.prompts;
  } else {
    return sendJson(res, 400, { error: 'input must be a non-empty string or array of strings' });
  }
  if (!Array.isArray(inputs) || inputs.length === 0) {
    return sendJson(res, 400, { error: 'input must be a non-empty string or array of strings' });
  }

  for (let i = 0; i < inputs.length; i++) {
    if (typeof inputs[i] !== 'string' || inputs[i].trim().length === 0) {
      return sendJson(res, 400, { error: `input at index ${i} must be a non-empty string` });
    }
  }

  let outputDimensionality = payload.outputDimensionality;
  if (!outputDimensionality && payload.options && payload.options.outputDimensionality) {
    outputDimensionality = payload.options.outputDimensionality;
  }
  outputDimensionality = outputDimensionality ? parseInt(outputDimensionality, 10) : DEFAULT_DIMENSIONS;

  if (!GEMINI_API_KEY) {
    return sendJson(res, 500, { error: 'GEMINI_API_KEY not configured' });
  }

  const start = process.hrtime.bigint();
  const embeddings = [];
  try {
    for (let i = 0; i < inputs.length; i += BATCH_SIZE) {
      const chunk = inputs.slice(i, i + BATCH_SIZE);
      const chunkEmbeddings = await fetchGeminiBatch(chunk, geminiModel, outputDimensionality, GEMINI_EMBEDDING_FALLBACK_MODEL);
      embeddings.push(...chunkEmbeddings);
    }
  } catch (err) {
    return sendJson(res, 502, { error: err.message });
  }
  const end = process.hrtime.bigint();
  const durationMs = Number((end - start) / 1000000n);

  const result = {
    model: requestedModel,
    gemini_model: geminiModel,
    output_dimensionality: outputDimensionality,
    duration_ms: durationMs,
    embeddings: embeddings,
  };
  if (isSingle) {
    result.embedding = embeddings[0];
  }

  sendJson(res, 200, result);
}

const server = createServer((req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end();
    return;
  }

  if (req.method === 'GET' && req.url === '/health') {
    return sendJson(res, 200, { status: 'ok', gemini_model: GEMINI_EMBEDDING_MODEL, dimensions: DEFAULT_DIMENSIONS });
  }

  if (req.method === 'POST' && (req.url === '/api/embed' || req.url === '/api/embeddings')) {
    return handleEmbed(req, res);
  }

  sendJson(res, 404, { error: 'not found' });
});

server.listen(PORT, HOST, () => {
  console.log(`Gemini-Ollama proxy listening on http://${HOST}:${PORT}`);
});
