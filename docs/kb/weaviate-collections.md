---
category: operations
---

# Collection Schema

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
- **Status**: ✅ Fully integrated and operational

### Installation
```bash
cd /home/tony/CascadeProjects/chaba
python3 -m venv venv-embeddings
source venv-embeddings/bin/activate
pip install "chonkie[sentence]"
```

**Note**: Chonkie is installed in the `venv-embeddings` virtual environment, which is also used for the GPU embedding service. This ensures consistent Python environment for both chunking and embedding operations.

### Usage
```bash
source venv-embeddings/bin/activate
python3 scripts/chunk-text.py "text to chunk"
```

### Integration Details
- **File**: `scripts/weaviate/index-ssot.mjs` updated to use Chonkie Python script
- **Fallback**: Simple character-based chunking as fallback if Chonkie fails
- **Execution**: Requires bash shell execution with proper virtual environment activation
- **Indexing Results**: Successfully indexed 24+ chunks using Chonkie chunking with GPU-accelerated embeddings
- **Search Quality**: Good semantic search quality with relevance scores on test queries for GPU queue, Chonkie chunking, and batch embedding topics

