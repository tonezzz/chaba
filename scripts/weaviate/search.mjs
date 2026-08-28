#!/usr/bin/env node

/**
 * Semantic Search for SSOT Documents
 * 
 * Search indexed SSOT documents using Weaviate REST API
 */

const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8082';

// Simple hash-based embedding (same as index-ssot.mjs)
async function generateEmbedding(text) {
  try {
    const simpleEmbedding = [];
    for (let i = 0; i < 384; i++) {
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

async function search(query, limit = 5) {
  try {
    console.log(`Searching for: "${query}"`);
    
    // Generate embedding for query
    const queryEmbedding = await generateEmbedding(query);
    
    // Search Weaviate using REST API
    const response = await fetch(`${WEAVIATE_URL}/v1/graphql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: `
          {
            Get {
              SSOTDocument(
                nearVector: {
                  vector: ${JSON.stringify(queryEmbedding)}
                }
                limit: ${limit}
              ) {
                title
                path
                type
                category
                tags
                language
                _additional {
                  distance
                }
              }
            }
          }
        `
      })
    });
    
    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Weaviate API error: ${error}`);
    }
    
    const data = await response.json();
    const results = data.data?.Get?.SSOTDocument || [];
    
    console.log(`\nFound ${results.length} results:\n`);
    
    for (const result of results) {
      const distance = result._additional?.distance || 0;
      const similarity = (1 - distance).toFixed(3);
      
      console.log(`[${similarity}] ${result.title}`);
      console.log(`  Type: ${result.type} | Category: ${result.category} | Language: ${result.language}`);
      console.log(`  Path: ${result.path}`);
      console.log(`  Tags: ${result.tags?.join(', ') || 'none'}`);
      console.log();
    }
    
  } catch (error) {
    console.error('Search failed:', error);
    throw error;
  }
}

// CLI interface
const query = process.argv[2];
const limit = parseInt(process.argv[3]) || 5;

if (!query) {
  console.log('Usage: node search.mjs "<query>" [limit]');
  console.log('Example: node search.mjs "GPU queue" 10');
  process.exit(1);
}

await search(query, limit);
