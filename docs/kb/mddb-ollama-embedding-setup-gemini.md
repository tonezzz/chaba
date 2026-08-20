---
category: operations
---

# Gemini Embedding Proxy (GPU Offload Alternative)

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

