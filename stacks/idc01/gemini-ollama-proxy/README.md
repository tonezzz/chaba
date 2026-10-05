# gemini-ollama-proxy — embedding proxy for mddb

Node service fronting Gemini embeddings with an Ollama fallback — mddb calls
it at `127.0.0.1:11435` (`MDDB_EMBEDDING_API_URL`). Runs `Network=host`,
binds loopback.

## Files

- `gemini-ollama-proxy.container` — quadlet
- app: `~/.config/containers/mddb/proxy/` — `gemini-ollama-proxy.mjs` +
  `health-check.mjs` (mounted ro)
- secrets: `~/.config/secrets/mddb-gemini.env` — Gemini API key

## Move

1. rsync `~/.config/containers/mddb/proxy/` and `~/.config/secrets/mddb-gemini.env`.
2. Needs `ollama` on the same host for the fallback path (or point
   `OLLAMA_FALLBACK_BASE` elsewhere).
3. mddb's `MDDB_EMBEDDING_API_URL` targets loopback — keep the proxy
   co-located with the mddb leader or repoint it.
4. `After=gemini-ollama-proxy.service` in mddb.container assumes co-location.
