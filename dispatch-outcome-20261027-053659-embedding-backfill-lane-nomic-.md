# Dispatch outcome — embedding-backfill-lanes (nomic re-embed lane)

Card: `embedding-backfill-lanes` · runner: idc02 · 2026-10-27

## What shipped

**`scripts/embed/embed-lane.py`** — the backfill lane runner
(`lessons|news|banks|recall|stats`). Embeds ride LiteLLM
`ollama-nomic-embed` (nomic-embed-text load-balanced across
idc02+idc03 ollama — the lane OPS-0708 already built). Space-pinned:
the script only ever asks for that model and fails rather than
falling back — per the card note, nomic/bge-m3 vectors never leak
into the gemini-embedding-2 retrieval space.

- **lessons** — WP lesson CPT via board-api `/lesson` `op=list`+`op=get`
  (no WP creds needed) → title+content chunked ~1500c →
  `search_document:`-prefixed nomic vectors →
  `~/.local/share/embed-lane/lessons-nomic.jsonl`.
  **Ran live: 89 lessons → 506 vectors (2.5MB).**
- **news** — public `/wp/v2/news` titles → vectors of the exact
  `norm(title)` string news-digest embeds (unprefixed, symmetric) →
  `news-nomic.jsonl`, hashed for resume. **Ran live: 1657 titles
  (7.5MB).** Both stores placed on idc03 where the consumers run.
- **banks** — copies the 24 vector-searched BANK_COLLS collections
  (leader :11023 + CMS :11027, same routing map as embed-space-eval)
  into mddb-embed :11028 — the self-owned **bge-m3** bank via
  embed-pool-shim (MEM-0788/0805). Resume-safe; pauses `/add` while
  the target embed queue ≥3000/4000 so bulk copies can't drop.
  **Ran live: 7179 docs delivered, 0 failed, 0 dropped; the queue
  drains async (6996/9740 embedded within the hour, omen carrying
  ~99% of embeds at ~195ms — pool graceful-degradation working).**
- **recall** — `search_query:`-prefixed probe over a store. Verified
  on idc03: "thai gold price factors" → `trade-gold-thb` /
  `trade-data-sources` top hits. The lessons nomic space is
  queryable end-to-end; surfacing it in education-due/Ada is the
  follow-up consumer, noted in the job doc.

**`scripts/ada/news-digest.py`** — `NEWS_VEC_CACHE`: reuses
precomputed title vectors (default path
`~/.local/share/embed-lane/news-nomic.jsonl` — no unit env change
needed); cache hits skip the embed call entirely, misses embed via
the lane and append back so the store self-heals. Verified: 3/4-hit
smoke test; `news-situation.py`'s member-ask `embed()` call stays
positional-compatible and gains the cache for free.

**`docs/ssot/infrastructure/ssot.jobs.yml`** — three dispatcher
jobs declared (condition_path-gated until merge):
`embed-lane-news` (idc03, 1h, 26h window), `embed-lane-lessons`
(idc03, 1d), `embed-lane-banks` (idc02, 1d — driver off idc03).

**`tests/embed/test_embed_lane.py`** — 7 tests green: byte-level
store↔cache contract (norm/sha/vector round-trip), foreign-space
rejection, chunk bounds, resume dedup.

**`docs/ssot/jobs/mddb/2026-10-27-embedding-backfill-lane.yml`** —
job doc: lane topology, store format, gotchas (WP `after` is GMT /
double-encoding returns 0 rows; Cloudflare 403s bare urllib; mddb
has no vector-ingest — queue is the only vector path;
copied ≠ indexed), verify commands, follow-ups.

## Decisions worth noting

- "MDDB bank reindex" landed on the **bge-m3** mddb-embed bank, not
  nomic — that instance is the realized local-space lane
  (MEM-0805). Nomic's role is the lesson/news sidecar spaces + live
  digest clustering, exactly where it's already deployed.
- News vectors are embedded **without** nomic's `search_document:`
  prefix — byte-identical to what news-digest computes today, so
  the cache is a drop-in with zero drift. Lessons use the prefix —
  asymmetric retrieval.

## Verify

```bash
python3 scripts/embed/embed-lane.py stats                 # store + queue state
python3 scripts/embed/embed-lane.py recall --query "…"    # lessons recall probe
NEWS_VEC_CACHE=~/.local/share/embed-lane/news-nomic.jsonl \
  python3 scripts/ada/news-digest.py --dry-run            # "embed cache: N/M hits"
python3 -m unittest tests.embed.test_embed_lane           # 7 tests
```

## lessons:

- WP `/wp/v2/news?after=` compares GMT and must NOT be pre-quoted —
  the `index.php?rest_route=` wrapper already encodes once;
  double-encoded dates silently return 0 rows, not an error.
- embed-pool degrades exactly as designed: omen won ~99% of races
  (195ms) while idc02/idc03 timed out under load — single fast
  upstream carries the whole drain.
- mddb-embed's 4000-chunk queue is the real backpressure point;
  adaptive throttle on `/v1/vector-stats` queue.depth made a 7K-doc
  copy drop-free (0 dropped).
