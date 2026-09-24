# MDDB embedding providers — OpenRouter primary, rollback to Gemini

Status: active since 2026-09-23. All collections embedded in the
OpenRouter/Vertex `gemini-embedding-2` space (768 dims).

## Why OpenRouter is primary

Google AI Studio free-tier quota for `gemini-embedding-2` flaps under
load (429s for hours). OpenRouter serves the same model via its
`Google` (Vertex) route at ~$0.20/M tokens — stable and cheap.

**Critical**: Vertex and AI Studio produce *different* vectors for the
same model name — Vertex applies `task_type` conditioning by default.
Vectors from the two endpoints are NOT interchangeable. The whole
corpus must stay on ONE path or scores collapse to ~0.

## Active configuration

- Proxy: `scripts/mddb/gemini-ollama-proxy.mjs` (deployed to
  `idc01:~/.config/containers/mddb/proxy/`, quadlet
  `systemd/gemini-ollama-proxy.container`).
- Env (`idc01:~/.config/secrets/mddb-gemini.env`):
  - `OPENROUTER_API_KEY` — enables the OR tier.
  - `OPENROUTER_PRIMARY=1` — OR serves every request; Gemini/Ollama
    are degraded fallbacks only.
- Provider pin: `provider.order: ["Google"], allow_fallbacks: false` —
  OR's default `Google AI Studio` upstream is broken
  (`API_KEY_INVALID`) and is a different vector space anyway.
- Fallback chain: OR → direct Gemini → Ollama `nomic-embed-text`.
  Both fallbacks are different spaces — degraded-emergency only.
- Response `fallback` field reports which provider served each request
  (`google/gemini-embedding-2` = OR, `nomic-embed-text` = Ollama).

## Rollback to direct Gemini (kept for later)

1. Remove `OPENROUTER_PRIMARY=1` from `mddb-gemini.env` (keep the key —
   OR stays as the middle fallback tier).
2. `ssh idc01 'systemctl --user restart gemini-ollama-proxy'`
3. **Mandatory full reindex** — the corpus is in Vertex space and
   direct-Gemini queries will not match it:
   ```bash
   # for each collection in /v1/stats:
   curl -X POST http://100.74.146.0:11023/v1/vector-reindex \
     -H 'Content-Type: application/json' \
     -d '{"collection":"<name>","force":true}'
   ```
   Run it as a background loop — big collections take minutes and the
   endpoint may return an empty body while completing server-side.
4. Verify: `ADA_MEMORY_BANKS_FILE=... python3 scripts/ada/recall-canary.py`
   should pass ~10/12+.

## Known issues

- MDDB `HNSW Add recovered from panic` (nil vector) still drops
  occasional chunks during bulk reindex — a doc may lose tail chunks
  (seen on `tony-projects/public-host-plan`, `kb-development`).
  Affected docs need re-add or split ingest; fix is upstream in mddb.
- OR key spend limit — check `GET /api/v1/auth/key`
  (`limit_remaining`); topped to $4 on 2026-09-23.
- OR-primary mode is FAIL-HARD: if OR errors the proxy returns 502 —
  Gemini/Ollama are never used because a wrong-space write is worse
  than an error. Response field `provider` names the serving backend.
- `mddb-embed-space-check.timer` (hourly flip back to Gemini space)
  RETIRED 2026-09-23 — obsolete and dangerous under OR-primary: on
  Gemini recovery it would have reindexed the corpus into a second
  space. Unit files + script removed from idc01.
- Incident 2026-09-23: Cloudflare WARP (`warp-svc`) running on idc01
  mangled inbound connections — SSH dropped pre-banner, services hung.
  Root cause not fully isolated (its fwmark/table-65743 rules coexist
  with tailscale's without an obvious main-table clash — likely a
  userspace interception or resource issue). ARCHIVED: unit stopped +
  disabled 2026-09-23; re-enable only after investigating why it was
  installed (Cloudflare Zero Trust for the future domain?). If SSH to
  idc01 ever accepts TCP then closes before the banner, check
  `systemctl is-active warp-svc` first.

## Verification commands

```bash
# which provider serves embeds:
ssh idc01 'curl -s http://127.0.0.1:11435/api/embed \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"gemini-embedding-2\",\"input\":\"probe\"}"' | jq .fallback
# → "google/gemini-embedding-2" means OR (correct steady state)

# proxy log:
ssh idc01 'podman logs --tail 20 gemini-ollama-proxy'

# recall benchmark:
ADA_MEMORY_BANKS_FILE=~/.config/ada/memory-banks.json \
  python3 scripts/ada/recall-canary.py
```
