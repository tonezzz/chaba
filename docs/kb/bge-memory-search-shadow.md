# BGE memory-search shadow (ADA-1299)

Date: 2026-11-19 · impl: ada-voice `backend/bge_memory_shadow.py` ·
validation: `scripts/bge-shadow-validate.py`, `tests/test_bge_memory_shadow.py`

## What it is

An **opt-in, asynchronous, metrics-only** shadow that runs alongside Ada's
existing Gemini `memory_search`. For every real recall it re-executes the
query against the isolated local BGE-M3 MDDB plane, reranks a bounded
candidate set through the Omen reranker, and logs one `key=value` metrics
line. **Gemini hits remain the only returned retrieval result** — the shadow
never changes what the model sees, never blocks the voice response, never
writes to MDDB, and never logs query or document text.

## Pipeline (per scheduled shadow)

1. **dense** — `POST {mddb}/vector-search` with `includeContent=false`,
   `topK=15` per bank collection, ≤4 collections in parallel. Same
   `filterMeta` status scoping as the baseline.
2. **fetch** — `POST {mddb}/get` for the merged/deduped top-20 candidates
   only, ≤8 in parallel; survivors go through the real `_doc_to_hit`
   ACL/status/draft filter.
3. **rerank** — top-10 candidates → `POST {rerank}/rerank` (Omen BGE
   reranker, bearer token), then overlap-vs-baseline metrics.

The whole run is deadline-bounded by `ADA_BGE_SHADOW_TIMEOUT_S` (clamped
0.1–10 s); each phase checks the remaining budget before issuing.

## Hard invariants (validated)

| Invariant | Mechanism | Proof |
|---|---|---|
| Never changes Gemini result | `schedule()` fires a detached task; returned hits are computed before it runs | `test_shadow_failure_does_not_change_gemini_result` |
| Never blocks voice response | `loop.create_task`, not awaited; schedule() returns in µs | `test_shadow_runs_concurrently_not_blocking` |
| Never writes MDDB | only `vector-search` + `/get` + `/rerank` reads | code + scenario runs |
| No query/doc text in logs | one `key=value` line; `phase=dense|fetch` error lines log collection name + exception type only | `privacy_minimized` live scenario (sentinel query absent, strict kv regex) |
| Queue bound | `MAX_INFLIGHT=2` — third concurrent call drops `reason=busy`, never queues | `test_schedule_drops_when_queue_full` + live scenario |
| Collection bound | `MAX_COLLECTIONS=32` — larger fanouts drop `reason=collection_limit` | `test_schedule_drops_over_collection_limit` |
| Timeout bound | per-call `timeout=remaining` on a shared deadline; stall → `status=empty` at ~deadline | live `stall_timeout`: 1.01 s elapsed at 1.0 s deadline |
| Failure isolation | every phase failure degrades to `status=empty`/`error`; `_run_safely` swallows all exceptions | live `dead_mddb_isolation` + `dead_reranker` |
| ACL/person scoping | shadow receives the exact `banks_for_person(person_entity)` list — it has no ACL of its own | `test_shadow_gets_only_authorized_banks`, `test_person_scoped_bank_replaces_personal_in_shadow` |
| Ops-plane exclusion | `is_ops_collection` banks are skipped even if a spec points at one | `test_shadow_skips_ops_collections` + live `ops_excluded` |
| Off switch | `ADA_BGE_SHADOW_ENABLED` unset/0, or either URL missing → `schedule()` no-ops | `off_switch`, `missing_endpoints` scenarios |

## Configuration (5 vars, per backend env file)

```
ADA_BGE_SHADOW_ENABLED=1
ADA_BGE_SHADOW_MDDB_URL=http://<bge-mddb>/v1      # BGE-M3 plane :11028
ADA_BGE_SHADOW_RERANK_URL=http://<omen>:11555/rerank
ADA_BGE_SHADOW_RERANK_TOKEN=<bearer>
ADA_BGE_SHADOW_TIMEOUT_S=5
```

Current state (verified 2026-11-19):

- **ada-dev + ada-ha-tony** (idc03): all 5 vars in
  `~/.config/secrets/*/backend.env`, confirmed in `/proc/<pid>/environ`.
  ada-ha-tony MDDB plane = idc02 `100.123.163.11:11028`, reranker =
  omen `100.75.102.88:11555`.
- **idc02 staging**: `~/.config/secrets/ada-lab.env` carries the same 5
  vars; `:11028` mddb-embed plane is local.

## Off switch / rollback

- **Disable**: set `ADA_BGE_SHADOW_ENABLED=0` (or delete it) in the
  backend env file and restart the service. Removing either `*_URL` var
  also no-ops it. No code change needed.
- No data to roll back — the shadow writes nothing.

## Observing the soak

```
journalctl --user -u ada-ha-tony.service --since today --no-pager \
  | grep "bge_memory_search shadow"
```

Line anatomy:

```
bge_memory_search shadow status=ok candidates=25 fetched=20 reranked=10
  baseline_hits=5 overlap_at_5=3 collections=2 collection_errors=0
  fetch_errors=0 dense_ms=131 fetch_ms=59 rerank_ms=1412 total_ms=1603
  baseline_degraded=False
```

- `status=ok|empty|error|dropped` — `empty` = no surviving candidates
  (deadline, degraded plane, or genuinely no hits), `dropped` =
  queue/collection bound, `error` = exception escaped `run_shadow`
  (still isolated from the user).
- `overlap_at_5` — reranked top-5 ∩ Gemini top-5; the metric this whole
  exercise exists to collect.
- `phase=dense|fetch` lines log `collection=<coll> error_type=<Exc>` —
  no content, ever.

**Traffic-drought caveat**: the shadow only fires on real
`memory_search` calls (`q` non-empty, not `*`, not `include_inactive`).
ada-ha-tony sees few of those — zero shadow lines in a period is usually
zero searches, not a fault. Correlate with `memory_search timing` lines.

**Cold-start caveat**: the first query after an idle stretch can pay
server-side query-embedding on the BGE plane (~5 s) and blow the
deadline once → `status=empty dense_ms≈timeout`. Warm runs are
~0.3–2 s. Expected; tune `ADA_BGE_SHADOW_TIMEOUT_S` if it repeats.

## Validate / probe

```bash
# Full 10-scenario live matrix (idc02 staging; read-only):
cd ~/CascadeProjects/ada-voice
set -a; source ~/.config/secrets/ada-lab.env; set +a
PYTHONPATH=. .venv/bin/python scripts/bge-shadow-validate.py   # expect 10/10 PASS

# Single live sample:
PYTHONPATH=. .venv/bin/python scripts/bge-shadow-probe.py      # expect status=ok

# Unit tests (12):
.venv/bin/python -m pytest tests/test_bge_memory_shadow.py -x -q
```

## Provenance

- Impl merged: ada-voice PRs #13/#14/#15 + `5114a5c`/`7c5ba50`
  (MEM-1129 dense+bounded-fetch fix — `includeContent=false` cut dense
  from ~4–6.6 s to ~130 ms).
- Validation branch (local on idc02, unpushed):
  `dispatch/20261119-130636-bge-shadow-validation` commit `c802286`
  (+8 unit tests, `scripts/bge-shadow-validate.py`).
- Evidence: `docs/ssot/jobs/ada/2026-11-19-bge-shadow-validation.yml`
  (chaba repo).
- Card: `ada-bge-memory-search-shadow` (ADA-1299).
