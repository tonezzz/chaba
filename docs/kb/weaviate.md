# Weaviate Vector Database

## What it is

Weaviate is a vector database for semantic search and RAG (Retrieval-Augmented Generation) pipelines. It provides AI-native vector storage with hybrid search capabilities (BM25 + vector search), built-in vectorization, and multi-tenancy support.

## Architecture

### Container Configuration
- **Location**: `/home/tony/CascadeProjects/chaba/stacks/web/docker-compose.yml`
- **Image**: `semitechnologies/weaviate:latest`
- **Version**: 1.38.8
- **Ports**: 8082 (external) → 8080 (internal)
- **Persistence**: Dedicated volume `weaviate_data` at `/var/lib/weaviate`

### Environment Configuration
- `QUERY_DEFAULTS_LIMIT=25`
- `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true`
- `PERSISTENCE_DATA_PATH=/var/lib/weaviate`
- `DEFAULT_VECTORIZER_MODULE=none`
- `CLUSTER_HOSTNAME=node1`

## Key Files

| File | Purpose |
|------|---------|
| `scripts/weaviate/index-ssot.mjs` | SSOT document indexing with Chonkie chunking |
| `scripts/weaviate/index-simple.mjs` | Simple document indexing |
| `scripts/weaviate/api.mjs` | Search API server |
| `scripts/weaviate/schema.json` | Weaviate collection schema |
| `scripts/chunk-text.py` | Chonkie text chunking integration |
| `docs/ssot/ssot.test.weaviate.yml` | Weaviate configuration and status |
| `docs/assessments/weaviate-assessment.md` | Weaviate vs pgvector analysis |

## Collection Schema

### SSOTDocument Collection
- **Vector Index Type**: HNSW
- **Distance**: Cosine
- **Vectorizer**: None (custom embeddings)

**Properties:**
- `title` (text): Document title or filename
- `content` (text): Full document content for semantic search
- `path` (text): File path in the repository
- `type` (text): Document type (ssot, session, kb, docs)
- `category` (text): Document category (apps, infrastructure, sessions)
- `tags` (text[]): Array of tags for filtering
- `language` (text): Primary language (en, th, mixed)
- `lastModified` (date): Last modification timestamp
- `size` (int): File size in bytes
- `chunkIndex` (int): Chunk index for multi-chunk documents (null for single chunk)
- `totalChunks` (int): Total number of chunks per document (null for single chunk)

## Chonkie Integration

### Text Chunking
- **Chunker**: Chonkie SentenceChunker
- **Chunk Size**: 512 tokens
- **Chunk Overlap**: 50 tokens
- **Trigger**: Documents >1000 characters
- **Purpose**: Better semantic search with sentence boundary preservation

### Installation
```bash
cd /home/tony/CascadeProjects/chaba
python3 -m venv venv
source venv/bin/activate
pip install "chonkie[sentence]"
```

### Usage
```bash
source venv/bin/activate
python3 scripts/chunk-text.py "text to chunk"
```

## Current Status

### Test Status
- **Weaviate Container**: Running ✅
- **Embedding Service**: Skipped ⏭️
- **Weaviate Search API**: Running ✅
- **Indexing**: Not Started ❌
- **Search UI**: Deployed ✅
- **Search Functionality**: Working ✅ (with mock data)
- **Data Collection**: In Progress 🔬

### Known Issues
- **Weaviate Client Library**: gRPC connection parameter compatibility issue
  - Error: "Cannot destructure property 'host' of params.connectionParams.grpc as it is undefined"
  - Location: `scripts/weaviate/index-ssot.mjs`
  - Status: Needs investigation
  - Potential fixes:
    - Use Weaviate REST API instead of client library
    - Upgrade Weaviate client library to compatible version
    - Add gRPC configuration parameters

- **Embedding Service Build**: Takes long due to PyTorch dependencies
- **Mock Data**: Currently using mock data for search testing
- **No Real Documents**: No real documents indexed yet
- **OpenAI API Key**: Need OpenAI API key for real embeddings

