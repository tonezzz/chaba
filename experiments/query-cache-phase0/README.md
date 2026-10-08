# query-cache phase 0 — near-repeat measurement

Card `nest-query-cache` phase 0: what fraction of real
`ada_memory_search` queries are near-repeats of earlier queries?

- `bankq-corpus-20261008.jsonl` — 1366 prod rows mined from the
  nest-bank-router `memory_search tool timing` instrumentation
  (copied from ada-pi `tests/bench/`, branch
  dispatch/20261008-135509-bankq-student).
- `analyze.py` — chronological replay: embed each normalized query
  (Weaviate embed service, all-MiniLM-L6-v2 — the same space the
  Weaviate-resident cache uses; production gemini-embedding-2 was
  quota-dead on measurement day), max cosine vs all earlier rows in the
  same (scope, bank_arg) partition.
- `results.json` — full output.

Headline: **52%** of rows have an earlier same-scope match at cosine
>= 0.92; 34.2% are exact normalized repeats. Not niche — the cache is
the primary p50 win.

Policy + caveats: `docs/ssot/apps/ssot.apps.ada-memory.query-cache.yml`.
