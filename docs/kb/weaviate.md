---
category: operations
---

# Weaviate Vector Database

## What it is

Weaviate is a vector database for semantic search and RAG (Retrieval-Augmented Generation) pipelines. It provides AI-native vector storage with hybrid search capabilities (BM25 + vector search), built-in vectorization, and multi-tenancy support.

**Note**: Archived REST API implementation details have been consolidated into this operational guide. The REST API approach resolved gRPC client compatibility issues and provides simpler HTTP-based interaction.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


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
| `scripts/weaviate/index-ssot.mjs` | SSOT document indexing with Chonkie chunking and GPU embeddings |
| `scripts/weaviate/index-simple.mjs` | Simple document indexing |
| `scripts/weaviate/api.mjs` | Search API server |
| `scripts/weaviate/schema.json` | Weaviate collection schema |
| `scripts/chunk-text.py` | Chonkie text chunking integration (sentence-aware) |
| `docs/ssot/ssot.test.weaviate.yml` | Weaviate configuration and status |
| `docs/assessments/weaviate-assessment.md` | Weaviate vs pgvector analysis |

## Current Status

### Test Status
- **Weaviate Container**: Running ✅
- **Embedding Service**: Running ✅ (GPU, 32ms per embedding)
- **Weaviate Search API**: Running ✅
- **Indexing**: Working ✅
- **Search UI**: Deployed ✅
- **Search Functionality**: Working ✅ (with GPU embeddings)
- **Data Collection**: Completed ✅

### Known Issues
- **Weaviate Client Library**: gRPC connection parameter compatibility issue
  - Error: "Cannot destructure property 'host' of params.connectionParams.grpc as it is undefined"
  - Location: `scripts/weaviate/index-ssot.mjs`
  - Status: ✅ Resolved - Using REST API approach
  - Potential fixes:
    - Use Weaviate REST API instead of client library
    - Upgrade Weaviate client library to compatible version
    - Add gRPC configuration parameters

- **Chonkie Chunking**: ✅ Resolved - Fully integrated with sentence-aware chunking
- **GPU Queue Integration**: ✅ Complete and operational with validated batch embedding performance

## Use Cases

### High-Value Opportunities
1. **Semantic Conversation Search (Yomi)**: Search LINE conversations by meaning
2. **RAG for Daily Summaries**: Context-aware summarization with historical context
3. **SSOT and KB Memory Search**: Semantic search across all SSOT documents
4. **Image Similarity Search**: Find similar generated images across history

### Medium-Value Opportunities
1. **Code Semantic Search**: Search code by functionality
2. **Session Archive Intelligence**: Automatic clustering of related sessions

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

## See also

- [Weaviate Collections](weaviate-collections.md)
- [Weaviate Operations](weaviate-operations.md)
