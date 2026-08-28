---
category: operations
---

# MDDB Ollama Embedding Setup

**Abstract**: Ollama container deployment and configuration for MDDB semantic search with GPU-accelerated embeddings using nomic-embed-text model.

## Overview

Ollama has been successfully deployed as the embedding provider for MDDB, enabling semantic search capabilities with GPU-accelerated text embeddings. The setup uses the nomic-embed-text model (768 dimensions) and integrates seamlessly with MDDB's vector search functionality.

## Related Documentation

- **MDDB Implementation**: `docs/kb/mddb-implementation-complete.md`
- **Migration Strategy**: `docs/kb/mddb-migration-strategy.md`
- **Deployment Config**: `stacks/web/mddb/docker-compose.yml`
- **Yomi Integration**: `scripts/yomi/yomi-api.mjs`

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-12 | Initial Ollama embedding setup documentation | devin |

## Tags

- ollama
- embeddings
- mddb
- gpu
- semantic-search
- nomic-embed-text
- vector-search

## See also

- [Mddb Ollama Embedding Setup Details](mddb-ollama-embedding-setup-details.md)
- [Mddb Ollama Embedding Setup Gemini](mddb-ollama-embedding-setup-gemini.md)
- [Mddb Ollama Embedding Setup Maintenance](mddb-ollama-embedding-setup-maintenance.md)
- [Mddb Ollama Embedding Setup Testing](mddb-ollama-embedding-setup-testing.md)
