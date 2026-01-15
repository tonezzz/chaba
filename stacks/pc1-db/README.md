# PC1 DB Stack

Dedicated stack for data storage, databases, and document processing services.

## Services

- **qdrant** - Vector database for embeddings and similarity search
  - Port: 6333
  - Purpose: Vector storage for RAG and image embeddings

- **mcp-rag** - RAG search and embeddings service
  - Port: 8055
  - Purpose: Text/image search with vector embeddings

- **mcp-doc-archiver** - Document processing and archiving
  - Port: 8066
  - Purpose: Document ingestion, extraction, and indexing

- **authentik-postgres** - Authentication database
  - Purpose: User authentication and authorization data

- **authentik-redis** - Authentication cache
  - Purpose: Session caching and temporary storage

- **minio** - Object storage
  - Ports: 9000 (API), 9001 (Console)
  - Purpose: File storage and document archives

- **vault** - Secrets management
  - Port: 8200
  - Purpose: Secure credential and secret storage

## Usage

```bash
# Start DB stack
docker-compose --file docker-compose.yml up -d

# Check service health
curl http://localhost:6333/health  # Qdrant
curl http://localhost:8055/health  # RAG
curl http://localhost:8066/health  # Doc Archiver

# Test vector search
curl -X POST http://localhost:8055/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"search_text","arguments":{"query":"test","limit":5}}'

# Access MinIO console
open http://localhost:9001
# Username: minioadmin / Password: minioadmin123
```

## Cross-Host Access

The DB services are designed to be accessible from other hosts:

### From pc2-worker or other hosts
```json
// 1mcp.json configuration
{
  "mcpServers": {
    "pc1-qdrant": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:6333/mcp",
      "tags": ["pc1", "qdrant", "vector", "remote"],
      "enabled": true
    },
    "pc1-mcp-rag": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8055/mcp",
      "tags": ["pc1", "rag", "embeddings", "remote"],
      "enabled": true
    },
    "pc1-mcp-doc-archiver": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8066/mcp",
      "tags": ["pc1", "doc-archiver", "remote"],
      "enabled": true
    }
  }
}
```

### Environment Setup
```bash
# Copy environment file
cp .env.example .env

# Adjust configuration as needed
# QDRANT_TEXT_COLLECTION=rag_text
# OLLAMA_URL=http://pc1.vpn:11435
# MINIO_ROOT_USER=minioadmin
```

## Network

- **Network**: `pc1-db-net` (172.23.0.0/16)
- **VPN Access**: Available via `pc1.vpn` endpoints
- **Service Dependencies**: RAG depends on Qdrant

## Features

### Vector Database (Qdrant)
- **Collections**: Text and image embeddings
- **Search**: Semantic similarity and hybrid search
- **Performance**: Optimized for RAG workloads
- **Persistence**: Durable vector storage

### RAG Service
- **Text Search**: Semantic document search
- **Image Search**: CLIP-based visual similarity
- **Embeddings**: Ollama text + CLIP image models
- **Integration**: Works with document archiver

### Document Archiver
- **Ingestion**: Multiple document formats
- **Extraction**: Structured data extraction
- **Indexing**: Automatic RAG integration
- **Storage**: MinIO object storage integration

### Storage Services
- **MinIO**: S3-compatible object storage
- **Vault**: Secure secrets management
- **PostgreSQL**: Relational database for auth
- **Redis**: High-performance caching

## Requirements

- Docker with sufficient storage
- Network access to Ollama (pc1.vpn:11435)
- Memory for vector operations
- Disk space for document storage

## Data Persistence

- **qdrant-data**: Vector embeddings and collections
- **mcp-doc-archiver-data**: Document processing cache
- **authentik-postgres**: Authentication data
- **minio-data**: Object storage files
- **vault-dev**: Encrypted secrets storage

## Security Considerations

- **MinIO**: Change default credentials in production
- **Vault**: Use proper sealing/unsealing procedures
- **PostgreSQL**: Strong password required
- **Network**: Consider VPN-only access for sensitive data

## Integration

This stack integrates with:
- **pc1-stack** - Core services and APIs
- **pc1-ai** - AI/ML model services
- **pc1-devops** - Development workflows
- **pc2-worker** - Remote data access
