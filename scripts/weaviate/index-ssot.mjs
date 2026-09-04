#!/usr/bin/env node

/**
 * SSOT Document Indexer for Weaviate
 * 
 * Indexes SSOT YAML files, session archives, and documentation into Weaviate
 * for semantic search using all-MiniLM-L6-v2 model via GPU embedding service
 */

import { readFile, readdir, stat, writeFile, unlink } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { exec } from 'child_process';
import { promisify } from 'util';
import { mkdtemp, rmdir } from 'fs/promises';
import { tmpdir } from 'os';

const execAsync = promisify(exec);
const __dirname = dirname(fileURLToPath(import.meta.url));

// Configuration
const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const EMBEDDING_DIM = 384; // all-MiniLM-L6-v2 (GPU-accelerated via embedding service)
const CHABA_ROOT = '/home/tony/CascadeProjects/chaba-tony-dell';

// Document patterns to index
const DOCUMENT_PATTERNS = [
  { pattern: 'docs/ssot/*.yml', type: 'ssot', category: 'ssot' },
  { pattern: 'docs/ssot/infrastructure/*.yml', type: 'ssot', category: 'infrastructure' },
  { pattern: 'docs/ssot/apps/*.yml', type: 'ssot', category: 'apps' },
  { pattern: 'docs/overview/*.yml', type: 'docs', category: 'overview' },
  { pattern: 'docs/sessions/*.yml', type: 'session', category: 'sessions' },
  { pattern: 'docs/kb/*.md', type: 'kb', category: 'kb' },
  { pattern: 'docs/assessments/*.md', type: 'assessment', category: 'assessments' },
  { pattern: 'docs/assessments/gpu-embedding/*.md', type: 'assessment', category: 'gpu-embedding' },
  { pattern: 'docs/architecture/*.md', type: 'architecture', category: 'architecture' },
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

// Generate embedding using GPU service
async function generateEmbedding(text) {
  try {
    const response = await fetch('http://localhost:5000/embed-single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, use_gpu: true }),
    });

    if (!response.ok) {
      throw new Error(`Embedding service error: ${response.statusText}`);
    }

    const data = await response.json();
    return data.embedding;
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

// Chunk text using Chonkie Python script
async function chunkText(content, chunkSize = 512, chunkOverlap = 50) {
  try {
    // Create temporary file to avoid shell escaping issues
    const tempDir = await mkdtemp(join(tmpdir(), 'chunk-'));
    const tempFile = join(tempDir, 'input.txt');
    await writeFile(tempFile, content, 'utf-8');
    
    const { stdout } = await execAsync(
      `/home/tony/venv-embeddings/bin/python /home/tony/CascadeProjects/chaba-tony-dell/scripts/chunk-text.py "${tempFile}" ${chunkSize} ${chunkOverlap}`,
      { timeout: 30000 }
    );
    
    // Clean up temp file
    await unlink(tempFile);
    await rmdir(tempDir);
    
    const result = JSON.parse(stdout);
    return result.chunks;
  } catch (error) {
    console.error('Error chunking text, falling back to simple chunking:', error.message);
    // Fallback to simple character-based chunking
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
    
    // Use Chonkie chunking for better semantic search
    const chunks = await chunkText(content, 512, 50);
    console.log(`Document chunked into ${chunks.length} parts`);
    
    // Index each chunk
    for (let i = 0; i < chunks.length; i++) {
      const chunkContent = chunks[i];
      const embedding = await generateEmbedding(chunkContent);
      
      console.log(`Embedding generated for chunk ${i + 1}/${chunks.length}: ${embedding.length} dimensions`);
      
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
          chunkIndex: i,
          totalChunks: chunks.length,
        },
        vector: embedding,
      };
      
      console.log(`Sending chunk ${i + 1}/${chunks.length} to Weaviate...`);
      const response = await fetch(`${WEAVIATE_API}/objects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataObj)
      });
      
      if (!response.ok) {
        throw new Error(`Failed to insert chunk ${i + 1}: ${response.status}`);
      }
    }
    
    console.log(`Document indexed successfully (${chunks.length} chunks)`);
  } catch (error) {
    console.error(`Error indexing ${filePath}:`, error.message);
  }
}

// Find files matching patterns
async function findDocuments() {
  const documents = [];
  
  for (const { pattern, type, category } of DOCUMENT_PATTERNS) {
    try {
      const { stdout } = await execAsync(`find ${CHABA_ROOT}/${pattern} -type f 2>/dev/null`);
      const files = stdout.trim().split('\n').filter(Boolean);
      
      for (const file of files) {
        documents.push({ path: file, type, category });
      }
    } catch (error) {
      console.warn(`No files found for pattern: ${pattern}`);
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
    
    // Index all found documents in batches to manage memory
    console.log(`Indexing ${documents.length} documents in batches`);
    const BATCH_SIZE = 10; // Process in batches to manage memory
    
    for (let i = 0; i < documents.length; i += BATCH_SIZE) {
      const batch = documents.slice(i, i + BATCH_SIZE);
      console.log(`\nProcessing batch ${Math.floor(i / BATCH_SIZE) + 1}/${Math.ceil(documents.length / BATCH_SIZE)} (${batch.length} documents)`);
      
      for (const doc of batch) {
        await indexDocument(doc.path, doc.type, doc.category);
      }
      
      // Force garbage collection between batches
      if (global.gc) {
        console.log('Running garbage collection...');
        global.gc();
      }
      
      console.log(`Batch completed. ${i + batch.length}/${documents.length} documents processed.`);
    }
    
    console.log('\nIndexing complete!');
    
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
