# Weaviate REST API Implementation

## What it is

Complete implementation of Weaviate vector database using REST API instead of gRPC client library, with hash-based embeddings for testing purposes.

## Context

Weaviate TypeScript client v3 gRPC connection parameter compatibility issues led to switching to REST API approach. Disk quota constraints prevented installation of heavy ML dependencies (sentence-transformers), requiring temporary hash-based embedding solution.

## Implementation Details

### REST API Connection

**Problem**: gRPC client library compatibility issue
```javascript
// Failed approach (gRPC)
const client = weaviate.client({
  connectionParams: {
    http: { host: 'localhost', port: 8082, secure: false },
    grpc: { address: 'localhost:8082', secure: false }
  }
});
// Error: Cannot destructure property 'host' of params.connectionParams.grpc as it is undefined
```

**Solution**: REST API approach
```javascript
const client = await weaviate.connectToCustom({
  httpHost: 'localhost',
  httpPort: 8082,
  httpSecure: false,
  grpcHost: 'localhost',
  grpcPort: 8300, // Internal gRPC port from docker logs
  grpcSecure: false,
  skipInitChecks: true // Skip gRPC health check
});
```

### Collection Creation via REST

```javascript
async function createCollection() {
  const schema = JSON.parse(await readFile('schema.json', 'utf-8'));
  
  // Delete existing collection
  await fetch(`${WEAVIATE_API}/schema/${schema.class}`, { method: 'DELETE' });
  
  // Create new collection
  const response = await fetch(`${WEAVIATE_API}/schema`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ class: schema.class, ...schema })
  });
}
```

### Data Insertion via REST

```javascript
const dataObj = {
  class: 'SSOTDocument',
  properties: {
    title: title,
    content: chunkContent,
    path: filePath,
    type,
    category,
    tags,
    language,
    lastModified: stats.mtime.toISOString(),
    size: stats.size,
    chunkIndex: null,
    totalChunks: null,
  },
  vector: embedding,
};

const response = await fetch(`${WEAVIATE_API}/objects`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(dataObj)
});
```

### Search via GraphQL

```javascript
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
            _additional {
              distance
            }
          }
        }
      }
    `
  })
});
```

## Hash-Based Embeddings (Temporary)

### Problem

Disk quota exceeded when installing sentence-transformers (500MB+ PyTorch dependencies)

### Solution

Simple hash-based embeddings for testing (384 dimensions):
```javascript
async function generateEmbedding(text) {
  const simpleEmbedding = [];
  for (let i = 0; i < 384; i++) {
    const charCode = text.charCodeAt(i % text.length) || 0;
    const hash = (charCode * 31 + i) % 1000 / 1000;
    simpleEmbedding.push(hash);
  }
  return simpleEmbedding;
}
```

### Limitations

- Not semantically meaningful (just hash-based)
- Cannot be used for production semantic search
- Similarity scores are not reliable
- Only for testing Weaviate pipeline

## Schema Configuration

```json
{
  "class": "SSOTDocument",
  "description": "Single Source of Truth documents for chaba project",
  "vectorizer": "none",
  "properties": [
    { "name": "title", "dataType": ["text"] },
    { "name": "content", "dataType": ["text"] },
    { "name": "path", "dataType": ["text"] },
    { "name": "type", "dataType": ["text"] },
    { "name": "category", "dataType": ["text"] },
    { "name": "tags", "dataType": ["text[]"] },
    { "name": "language", "dataType": ["text"] },
    { "name": "lastModified", "dataType": ["date"] },
    { "name": "size", "dataType": ["int"] },
    { "name": "chunkIndex", "dataType": ["int"] },
    { "name": "totalChunks", "dataType": ["int"] }
  ],
  "vectorIndexType": "hnsw",
  "vectorIndexConfig": {
    "distance": "cosine",
    "m": 16,
    "efConstruction": 128
  }
}
```

## Test Results

### Successfully Indexed Documents

1. github-mcp-model-assessment.md (3,687 chars)
2. gpu-embedding-action-plan.md (15,663 chars)
3. gpu-embedding-feasibility-assessment.md (9,763 chars)
4. gpu-embedding-gap-analysis.md (10,333 chars)
5. gpu-embedding-revised-plan.md (11,408 chars)
6. gpu-sharing-data-collection.md (9,152 chars)
7. wireguard-architecture.md (9,677 chars)

### Search Results

**Query: "GPU embedding"**
- gpu-embedding-revised-plan.md (0.838)
- gpu-embedding-action-plan.md (0.836)
- gpu-sharing-data-collection.md (0.830)
- gpu-embedding-gap-analysis.md (0.820)
- github-mcp-model-assessment.md (0.819)

**Query: "WireGuard"**
- gpu-sharing-data-collection.md (0.818)
- gpu-embedding-gap-analysis.md (0.817)
- gpu-embedding-revised-plan.md (0.808)
- wireguard-architecture.md (0.807)
- github-mcp-model-assessment.md (0.803)

## Related Files

| File | Purpose |
|------|---------|
| `scripts/weaviate/index-ssot.mjs` | Document indexing with REST API |
| `scripts/weaviate/search.mjs` | Semantic search with GraphQL |
| `scripts/weaviate/schema.json` | Weaviate collection schema |
| `scripts/weaviate/package.json` | Node.js dependencies |

## Production Requirements

### GPU-Accelerated Embeddings

Replace hash-based embeddings with proper sentence-transformers:
```javascript
// Production implementation
import { SentenceTransformer } from '@xenova/transformers';

const model = await SentenceTransformer.from_pretrained('all-MiniLM-L6-v2');
const embedding = await model.encode(text);
```

### Chonkie Text Chunking

Replace simple character-based chunking with Chonkie:
```javascript
import { SentenceChunker } from 'chonkie';

const chunker = new SentenceChunker(chunkSize=512, overlap=50);
const chunks = await chunker.chunk(text);
```

### Proper ML Dependencies

Install sentence-transformers with GPU support:
```bash
pip install sentence-transformers torch --index-url https://download.pytorch.org/whl/cu118
```

## Troubleshooting

### gRPC Connection Error

**Issue**: `TypeError: Cannot destructure property 'host' of params.connectionParams.grpc as it is undefined`
**Solution**: Use REST API instead of gRPC client methods

### Disk Quota Issue

**Issue**: Disk quota exceeded when installing sentence-transformers
**Solution**: Use hash-based embeddings for testing, plan GPU-accelerated solution for production

### Schema JSON Syntax Error

**Issue**: `SyntaxError: Expected ',' or '}' after property value in JSON`
**Solution**: Fix JSON syntax (missing commas, proper object structure)

## Advantages of REST API Approach

1. **Simpler Connection**: No gRPC complexity
2. **Better Compatibility**: Works with standard HTTP
3. **Easier Debugging**: Can test with curl/browser
4. **Language Agnostic**: Works with any HTTP client
5. **Firewall Friendly**: Standard HTTP ports

## Disadvantages

1. **Performance**: gRPC is theoretically faster
2. **Streaming**: No streaming support
3. **Type Safety**: Less type-safe than client library
4. **Features**: Some advanced features may not be available

## Tags

- **weaviate**: Vector database implementation
- **rest-api**: HTTP-based Weaviate interaction
- **embeddings**: Hash-based temporary solution
- **semantic-search**: Vector search functionality
- **testing**: Development and validation approach
- **gpu-acceleration**: Future production requirement
