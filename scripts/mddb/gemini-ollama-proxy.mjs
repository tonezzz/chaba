#!/usr/bin/env node
import { createServer } from 'node:http';

const PORT = parseInt(process.env.GEMINI_PROXY_PORT || '11435', 10);
const HOST = process.env.GEMINI_PROXY_HOST || '0.0.0.0';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_EMBEDDING_MODEL = process.env.GEMINI_EMBEDDING_MODEL || 'gemini-embedding-001';
const DEFAULT_DIMENSIONS = parseInt(process.env.GEMINI_EMBEDDING_DIMENSIONS || '768', 10);

const MODEL_ALIASES = {
  'text-embedding-004': GEMINI_EMBEDDING_MODEL,
  'nomic-embed-text': GEMINI_EMBEDDING_MODEL,
  'gemini-embedding-001': 'gemini-embedding-001',
  'gemini-embedding-2': 'gemini-embedding-2',
  'gemini-embedding-2-preview': 'gemini-embedding-2-preview',
};

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

async function fetchGeminiEmbedding(text, geminiModel, outputDimensionality) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${geminiModel}:embedContent?key=${GEMINI_API_KEY}`;
  const body = {
    content: { parts: [{ text }] },
  };
  if (outputDimensionality) {
    body.outputDimensionality = outputDimensionality;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Gemini API error: ${response.status} - ${error}`);
  }

  const data = await response.json();
  return data.embedding.values;
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

  let inputs = payload.input;
  if (typeof inputs === 'string') {
    inputs = [inputs];
  } else if (!Array.isArray(inputs) || inputs.length === 0) {
    return sendJson(res, 400, { error: 'input must be a non-empty string or array of strings' });
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
  for (const text of inputs) {
    if (typeof text !== 'string' || text.trim().length === 0) {
      return sendJson(res, 400, { error: 'each input must be a non-empty string' });
    }
    try {
      const values = await fetchGeminiEmbedding(text, geminiModel, outputDimensionality);
      embeddings.push(values);
    } catch (err) {
      return sendJson(res, 502, { error: err.message });
    }
  }
  const end = process.hrtime.bigint();
  const durationMs = Number((end - start) / 1000000n);

  sendJson(res, 200, {
    model: requestedModel,
    gemini_model: geminiModel,
    output_dimensionality: outputDimensionality,
    embeddings,
    duration_ms: durationMs,
  });
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

  if (req.method === 'POST' && req.url === '/api/embed') {
    return handleEmbed(req, res);
  }

  sendJson(res, 404, { error: 'not found' });
});

server.listen(PORT, HOST, () => {
  console.log(`Gemini-Ollama proxy listening on http://${HOST}:${PORT}`);
});
