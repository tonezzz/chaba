# Dispatch outcome — BGE memory-search shadow validation (ADA-1299)

Card: ada-bge-memory-search-shadow · Runner: idc02 · 2026-11-19

## What changed

**ada-voice** (worktree `.scratch/ada-voice`, local branch
`dispatch/20261119-130636-bge-shadow-validation`, commit `c802286` —
unpushed, salvageable from idc02 like the MEM-1129 branch was):

- `tests/test_bge_memory_shadow.py` — 4 → 12 tests. New coverage for the
  card's required validations: queue bound (`MAX_INFLIGHT=2`, third
  schedule drops `reason=busy`), collection bound (`MAX_COLLECTIONS`),
  missing-endpoint no-op, deadline bounding on a stalled plane
  (`status=empty`, `collection_errors`, bounded wall time),
  ops-collection exclusion, person-policy allow-list inheritance
  (`bank='all'` shadow receives exactly the authorized subset),
  person-scope swap (`personal-kk` replaces `personal`), and a
  non-blocking proof (baseline result returns while the shadow task is
  still pending).
- `scripts/bge-shadow-validate.py` — repeatable 10-scenario live matrix
  against the real `:11028` BGE plane + `:11555` Omen reranker. Prints
  PASS/FAIL per scenario, exits non-zero on any failure.

**chaba** (this worktree, commit `d32250ac2a`):

- `docs/kb/bge-memory-search-shadow.md` — runbook: pipeline anatomy, the
  11 hard invariants with their proofs, env-var config per instance, off
  switch/rollback (ENABLED=0 or delete URLs + restart — nothing else
  needed, no data written), soak monitoring, traffic-drought and
  cold-start caveats, validation commands, provenance.
- `docs/ssot/jobs/ada/2026-11-19-bge-shadow-validation.yml` — evidence
  trail.

## Verified

- **Unit**: `pytest tests/test_bge_memory_shadow.py` → 12/12 pass;
  `-k "memory or bge"` suite → 188 pass; `tool-lint` clean.
- **Live matrix on idc02** (`ada-lab.env`): **10/10 PASS** —
  off_switch, missing_endpoints, healthy (`status=ok reranked=10
  total_ms=331`), queue_bound (`[True, True, False]` + `reason=busy`
  logged), dead_mddb_isolation (`status=empty`, 4 collection_errors,
  0.05s), dead_reranker (`status=error ConnectError` via `_run_safely`),
  stall_timeout (non-routable endpoint cut at **1.01s** of a 1.0s
  deadline → `status=empty`), tiny_timeout, ops_excluded
  (`collections_scanned=4` not 5), privacy_minimized (sentinel query
  absent from every line; strict `key=value` format holds).
- **Prod context on idc03** (real in-process `memory_search`,
  ada-ha-tony env, anonymous `person_entity=None`): baseline returned 5
  Gemini hits undegraded; shadow logged `status=ok candidates=25
  fetched=20 reranked=10 baseline_hits=5 overlap_at_5=3 collections=2
  collection_errors=0 fetch_errors=0 dense_ms=131 fetch_ms=59
  rerank_ms=1412 total_ms=1603` — the **first post-MEM-1129 status=ok in
  prod context** (deployed HEAD a2a2026 includes 5114a5c). Anonymous ACL
  verified live: `banks_for_person(None)` = general+home only; shadow
  queried exactly those 2 collections. All 5 `ADA_BGE_SHADOW_*` vars
  confirmed in the service's `/proc` environ.
- Preserved: Gemini is the only returned result; shadow is detached
  (`create_task`), read-only on MDDB, content-free in logs.

## Not done / watch items

- **Soak still thin**: ada-ha-tony has had zero organic `memory_search`
  calls since the 2026-11-18 21:45 restart — no organic new-format
  shadow lines yet. The 3 journal lines from Nov 18 are old-format
  (pre-fix timeouts). Overlap accumulation needs real voice traffic; the
  runbook documents how to watch it (`journalctl --user -u ada-ha-tony |
  grep "bge_memory_search shadow"`).
- The validation branch is local on idc02 — merge via the normal
  ada-voice flow (tony-dell edit point / deploy-ada.sh) if the tests +
  validator should land permanently.
- `rerank_ms` (~1.1–2.5s) dominates the shadow's total; irrelevant while
  async, but it is the number that matters if BGE is ever promoted
  toward the served path (separate approval required — unchanged).

## Verify

```
# idc02 staging:
cd ~/CascadeProjects/ada-voice
set -a; source ~/.config/secrets/ada-lab.env; set +a
PYTHONPATH=. .venv/bin/python scripts/bge-shadow-validate.py   # 10/10 PASS
.venv/bin/python -m pytest tests/test_bge_memory_shadow.py -x -q  # 12 pass

# prod soak:
ssh idc03 'journalctl --user -u ada-ha-tony.service --since today \
  --no-pager | grep "bge_memory_search shadow"'
```

lessons:
- ada-ha-tony is a **user** unit on idc03 (`systemctl --user`,
  `journalctl --user`); system-level unit queries return MainPID=0.
- `~/.config/secrets/tony-ha/backend.env` is NOT bash-sourceable
  (unquoted multi-line values with parens, line 56) — load needed keys
  in Python instead of `source`.
- The shadow only fires on real memory_search calls — zero shadow lines
  in the journal means zero searches, not a fault; correlate with
  `memory_search timing` lines before declaring a soak healthy or dead.
- `includeContent=false` dense + `/v1/get` fetch phase (5114a5c) cut
  dense from ~5s timeouts to ~131ms — old-format log lines lack
  `fetch_ms`, so line format itself tells you which code emitted it.
