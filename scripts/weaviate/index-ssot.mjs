#!/usr/bin/env node

/**
 * SSOT Document Indexer for Weaviate
 * 
 * Indexes SSOT YAML files, session archives, and documentation into Weaviate
 * for semantic search using SEA-LION-E5-Embedding-600M model
 */

import { readFile, readdir, stat } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);
const __dirname = dirname(fileURLToPath(import.meta.url));

// Configuration
const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const EMBEDDING_DIM = 384; // all-MiniLM-L6-v2 (temporary hash-based for testing)
const CHABA_ROOT = '/home/tony/CascadeProjects/chaba';

// Document patterns to index
const DOCUMENT_PATTERNS = [
  { pattern: 'docs/overview/*.md', type: 'docs', category: 'overview' },
];

// Connect to Weaviate using REST API
const WEAVIATE_API = `${WEAVIATE_URL}/v1`;

async function connectToWeaviate() {
  try {
    const response = await fetch(`${WEAVIATE_API}/.well-known/ready`);
    if (response.ok) {
      console.log('Connected to Weaviate at', WEAVIATE_URL);
    } else {
      throw new Error('Weaviate not ready');
    }
  } catch (error) {
    console.error('Failed to connect to Weaviate:', error);
    throw error;
  }
}

// Create collection if it doesn't exist
async function createCollection() {
  try {
    const schema = JSON.parse(
      await readFile(join(__dirname, 'schema.json'), 'utf-8')
    );
    
    try {
      await fetch(`${WEAVIATE_API}/schema/${schema.class}`, {
        method: 'DELETE'
      });
      console.log(`Deleted existing collection: ${schema.class}`);
    } catch (e) {
      // Collection doesn't exist, that's fine
    }
    
    const response = await fetch(`${WEAVIATE_API}/schema`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ class: schema.class, ...schema })
    });
    
    if (!response.ok) {
      throw new Error(`Failed to create collection: ${response.status}`);
    }
    
    console.log(`Created collection: ${schema.class}`);
  } catch (error) {
    console.error('Error creating collection:', error);
    throw error;
  }
}

// Generate embedding using local model
async function generateEmbedding(text) {
  try {
    // Use simple hash-based embedding for testing (no heavy dependencies)
    // This is a temporary solution for testing the pipeline
    const simpleEmbedding = [];
    for (let i = 0; i < 384; i++) {
      // Generate deterministic hash-based embedding
      const charCode = text.charCodeAt(i % text.length) || 0;
      const hash = (charCode * 31 + i) % 1000 / 1000;
      simpleEmbedding.push(hash);
    }
    return simpleEmbedding;
  } catch (error) {
    console.error('Error generating embedding:', error);
    throw error;
  }
}

// Detect language (simple heuristic)
function detectLanguage(text) {
  const thaiChars = text.match(/[\u0E00-\u0E7F]/g);
  if (thaiChars && thaiChars.length > text.length * 0.3) {
    return 'th';
  } else if (thaiChars && thaiChars.length > 0) {
    return 'mixed';
  }
  return 'en';
}

// Extract tags from SSOT YAML
function extractTags(content, type) {
  const tags = [type];
  
  // Extract common keywords
  const keywords = content.match(/\b(apps|infrastructure|gpu|docker|api|database|weaviate|postgres|redis|yomi|track4|imagen|video)\b/gi);
  if (keywords) {
    keywords.forEach(kw => {
      const normalized = kw.toLowerCase();
      if (!tags.includes(normalized)) {
        tags.push(normalized);
      }
    });
  }
  
  return tags;
}

// Chunk text using simple character-based chunking (for testing)
async function chunkText(content, chunkSize = 512, chunkOverlap = 50) {
  try {
    if (content.length <= chunkSize) {
      return [content];
    }
    
    const chunks = [];
    let start = 0;
    while (start < content.length) {
      const end = Math.min(start + chunkSize, content.length);
      chunks.push(content.substring(start, end));
      start = end - chunkOverlap;
      if (start < 0) start = 0;
    }
    return chunks;
  } catch (error) {
    console.warn('Chunking failed, using original content:', error.message);
    return [content]; // Fallback to original content
  }
}

// Index a single document
async function indexDocument(filePath, type, category) {
  try {
    console.log(`Processing: ${filePath}`);
    const content = await readFile(filePath, 'utf-8');
    const stats = await stat(filePath);
    const title = filePath.split('/').pop();
    
    console.log(`Content length: ${content.length} chars`);
    
    // Use full content without chunking for testing
    const chunkContent = content;
    const embedding = await generateEmbedding(chunkContent);
    
    console.log(`Embedding generated: ${embedding.length} dimensions`);
    
    const dataObj = {
      class: 'SSOTDocument',
      properties: {
        title: title,
        content: chunkContent,
        path: filePath,
        type,
        category,
        tags: [],
        language: 'en',
        lastModified: stats.mtime.toISOString(),
        size: stats.size,
        chunkIndex: null,
        totalChunks: null,
      },
      vector: embedding,
    };
    
    console.log(`Sending to Weaviate...`);
    const response = await fetch(`${WEAVIATE_API}/objects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dataObj)
    });
    
    if (!response.ok) {
      throw new Error(`Failed to insert data: ${response.status}`);
    }
    
    console.log(`Document indexed successfully`);
  } catch (error) {
    console.error(`Error indexing ${filePath}:`, error.message);
  }
}

// Find files matching patterns
async function findDocuments() {
  const documents = [];
  
  // Test with multiple overview documents
  const testFiles = [
    'github-mcp-model-assessment.md',
    'gpu-embedding-action-plan.md',
    'gpu-embedding-feasibility-assessment.md',
    'gpu-embedding-gap-analysis.md',
    'gpu-embedding-revised-plan.md',
    'gpu-sharing-data-collection.md',
    'wireguard-architecture.md'
  ];
  
  for (const file of testFiles) {
    const path = `/home/tony/CascadeProjects/chaba/docs/overview/${file}`;
    try {
      await stat(path); // Check if file exists
      documents.push({ path, type: 'docs', category: 'overview' });
    } catch (error) {
      console.log(`File not found: ${file}`);
    }
  }
  
  return documents;
}

// Main indexing process
async function main() {
  try {
    console.log('Starting SSOT document indexing...');
    
    await connectToWeaviate();
    await createCollection();
    
    // Find documents
    const documents = await findDocuments();
    console.log(`Found ${documents.length} documents to index`);
    
    // Index all found documents
    console.log(`Indexing ${documents.length} documents`);
    for (const doc of documents) {
      await indexDocument(doc.path, doc.type, doc.category);
    }
    
    console.log('Indexing complete!');
    
    // Show collection stats
    const response = await fetch(`${WEAVIATE_URL}/v1/schema/SSOTDocument`);
    const classInfo = await response.json();
    console.log('Collection created:', classInfo);
    
  } catch (error) {
    console.error('Indexing failed:', error);
    process.exit(1);
  }
}

main();
