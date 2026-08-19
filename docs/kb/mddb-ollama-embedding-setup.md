# MDDB Ollama Embedding Setup

**Abstract**: Ollama container deployment and configuration for MDDB semantic search with GPU-accelerated embeddings using nomic-embed-text model.

## Overview

Ollama has been successfully deployed as the embedding provider for MDDB, enabling semantic search capabilities with GPU-accelerated text embeddings. The setup uses the nomic-embed-text model (768 dimensions) and integrates seamlessly with MDDB's vector search functionality.

## Implementation Details

### Container Configuration
- **Image**: ollama/ollama:latest
- **Container Name**: ollama
- **GPU Support**: NVIDIA GeForce GTX 1650 (4096MB total)
- **Network**: web_default (Docker network)
- **Restart Policy**: unless-stopped

### Docker Compose Configuration
```yaml
ollama:
  image: ollama/ollama:latest
  container_name: ollama
  restart: unless-stopped
  ports:
    - "11434:11434"
  volumes:
    - ollama-data:/root/.ollama
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  networks:
    - default
```

### MDDB Environment Configuration
```yaml
environment:
  - MDDB_EMBEDDING_PROVIDER=ollama
  - MDDB_EMBEDDING_API_URL=http://ollama:11434
  - MDDB_EMBEDDING_MODEL=nomic-embed-text
  - MDDB_EMBEDDING_DIMENSIONS=768
```

## Model Information

### nomic-embed-text
- **Model Size**: 274 MB
- **Dimensions**: 768
- **Context Length**: 2048 tokens
- **Family**: nomic-bert
- **Parameter Size**: 137M
- **Quantization**: F16
- **Capabilities**: Embedding generation

### Model Download
```bash
docker exec ollama ollama pull nomic-embed-text
```

## GPU Resource Usage

### Current Allocation
- **Total GPU Memory**: 4096 MB (NVIDIA GeForce GTX 1650)
- **Ollama Usage**: 388 MB (9.5%)
- **Free Memory**: 3213 MB (78.4%)
- **Process**: /usr/lib/ollama/llama-server (PID: 3505946)

### Resource Efficiency
- GPU resources efficiently managed for shared environment
- Sufficient free memory for other GPU services
- Stable performance with low memory footprint

## Integration with MDDB

### Vector Index Status
- **Total Embedded Documents**: 88
- **Total Chunks**: 551
- **Collections Embedded**: 4 (kb-system, kb-development, kb-features, kb-operations)
- **Algorithm**: Flat
- **Distance Metric**: Cosine
- **Quantization**: float32

### Collection Breakdown
- **kb-system**: 27 documents, 153 chunks
- **kb-development**: 15 documents, 90 chunks
- **kb-features**: 42 documents, 268 chunks
- **kb-operations**: 4 documents, 40 chunks

## Testing and Verification

### Embedding Generation Test
```bash
docker exec ollama ollama run nomic-embed-text "test"
```
**Result**: Successfully generates 768-dimensional vector

### API Connectivity Test
```bash
curl -s http://localhost:11434/api/tags
```
**Result**: Returns model information and capabilities

### MDDB Integration Test
```bash
curl -s http://tony-omen.local:11023/v1/vector-stats
```
**Result**: Returns embedding configuration and index status

## Performance Metrics

### Search Performance
- **Average Response Time**: 200-300ms
- **Fastest Query**: 88ms
- **Slowest Query**: 451ms
- **Relevance Scores**: 0.45-0.76 (high quality)

### Test Query Results
- "docker configuration management" → 5 results (scores: 0.55-0.64)
- "documentation standards" → 5 results (scores: 0.59-0.76)
- "carplay navigation" → 5 results (scores: 0.51-0.70)
- "monitoring health checks" → 4 results (scores: 0.45-0.58)

## Comparison with Yomi Embeddings

### Current Yomi Setup
- **Provider**: Gemini API (text-embedding-004)
- **Rate Limiting**: 1 concurrent, 1-minute queue timeout
- **API Key Required**: Yes
- **Cost**: Free tier limits apply
- **Location**: scripts/yomi/yomi-api.mjs

### Potential Shared Ollama
- **Provider**: Ollama (nomic-embed-text)
- **Rate Limiting**: None (local)
- **API Key Required**: No
- **Cost**: Free (local GPU)
- **Benefits**: Shared GPU resources, no API costs, consistent model

### Migration Consideration
- Yomi could migrate to shared Ollama service
- Would eliminate Gemini API dependency
- Consistent embedding model across systems
- Requires code changes in yomi-api.mjs

## Gemini Embedding Proxy (GPU Offload Alternative)

A Node.js proxy, `scripts/mddb/gemini-ollama-proxy.mjs`, exposes an Ollama-compatible `/api/embed` (and `/api/embeddings`) endpoint on `tony-omen:11435` and translates requests to Google's Gemini `batchEmbedContents` API. This lets MDDB keep using the `ollama` embedding provider while the actual embedding generation runs in Gemini, freeing `tony-omen`'s GPU.

### Proxy Configuration

