# Dispatch outcome — mddb-leader-bge-m3-migration-11023

**Result: migration executed and verified live; async force-reindex of all 63
collections is draining on idc03 leader :11023.** Card
`mddb-leader-bge-m3-migration-11023`, host mn01, 2026-11-24 ~21:30–22:00 ICT.

## What changed (prod, idc03)

1. `~/.config/containers/systemd/mddb.container` — backup
   `mddb.container.bak-20261124-bge`; env diff: `MDDB_EMBEDDING_API_URL`
   → `http://100.102.134.91:11436`, `MODEL` → `bge-m3`, `DIMENSIONS` →
   `1024`, **plus new `MDDB_OUTBOUND_ALLOWLIST=100.102.134.91`** (SSRF
   guard blocked the private apiUrl on API-written configs). daemon-reload
   + restart (3 boots total — see gotcha).
2. **Stored embedding config (the step the card missed):** :11023's DB has
   `/v1/embedding-configs` and a stored `isDefault` (`gemini-proxy`,
   :11435) that overrides env for the embed worker. Flipped default to the
   pre-staged `bge-m3-local` via `POST /v1/embedding-configs/set-default`,
   PUT its apiUrl to the tailnet shim addr, restarted. `gemini-proxy` and
   `nomic-local` kept as non-default rollback configs.
3. Fired `POST /v1/vector-reindex {collection, force:true, async:true}` for
   all 63 collections, ordered ada-ha-bank-* first, chunk-monsters
   (devin-tony 76k chunks, devin-handoff 34.7k docs) last.

## Verified

- Canary reindex `ada-ha-bank-dev-scratch`: embedded=1, failed=0, 1.9s.
- `vector-search` returns bge hits on `ada-ha-bank-dev-scratch`,
  `ada-ha-bank-general`, `ada-ha-bank-personal-tony`,
  `ada-ha-bank-note-tony` within ~10 min of drain start.
- `/v1/config` vectorConfig = bge-m3/1024/:11436 (env); provenance warning
  correctly lists 52 collections stale vs bge-m3.
- Followers: idc02 `mddb` and con01 `mddb-follower` have NO embed env —
  their vector-search already returned "no embedding provider" before the
  migration (pre-existing, no regression; step 1 of card resolved).

## Scale correction vs card

Card said 27.7k docs / ETA 8–12h. Live stats: **56.5k docs / 144.4k
chunks** → realistic drain ~20–30h at warm-pool pace (~100–120 chunks/min,
2 embed workers, effective pool = idc03+omen only after 11-20/24 upstream
drops). Degraded vector recall ramps per-collection; banks were queued
first. Queue depth ~2.4k/4000 with occasional shim 504s — retries
(maxAttempts=50), dropped=0.

## Follow-ups (also in card comms + runbook)

- Post-drain: non-force `/v1/vector-reindex` sweep per collection to pick
  up chunks that failed during pool saturation, then verify
  general/personal-tony search + Ada memory_search smoke; golden-set eval
  card `cms-plane-bge-golden-set-eval` still the labeled-recall gate.
- `gemini-ollama-proxy` :11435 lost its last mddb consumer — keep as
  declared fallback or retire per host-hygiene.
- Reindex jobs are in-memory (`/v1/vector-reindex/jobs`) — a leader restart
  mid-drain loses job tracking; embed queue itself requeues to 50 attempts.

## Deliverables

- `docs/ssot/jobs/mddb/2026-11-24-leader-11023-bge-m3-migration.yml` —
  full runbook: env diff, stored-config procedure, rollback, followers,
  follow-ups.
- `docs/kb/mddb-embedding-providers.md` — appended "Stored embedding
  configs override env" section with the exact API sequence.
- Card comms updated at each milestone (preflight, env-live canary,
  reindex-running).

## How to verify

```bash
curl -s http://100.102.134.91:11023/v1/config | jq .vectorConfig   # bge-m3/1024/:11436
curl -s http://100.102.134.91:11023/v1/embedding-configs | jq '.configs[]|{id,isDefault,apiUrl}'
curl -s http://100.102.134.91:11023/v1/vector-reindex/jobs | jq '[.jobs[].status]|group_by(.)|map({(.[0]):length})|add'
curl -s -X POST http://100.102.134.91:11023/v1/vector-search -H 'Content-Type: application/json' \
  -d '{"collection":"ada-ha-bank-general","query":"wifi password","topK":3}'
```

lessons:
- mddb embed plane has TWO config layers: `MDDB_EMBEDDING_*` env AND DB-stored `/v1/embedding-configs` — a stored `isDefault` silently wins over env; env-only migrations fail on instances that have stored configs (check `GET /v1/embedding-configs` first).
- API-written embedding configs are SSRF-guarded: private apiUrls need `MDDB_OUTBOUND_ALLOWLIST=<host>` env at boot; loopback needs no opt-in but embed-pool-shim binds the tailnet addr only, so `127.0.0.1:11436` refuses.
- The embed worker caches the embedding config in memory — after `set-default`/PUT, restart mddb.service before embeds pick it up.
- PUT `/v1/embedding-configs/{id}` requires the FULL config object (provider/model/dimensions/apiUrl), not a partial patch.
- `while read` loops over a newline-less file silently skip the last item — the biggest collection (devin-handoff) almost didn't get its reindex job; write lists with a trailing newline or loop differently.