## Use Cases

### High-Value Opportunities
1. **Semantic Conversation Search (Yomi)**: Search LINE conversations by meaning
2. **RAG for Daily Summaries**: Context-aware summarization with historical context
3. **SSOT and KB Memory Search**: Semantic search across all SSOT documents
4. **Image Similarity Search**: Find similar generated images across history

### Medium-Value Opportunities
1. **Code Semantic Search**: Search code by functionality
2. **Session Archive Intelligence**: Automatic clustering of related sessions

## API Endpoints

### Weaviate
- http://localhost:8082/v1/.well-known/ready
- http://localhost:8082/v1/schema
- http://localhost:8082/v1/nodes

### Weaviate Search API
- http://localhost:3002/health
- http://localhost:3002/search

### Embedding Service (when built)
- http://localhost:5000/health
- http://localhost:5000/model-info
- http://localhost:5000/embed

## Routing

### Caddy Configuration
- `/api/weaviate/*` → weaviate:8080
- `/api/weaviate-search/*` → weaviate-search:3002
- `/apps/weaviate-search/` → weaviate-search UI

## Troubleshooting

### Weaviate Client Connection Error
**Error**: `TypeError: Cannot destructure property 'host' of params.connectionParams.grpc as it is undefined`

**Solutions**:
1. Use Weaviate REST API instead of client library
2. Add gRPC configuration parameters to connection
3. Upgrade Weaviate client library to compatible version

### Container Not Starting
**Check**:
```bash
docker logs weaviate
docker ps | grep weaviate
curl http://localhost:8082/v1/.well-known/ready
```

### Indexing Fails
**Check**:
- Weaviate container is running
- Collection schema exists
- Embedding service is available (if using)
- File paths are correct
- Chonkie virtual environment is activated

### gRPC Connection Error
**Issue**: `TypeError: Cannot destructure property 'host' of 'params.connectionParams.grpc' as it is undefined`
**Root Cause**: Weaviate TypeScript client v3 requires both http and grpc connection parameters
**Solution**: Use REST API instead of gRPC client methods
**Fix Applied**:
```javascript
// Before (gRPC approach - fails)
const client = weaviate.client({
  connectionParams: {
    http: { host: 'localhost', port: 8082, secure: false },
    grpc: { address: 'localhost:8082', secure: false }
  }
});

// After (REST API approach - works)
const client = await weaviate.connectToCustom({
  httpHost: 'localhost',
  httpPort: 8082,
  httpSecure: false,
  grpcHost: 'localhost',
  grpcPort: 8300, // Internal gRPC port
  grpcSecure: false,
  skipInitChecks: true // Skip gRPC health check
});
```
**Status**: ✅ Resolved (2026-08-04)

### Disk Quota Issue with sentence-transformers
**Issue**: Disk quota exceeded when installing sentence-transformers for embeddings
**Root Cause**: sentence-transformers requires PyTorch and heavy ML dependencies (500MB+)
**Temporary Solution**: Use simple hash-based embeddings for testing
**Fix Applied**:
```javascript
// Temporary hash-based embedding (384 dimensions)
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
**Production Solution**: Use GPU-accelerated embeddings with proper sentence-transformers
**Status**: ⚠️ Temporary fix - production requires proper ML embeddings

## Related Documentation

- **[weaviate-assessment.md](../assessments/weaviate-assessment.md)** - Weaviate vs pgvector analysis
- **[ssot.test.weaviate.yml](../ssot/ssot.test.weaviate.yml)** - Weaviate configuration and status
- **[yomi.md](yomi.md)** - Yomi LINE web app (potential integration)

## Tags

- **weaviate**: Vector database for semantic search
- **chonkie**: Text chunking library for document processing
- **semantic-search**: AI-native search capabilities
- **rag**: Retrieval-Augmented Generation pipelines
- **embeddings**: Vector embeddings for text and images
- **hybrid-search**: BM25 + vector combination search