- **Source**: `scripts/mddb/gemini-ollama-proxy.mjs`
- **Host/Port**: `tony-omen:11435` (also accessible from `tony-dell` at `100.75.102.88:11435`)
- **Gemini Model**: `gemini-embedding-001` (768 dimensions)
- **Model Alias**: `nomic-embed-text` is mapped to `gemini-embedding-001`
- **Rate Limits**: 100 RPM, 30000 TPM, 1000 RPD by default; proxy batches and retries with exponential backoff.
- **Environment**: `GEMINI_API_KEY` and optionally `GEMINI_PROXY_PORT`, `GEMINI_EMBEDDING_MODEL`, `GEMINI_EMBEDDING_DIMENSIONS`.

### MDDB Configuration for Gemini Proxy

```yaml
environment:
  - MDDB_EMBEDDING_PROVIDER=ollama
  - MDDB_EMBEDDING_API_URL=http://gemini:11435
  - MDDB_EMBEDDING_MODEL=nomic-embed-text
  - MDDB_EMBEDDING_DIMENSIONS=768
```

The MDDB container needs a `--add-host gemini:100.75.102.88` or a Docker network alias `gemini` so `gemini:11435` resolves to `tony-omen`.

### Side-by-Side Validation (2026-08-18)

Test collections on `tony-dell`:

- **mddb-gemini-test** (`:12023`) — MDDB using Gemini proxy
- **mddb-ollama-test** (`:12024`) — MDDB using local Ollama

Both indexed the same 3 test documents.

| Query | Gemini top score | Gemini latency | Ollama top score | Ollama latency |
|---|---|---|---|---|
| `Gemini embedding API` | 0.8073 (gemini-embedding) | ~575 ms | 0.8248 (gemini-embedding) | ~5.9 s (cold) |
| `Ollama GPU memory` | 0.8453 (ollama-gpu) | ~524 ms | 0.8107 (ollama-gpu) | ~117 ms (warm) |
| `Tailscale networking` | 0.8234 (tailscale-networking) | ~481 ms | 0.7983 (tailscale-networking) | ~4.8 s (cold) |

**Findings**: Gemini relevance is comparable or slightly better. Gemini latency is ~500 ms per query, while Ollama is ~100 ms once warm but 1-6 s on cold starts.

### Decision

Switched the live MDDB on `tony-dell` to use the Gemini proxy. Ollama can be stopped on `tony-omen` once the live MDDB reindex is verified and no other Ollama consumers remain.

### Loading Test Documents via GraphQL

```bash
# Example payload for GraphQL addBatch
mutation($collection: String!, $documents: [AddBatchDocumentInput!]!) {
  addBatch(collection: $collection, documents: $documents) {
    added
    failed
    errors
  }
}
```

Documents: `{key, lang: "en", contentMd: "..."}`

### Verification Commands

```bash
# Health
curl -s http://tony-omen:11435/health

# Direct proxy test
curl -s -X POST http://100.75.102.88:11435/api/embed -H 'Content-Type: application/json' -d '{"model":"nomic-embed-text","input":"test"}'

# MDDB test stats
curl -s http://tony-dell:12023/v1/vector-stats
curl -s http://tony-dell:12024/v1/vector-stats
```

### Related Files

- `scripts/mddb/gemini-ollama-proxy.mjs` — Gemini/Ollama proxy
- `stacks/web/mddb/docker-compose.yml` — MDDB and proxy compose
- `docs/ssot/infrastructure/ssot.gemini-embedding.yml` — Gemini embedding SSOT

## Troubleshooting

### Ollama Container Issues
**Symptoms**: Container not starting, GPU not accessible
**Solutions**:
- Check GPU availability: `nvidia-smi`
- Verify Docker GPU support: `docker run --rm --gpus all nvidia/cuda:11.0.3-base-ubuntu20.04 nvidia-smi`
- Check container logs: `docker logs ollama`

### Model Download Issues
**Symptoms**: Model pull fails, slow download
**Solutions**:
- Check network connectivity
- Verify disk space availability
- Retry model pull: `docker exec ollama ollama pull nomic-embed-text`

### MDDB Integration Issues
**Symptoms**: Vector search not working, embedding errors
**Solutions**:
- Verify MDDB environment variables
- Check Ollama connectivity from MDDB container
- Test embedding generation directly
- Review MDDB logs for errors

### GPU Resource Issues
**Symptoms**: Out of memory errors, slow performance
**Solutions**:
- Monitor GPU usage: `nvidia-smi`
- Check for conflicting GPU processes
- Consider smaller model if needed
- Optimize batch sizes for embedding generation

## Maintenance

### Model Updates
```bash
# Update model
docker exec ollama ollama pull nomic-embed-text

# Check for newer versions
docker exec ollama ollama list
```

### Container Maintenance
```bash
# Restart container
docker restart ollama

# View logs
docker logs ollama --tail 50

# Check resource usage
docker stats ollama
```

### Index Maintenance
```bash
# Reindex specific collection
curl -X POST http://tony-omen.local:11023/v1/vector-reindex \
  -H "Content-Type: application/json" \
  -d '{"collection":"kb-system","force":true}'

# Check vector stats
curl http://tony-omen.local:11023/v1/vector-stats
```

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