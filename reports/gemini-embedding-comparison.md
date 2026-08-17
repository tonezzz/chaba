# Gemini vs Ollama Embedding Comparison

## Setup

- **Host**: tony-omen
- **Ollama endpoint**: http://localhost:11434/api/embed using `nomic-embed-text` (768-dim)
- **Gemini proxy endpoint**: http://localhost:11435/api/embed using `text-embedding-004` mapped to `gemini-embedding-001` with `outputDimensionality=768`
- **API key source**: `/etc/systemd/system/yomi-process.service.d/override.conf`
- **Samples**: 8 representative snippets from SSOT, GPU queue, Yomi, and Weaviate documentation

## Latency

| Provider | Avg per-embedding latency | Query latency |
|---|---|---|
| Ollama (nomic-embed-text) | 127.03 ms | 113.95 ms |
| Gemini (gemini-embedding-001 via proxy) | 472.88 ms | 436.92 ms |

## Relevance: query "How can I free GPU memory used by the embedding model?"

### Ollama top 3

| Rank | Score | Snippet |
|---|---|---|
| 1 | 0.6096 | Free tony-omen GPU by moving embedding generation from local Ollama to Google Gemini. |
| 2 | 0.5400 | Weaviate vector search uses HNSW indexing and custom embeddings from the GPU embedding service. |
| 3 | 0.5213 | GPU queue manages workloads so that llama, imagen2, and txt2vid do not compete for VRAM. |

### Gemini top 3

| Rank | Score | Snippet |
|---|---|---|
| 1 | 0.7138 | Free tony-omen GPU by moving embedding generation from local Ollama to Google Gemini. |
| 2 | 0.6450 | The SSOT for Gemini embeddings documents the goal of offloading embedding work to the cloud. |
| 3 | 0.6007 | GPU queue manages workloads so that llama, imagen2, and txt2vid do not compete for VRAM. |

## Cross-model agreement

Average cosine between the Ollama and Gemini vectors for the same text: **0.0426**

## Notes

- The `text-embedding-004` model was not available in the Google project tied to this API key. The proxy falls back to `gemini-embedding-001` and truncates to 768 dimensions via `outputDimensionality`.
- No full MDDB or Weaviate test collections were created because neither MDDB nor Weaviate is currently running on tony-omen; the comparison was performed at the embedding-API level to de-risk the model/provider switch.
- Ollama local latency is far lower (typical ~32 ms), while the Gemini round-trip is dominated by network and API latency.

## Recommendation

Gemini results are semantically similar but slower. The proxy is viable for batch re-indexing; query latency should be monitored before a full switch.
