#!/usr/bin/env node

/**
 * SSOT Document Indexer for Weaviate
 * 
 * Indexes SSOT YAML files, session archives, and documentation into Weaviate
 * for semantic search using SEA-LION-E5-Embedding-600M model
 */

import weaviate from 'weaviate-client';
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
  { pattern: 'docs/overview/ssot*.yml', type: 'ssot', category: 'overview' },
  { pattern: 'docs/overview/sessions/**/*.yml', type: 'session', category: 'sessions' },
  { pattern: 'docs/**/*.md', type: 'docs', category: 'documentation' },
  { pattern: '.sessions/**/*.yml', type: 'session', category: 'sessions' },
  { pattern: 'scripts/**/*.md', type: 'docs', category: 'scripts' },
];

// Connect to Weaviate
const client = weaviate.client({
  connectionParams: {
    http: {
      host: WEAVIATE_URL.replace('http://', '').replace('https://', '').split(':')[0],
      port: parseInt(WEAVIATE_URL.split(':')[2]) || 8080,
      secure: false
    }
  }
});

console.log('Connected to Weaviate at', WEAVIATE_URL);

// Create collection if it doesn't exist
async function createCollection() {
  try {
    const schema = JSON.parse(
      await readFile(join(__dirname, 'schema.json'), 'utf-8')
    );
    
    try {
      await client.schema.classDeleter().withClassName(schema.class).do();
      console.log(`Deleted existing collection: ${schema.class}`);
    } catch (e) {
      // Collection doesn't exist, that's fine
    }
    
    await client.schema.classCreator().withClass(schema).do();
    
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

model = SentenceTransformer('${MODEL_NAME}')
text = sys.argv[1]
embedding = model.encode(text, convert_to_numpy=False)
print(','.join(map(str, embedding)))
`;
    
    const { stdout } = await execAsync(`python3 -c "${script.replace(/"/g, '\\"')}" "${text.replace(/"/g, '\\"')}"`);
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

// Index a single document
async function indexDocument(filePath, type, category) {
  try {
    const content = await readFile(filePath, 'utf-8');
    const stats = await stat(filePath);
    const title = filePath.split('/').pop();
    
    const embedding = await generateEmbedding(content);
    const language = detectLanguage(content);
    const tags = extractTags(content, type);
    
    const dataObj = {
      class: 'SSOTDocument',
      properties: {
        title,
        content,
        path: filePath,
        type,
        category,
        tags,
        language,
        lastModified: stats.mtime.toISOString(),
        size: stats.size,
      },
      vector: embedding,
    };
    
    await client.data.creator().withObject(dataObj).do();
    
    console.log(`Indexed: ${filePath} (${language}, ${content.length} chars)`);
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
    
    // Create collection
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
    const classInfo = await client.schema.classGetter().withClassName('SSOTDocument').do();
    console.log('Collection created:', classInfo);
    
  } catch (error) {
    console.error('Indexing failed:', error);
    process.exit(1);
  }
}

main();
