#!/usr/bin/env node

/**
 * Simple SSOT Document Indexer for Weaviate
 * 
 * Indexes SSOT YAML files using REST API and local embedding service
 */

import { readFile, stat } from 'fs/promises';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// Configuration
const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';
const CHABA_ROOT = '/home/tony/CascadeProjects/chaba-tony-dell';

// Document patterns to index
const DOCUMENT_PATTERNS = [
  { pattern: 'docs/ssot/**/*.yml', type: 'ssot', category: 'ssot' },
  { pattern: 'docs/overview/*.md', type: 'docs', category: 'overview' },
  { pattern: 'docs/sessions/*.yml', type: 'session', category: 'sessions' },
  { pattern: 'docs/kb/*.md', type: 'kb', category: 'kb' },
  { pattern: 'docs/assessments/**/*.md', type: 'assessment', category: 'assessments' },
  { pattern: 'docs/architecture/*.md', type: 'architecture', category: 'architecture' },
];

// Generate embedding using local service
async function generateEmbedding(text) {
  try {
    const response = await fetch('http://localhost:5001/embed-single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
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

// Extract tags from content
function extractTags(content, type) {
  const tags = [type];
  
  const keywords = content.match(/\b(apps|infrastructure|gpu|docker|api|database|weaviate|postgres|redis|yomi|track4|imagen|video|embedding|queue)\b/gi);
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
    
    const response = await fetch(`${WEAVIATE_URL}/v1/objects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dataObj),
    });

    if (!response.ok) {
      throw new Error(`Weaviate API error: ${await response.text()}`);
    }
    
    console.log(`Indexed: ${title} (${language}, ${content.length} chars)`);
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
    
    // Find documents
    const documents = await findDocuments();
    console.log(`Found ${documents.length} documents to index`);
    
    // Index documents
    for (const doc of documents) {
      await indexDocument(doc.path, doc.type, doc.category);
    }
    
    console.log('Indexing complete!');
    
    // Show collection stats
    const response = await fetch(`${WEAVIATE_URL}/v1/objects?class=SSOTDocument&limit=1`);
    const data = await response.json();
    console.log(`Total indexed: ${data.totalResults || 0}`);
    
  } catch (error) {
    console.error('Indexing failed:', error);
    process.exit(1);
  }
}

main();