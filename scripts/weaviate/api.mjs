#!/usr/bin/env node

/**
 * Weaviate Search API
 * 
 * Simple HTTP API for semantic search of SSOT documents
 * Currently using mock data for testing
 */

import { createServer } from 'http';

const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const PORT = process.env.PORT || 3002;

console.log('Weaviate Search API starting...');
console.log('Weaviate URL:', WEAVIATE_URL);

// Mock search results for testing
const mockResults = [
  {
    title: 'GPU Queue Management',
    content: 'GPU queue system for efficient resource allocation across llama, imagen2, and txt2vid workloads',
    path: 'docs/ssot/infrastructure/ssot.gpu.yml',
    type: 'ssot',
    category: 'infrastructure',
    tags: ['gpu', 'queue', 'management'],
    language: 'en',
    similarity: 0.95
  },
  {
    title: 'Weaviate Vector Database',
    content: 'Vector database configuration for semantic search and RAG pipelines',
    path: 'docs/ssot/ssot.test.weaviate.yml',
    type: 'ssot',
    category: 'infrastructure',
    tags: ['weaviate', 'vector', 'search'],
    language: 'en',
    similarity: 0.88
  },
  {
    title: 'Thai Legal Document Processing',
    content: 'Thai legal document processing with multilingual support using Gemma model',
    path: 'docs/overview/sessions/thai-legal.yml',
    type: 'session',
    category: 'sessions',
    tags: ['thai', 'legal', 'gemma'],
    language: 'th',
    similarity: 0.82
  },
  {
    title: 'Docker Configuration',
    content: 'Docker compose configuration for web services and infrastructure',
    path: 'stacks/web/docker-compose.yml',
    type: 'docs',
    category: 'infrastructure',
    tags: ['docker', 'compose', 'web'],
    language: 'en',
    similarity: 0.75
  },
  {
    title: 'Caddy Web Server',
    content: 'Caddy reverse proxy configuration for routing and SSL',
    path: 'stacks/web/Caddyfile',
    type: 'docs',
    category: 'infrastructure',
    tags: ['caddy', 'proxy', 'routing'],
    language: 'en',
    similarity: 0.70
  }
];

async function handleSearch(req, res) {
  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Method not allowed' }));
    return;
  }

  try {
    const body = await getRequestBody(req);
    const { query, limit = 20 } = JSON.parse(body);

    console.log('Search query:', query);

    // Return mock results filtered by query
    const filteredResults = mockResults.filter(result =>
      result.title.toLowerCase().includes(query.toLowerCase()) ||
      result.content.toLowerCase().includes(query.toLowerCase()) ||
      result.tags.some(tag => tag.toLowerCase().includes(query.toLowerCase()))
    ).slice(0, limit);

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ results: filteredResults }));

  } catch (error) {
    console.error('Search error:', error);
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: error.message }));
  }
}

async function handleHealth(req, res) {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    status: 'healthy',
    weaviate_url: WEAVIATE_URL,
    mode: 'mock', // Using mock data for testing
    total_documents: mockResults.length
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
