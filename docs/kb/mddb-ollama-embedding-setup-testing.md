---
category: operations
---

# Testing and Verification

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

