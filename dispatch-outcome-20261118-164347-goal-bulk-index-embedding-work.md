# Dispatch outcome — embed-free-lane-daily-budget

## Decision (the card's explicit ask)

- **Where the budget lives:** proxy side (option b) for what this repo
  can enforce — implemented in `scripts/mddb/gemini-ollama-proxy.mjs`.
  Option (a) mddbd-side worker budget remains the architecturally
  correct home for *strict* query-vs-index priority, but that is
  mddb-fork code, outside this dispatch's repo — left as a followup.
- **Do query embeds get priority?** Partial, de-facto. The proxy cannot
  tell query from index embeds on mddbd traffic: the index worker sends
  per-chunk single-text calls over the same endpoint+URL as query
  embeds (one `MDDB_EMBEDDING_API_URL` for both). The card's check —
  "does EmbeddingJob carry the distinction" — is effectively YES by
  construction: mddbd's embed queue only ever holds index work;
  vector-search embeds synchronously and never enters it. (The
  gpu-queue EmbeddingJob in this repo is an unrelated Weaviate system.)

## What changed

- `scripts/mddb/gemini-ollama-proxy.mjs`
  - `FREE_GEMINI_HOURLY_BUDGET` (default 0=off): token bucket on the
    free leg per UTC hour — spreads the daily free quota across 24h so
    a bulk burst can't drain it by morning; past it the free leg
    refuses and the backup chain (OR → paid, capped) serves.
  - `FREE_GEMINI_BULK_DAILY_BUDGET` (default 0=off): per-UTC-day free
    budget for bulk-marked requests. Marker = `x-embed-lane: bulk`
    header or `"lane":"bulk"` body field.
  - `PAID_GEMINI_BULK_ALLOW=0`: bulk-marked requests also skip the paid
    leg, keeping the capped trickle for interactive traffic.
  - Budget refusals throw a tagged `err.freeBudget` → backup chain
    WITHOUT tripping the provider circuit or paging
    `embed_circuit_open`. Trips emit `embed_free_budget` ops-event
    (15min damped). `/health` exposes all new counters/budgets.
  - `GEMINI_API_BASE` env override added (default unchanged) so tests
    can point at a stub.
- `scripts/nest/embed-pool-shim.py`: `EMBED_POOL_LANE` env stamps
  `x-embed-lane` on upstream calls (set `bulk` on the backfill-bank
  pool); caller-set header is forwarded and wins.
- `scripts/ops-digest.py`: `FLAGGED += embed_free_budget`.
- `docs/kb/mddb-embedding-providers.md`, `docs/ssot/infrastructure/ssot.services.yml`: env docs.
- `docs/ssot/jobs/infrastructure/2026-11-18-embed-free-lane-budget.yml`: decision record.
- `tests/embed/test_gemini_proxy_budget.mjs`: node:test, 3/3 pass
  (real proxy subprocess against stub Gemini).

## Important findings

- **Live/repo drift:** the 2026-11-18 ~14:17 live patch to the proxy on
  idc03 (`GEMINI_FREE_KEYS` ring + per-key circuits, backup
  `.bak-keyring-20261118`) is NOT in the repo — deploying this version
  as-is would revert the keyring. Reconcile before next deploy.
- Demand ~38–58k embeds/day vs ~9k/day same-space capacity — the free
  lane is <5% of demand and exhausts daily regardless. This budget is
  a fairness layer, not a capacity fix; the 2026-11-18 incident was
  ALL legs exhausted + queue pinned at 4000 (see card
  mddb-fail-fast-writes-when-embed-provide-c55f11, repo=mddb-fork).
- Possible wrong-space hazard flagged in the job record: the pool shim
  races the gemini proxy for mddb-embed (bge-m3 1024d bank) — if the
  proxy wins it returns 768d gemini vectors into a bge-m3 bank.

## Verify

`node --test tests/embed/test_gemini_proxy_budget.mjs` — 3/3 green;
`node --check` clean; ssot-prose-smell 0 flagged; yaml parse clean.

## Deploy (not done — dispatch boundary)

Reconcile keyring first, then scp proxy to idc03 proxy dir, set e.g.
`FREE_GEMINI_HOURLY_BUDGET=80`, `FREE_GEMINI_BULK_DAILY_BUDGET=500`,
`PAID_GEMINI_BULK_ALLOW=0` in mddb-gemini.env, restart
gemini-ollama-proxy; optionally `EMBED_POOL_LANE=bulk` on
embed-pool-shim.service.
