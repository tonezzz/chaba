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
const EMBEDDING_DIM = 1536; // OpenAI text-embedding-3-small
const CHABA_ROOT = '/home/tony/CascadeProjects/chaba';

// Document patterns to index
const DOCUMENT_PATTERNS = [
  { pattern: 'docs/ssot/**/*.yml', type: 'ssot', category: 'ssot' },
  { pattern: 'docs/sessions/**/*.yml', type: 'session', category: 'sessions' },
  { pattern: 'docs/kb/*.md', type: 'kb', category: 'kb' },
  { pattern: 'docs/assessments/**/*.md', type: 'assessment', category: 'assessments' },
  { pattern: 'docs/architecture/*.md', type: 'architecture', category: 'architecture' },
  { pattern: 'docs/overview/*.md', type: 'docs', category: 'overview' },
  { pattern: '.sessions/**/*.yml', type: 'session', category: 'sessions' },
  { pattern: 'scripts/**/*.md', type: 'docs', category: 'scripts' },
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
    // Use Python script with sentence-transformers
    const script = `
import sys
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
text = sys.argv[1]
embedding = model.encode(text, convert_to_numpy=False)
print(','.join(map(str, embedding)))
`;
    
    const { stdout } = await execAsync(`/home/tony/CascadeProjects/chaba/venv/bin/python3 -c "${script.replace(/"/g, '\\"')}" "${text.replace(/"/g, '\\"')}"`);
    const embedding = stdout.trim().split(',').map(Number);
    return embedding;
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
    const { stdout } = await execAsync(
      `/home/tony/CascadeProjects/chaba/venv/bin/python3 /home/tony/CascadeProjects/chaba/scripts/chunk-text.py "${content.replace(/"/g, '\\"')}" ${chunkSize} ${chunkOverlap}`
    );
    const result = JSON.parse(stdout);
    return result.chunks || [content]; // Return chunks or original if chunking fails
  } catch (error) {
    console.warn('Chunking failed, using original content:', error.message);
    return [content]; // Fallback to original content
  }
}

// Index a single document
async function indexDocument(filePath, type, category) {
  try {
    const content = await readFile(filePath, 'utf-8');
    const stats = await stat(filePath);
    const title = filePath.split('/').pop();
    
    // Chunk the document if it's large (>1000 chars)
    const chunks = content.length > 1000 
      ? await chunkText(content, 512, 50)
      : [content];
    
    const language = detectLanguage(content);
    const tags = extractTags(content, type);
    
    // Index each chunk separately
    for (let i = 0; i < chunks.length; i++) {
      const chunkContent = chunks[i];
      const embedding = await generateEmbedding(chunkContent);
      
      const dataObj = {
        class: 'SSOTDocument',
        properties: {
          title: chunks.length > 1 ? `${title} (chunk ${i + 1}/${chunks.length})` : title,
          content: chunkContent,
          path: filePath,
          type,
          category,
          tags,
          language,
          lastModified: stats.mtime.toISOString(),
          size: stats.size,
          chunkIndex: chunks.length > 1 ? i : null,
          totalChunks: chunks.length > 1 ? chunks.length : null,
        },
        vector: embedding,
      };
      
      const response = await fetch(`${WEAVIATE_API}/objects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataObj)
      });
      
      if (!response.ok) {
        throw new Error(`Failed to insert data: ${response.status}`);
      }
    }
    
    console.log(`Indexed: ${filePath} (${language}, ${content.length} chars, ${chunks.length} chunk${chunks.length > 1 ? 's' : ''})`);
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
    
    // Index documents
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
