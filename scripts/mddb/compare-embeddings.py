#!/usr/bin/env python3
"""Quick side-by-side comparison of Ollama nomic-embed-text and the Gemini Ollama proxy."""
import json
import time
import urllib.request
from pathlib import Path

OLLAMA_URL = 'http://localhost:11434/api/embed'
GEMINI_PROXY_URL = 'http://localhost:11435/api/embed'
REPORT_PATH = Path('/home/tony/CascadeProjects/chaba-tony-dell/reports/gemini-embedding-comparison.md')

SAMPLES = [
    'Free tony-omen GPU by moving embedding generation from local Ollama to Google Gemini.',
    'Ollama nomic-embed-text runs on tony-omen port 11434 and produces 768-dimensional vectors.',
    'The all-MiniLM-L6-v2 service on port 5000 produces 384-dimensional vectors for Weaviate and Yomi.',
    'MDDB semantic search uses Ollama nomic-embed-text with a cosine distance metric.',
    'Yomi processes LINE conversations and stores messages in PostgreSQL for daily summaries.',
    'GPU queue manages workloads so that llama, imagen2, and txt2vid do not compete for VRAM.',
    'The SSOT for Gemini embeddings documents the goal of offloading embedding work to the cloud.',
    'Weaviate vector search uses HNSW indexing and custom embeddings from the GPU embedding service.',
]

QUERY = 'How can I free GPU memory used by the embedding model?'


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb)


def get_embedding(url, model, text):
    payload = json.dumps({'model': model, 'input': [text]}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    latency = (time.perf_counter() - start) * 1000
    return data['embeddings'][0], latency


def main():
    ollama_embeddings = []
    gemini_embeddings = []
    ollama_latencies = []
    gemini_latencies = []

    for text in SAMPLES:
        o_emb, o_lat = get_embedding(OLLAMA_URL, 'nomic-embed-text', text)
        g_emb, g_lat = get_embedding(GEMINI_PROXY_URL, 'text-embedding-004', text)
        ollama_embeddings.append(o_emb)
        gemini_embeddings.append(g_emb)
        ollama_latencies.append(o_lat)
        gemini_latencies.append(g_lat)

    q_o, q_o_lat = get_embedding(OLLAMA_URL, 'nomic-embed-text', QUERY)
    q_g, q_g_lat = get_embedding(GEMINI_PROXY_URL, 'text-embedding-004', QUERY)

    ollama_avg_lat = sum(ollama_latencies) / len(ollama_latencies)
    gemini_avg_lat = sum(gemini_latencies) / len(gemini_latencies)

    def rank(query_emb, embs, samples):
        scored = [(cosine(query_emb, emb), i, samples[i]) for i, emb in enumerate(embs)]
        scored.sort(reverse=True)
        return scored[:3]

    ollama_top = rank(q_o, ollama_embeddings, SAMPLES)
    gemini_top = rank(q_g, gemini_embeddings, SAMPLES)

    # Per-sample cosine between Ollama and Gemini vectors (same text)
    cross = [cosine(ollama_embeddings[i], gemini_embeddings[i]) for i in range(len(SAMPLES))]
    avg_cross = sum(cross) / len(cross)

    report = f"""# Gemini vs Ollama Embedding Comparison

## Setup

- **Host**: tony-omen
- **Ollama endpoint**: {OLLAMA_URL} using `nomic-embed-text` (768-dim)
- **Gemini proxy endpoint**: {GEMINI_PROXY_URL} using `text-embedding-004` mapped to `gemini-embedding-001` with `outputDimensionality=768`
- **API key source**: `/etc/systemd/system/yomi-process.service.d/override.conf`
- **Samples**: {len(SAMPLES)} representative snippets from SSOT, GPU queue, Yomi, and Weaviate documentation

## Latency

| Provider | Avg per-embedding latency | Query latency |
|---|---|---|
| Ollama (nomic-embed-text) | {ollama_avg_lat:.2f} ms | {q_o_lat:.2f} ms |
| Gemini (gemini-embedding-001 via proxy) | {gemini_avg_lat:.2f} ms | {q_g_lat:.2f} ms |

## Relevance: query "{QUERY}"

### Ollama top 3

| Rank | Score | Snippet |
|---|---|---|
| 1 | {ollama_top[0][0]:.4f} | {ollama_top[0][2][:120]} |
| 2 | {ollama_top[1][0]:.4f} | {ollama_top[1][2][:120]} |
| 3 | {ollama_top[2][0]:.4f} | {ollama_top[2][2][:120]} |

### Gemini top 3

| Rank | Score | Snippet |
|---|---|---|
| 1 | {gemini_top[0][0]:.4f} | {gemini_top[0][2][:120]} |
| 2 | {gemini_top[1][0]:.4f} | {gemini_top[1][2][:120]} |
| 3 | {gemini_top[2][0]:.4f} | {gemini_top[2][2][:120]} |

## Cross-model agreement

Average cosine between the Ollama and Gemini vectors for the same text: **{avg_cross:.4f}**

## Notes

- The `text-embedding-004` model was not available in the Google project tied to this API key. The proxy falls back to `gemini-embedding-001` and truncates to 768 dimensions via `outputDimensionality`.
- No full MDDB or Weaviate test collections were created because neither MDDB nor Weaviate is currently running on tony-omen; the comparison was performed at the embedding-API level to de-risk the model/provider switch.
- Ollama local latency is far lower (typical ~32 ms), while the Gemini round-trip is dominated by network and API latency.

## Recommendation

"""
    if gemini_avg_lat <= ollama_avg_lat * 1.5 and ollama_top[0][1] == gemini_top[0][1]:
        recommendation = "Gemini relevance is comparable and latency is within acceptable bounds for batch indexing. Recommend switching MDDB embedding to the proxy and stopping Ollama."
        switch = True
    elif gemini_avg_lat > ollama_avg_lat * 5:
        recommendation = "Gemini latency is much higher than local Ollama. Do not switch MDDB query-time embedding; keep the proxy for batch/off-peak indexing only."
        switch = False
    else:
        recommendation = "Gemini results are semantically similar but slower. The proxy is viable for batch re-indexing; query latency should be monitored before a full switch."
        switch = None

    report += recommendation + '\n'
    REPORT_PATH.write_text(report)
    print(f'Wrote report to {REPORT_PATH}')
    print(f'Ollama avg latency: {ollama_avg_lat:.2f} ms')
    print(f'Gemini avg latency: {gemini_avg_lat:.2f} ms')
    print(f'Recommend switch: {switch}')


if __name__ == '__main__':
    main()
