# Dispatch outcome — BGE shadow dense+fetch+rerank (MEM-1129 blocker)

Card: bge-serving-path-dense-retrieval-with-in-b080f6 · Runner: idc02 · 2026-11-18

## What changed

Repo `ada-voice`, branch `dispatch/20261118-210023-blocker-for-mem-1129-productio`
(worktree at `.scratch/ada-voice`), commit `5114a5c`:

- `backend/bge_memory_shadow.py` — `run_shadow` restructured from one
  `includeContent=true` /vector-search per collection (measured ~4.2–6.6s
  on :11028 → every production shadow sample logged
  `status=empty/error TimeoutError`) into three deadline-bounded phases:
  1. **dense** — `/vector-search` `includeContent=false`, `topK=15`
     per collection, parallel ×4, same `filterMeta` scoping as before;
  2. **fetch** — `/v1/get` for the merged/deduped top-20 candidates
     only, parallel ×8, then `_doc_to_hit` filtering (unchanged
     ACL/status/draft semantics);
  3. **rerank** — unchanged top-10 reranker call.
- Shadow log line now reports `dense_ms fetch_ms rerank_ms` plus
  `fetched`/`fetch_errors`; per-phase failures log
  `phase=dense|fetch collection=<coll> error_type=<ExcType>`.
- `tests/test_bge_memory_shadow.py` — FakeClient now emulates the
  two-phase path; asserts `includeContent=False`, bounded /v1/get,
  new metrics.
- `scripts/bge-shadow-probe.py` — ad-hoc live probe used for the
  measurements below (kept for ADA-1299 soak verification).
- Trail note: `docs/ssot/jobs/ada/2026-11-18-bge-shadow-dense-fetch-rerank.yml`
  (chaba worktree).

## Measured (live :11028 mddb-embed + :11555 reranker, 4 real collections)

- `includeContent=false` vs `true` on ada-ha-bank-general: **~2ms vs 6.57s**
- `/v1/get` per doc: ~7ms
- Probe warm run: `status=ok candidates=15 fetched=15 reranked=9
  dense_ms=322 fetch_ms=66 rerank_ms=1078 total_ms=1470` — DONE bar met
  (status=ok, total_ms < ~2s real traffic).
- Probe cold run (fresh reranker): total 2939ms — rerank_ms=2547 cold;
  reranker is now the dominant cost (dense+fetch ≈390ms, inside the
  ~800ms sync-serving target). Reranker speed is external to this change.
- Caveat: cold server-side query embedding can still push dense over
  the 3s deadline once; `ADA_BGE_SHADOW_TIMEOUT_S` stays configurable.

## Preserved

ACL/person scoping upstream unchanged, `filterMeta`/`_doc_to_hit`
semantics unchanged, shadow still result-invisible (schedule()
untouched, metrics-only), Gemini fallback untouched.

## Verify

```
cd <ada-voice checkout>
.venv/bin/python -m pytest tests/test_bge_memory_shadow.py -x -q   # 4 passed
# live (needs secrets on host):
set -a; source ~/.config/secrets/ada-lab.env; set +a
PYTHONPATH=. .venv/bin/python scripts/bge-shadow-probe.py          # expect status=ok
```

Full suite: 1813 passed / 7 skipped; `tool-lint` clean. No prod deploy
(deploy-ada.sh is the separate gated step). Branch not pushed.
