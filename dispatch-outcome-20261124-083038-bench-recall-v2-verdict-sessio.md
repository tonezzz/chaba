# Dispatch outcome — wire-hybrid-recall-t1-semantic-t2-keywor-ef89a0

**Task:** bench-recall v2 verdict — extend the SessionStart recall hook to
run hybrid recall: (a) T1 semantic over the devin-session bank, (b) T2
keyword over local transcript archives, (c) merged top-k at <=8KB,
fail-open, T2 local-only. Verify: rerun bench-recall hybrid_t2 live +
manual recall on 3 known sessions.

## What I found

The heavy lifting already landed via `distiller-enrich-productionize`
(commit a12b75e91f): `scripts/devin/session/session_recall.py` (T1 mddb
`/v1/vector-search` status=active + T2 sqlite FTS5/bm25 over
`transcripts/`, `cli/summaries/`, `summaries/`) wired into
`notebooklm-recall.sh`. This dispatch audited it against the card spec,
closed two real gaps, and ran the required live verification.

## What changed (commit 62279f3d65 on dispatch branch)

- `scripts/devin/session/notebooklm-recall.sh` — injection was up to
  ~12KB (8000c memory tail + 4000c hybrid). Rebalanced to 3500c + 4300c
  => worst case ~7.9KB, under the 8KB cap.
- `scripts/devin/session/session_recall.py` —
  - T2 index open/index failure no longer kills T1 (independent try;
    previously any FTS5/index error returned zero output — both lanes
    lost).
  - Both lanes empty => emits nothing (was an empty header = context
    noise).
  - T1 results stable-sorted so `devin-session/<name>` distilled
    summaries surface before `devin/<hex>` raw transcript dumps
    (same set, better readability).
- `tests/devin/test_session_recall.py` — +2 fail-open tests (13 pass).
- `docs/ssot/jobs/infrastructure/2026-11-24-hybrid-recall-wiring.yml` —
  job doc with decisions/residual.
- `reports/bench-recall-hybrid-t2-rerun-20261124.{json,md}` — rerun
  evidence (force-added; reports/ is gitignored).

## Verification (all live, on tony-dell)

- **bench-recall hybrid_t2 rerun:** fixture sessions are pruned from
  every reachable sessions.db, so I rebuilt the corpus sidecar from the
  surviving T2 archives (`~/.local/share/devin/cli/summaries/<name>.md`
  compaction dumps — the actual post-prune transcript source). Result:
  **hybrid_t2 hit@3 = 91.7% — identical to the v2 verdict** (T1 63.9%,
  T2-alone 66.7% on the thinner archives; the lanes still complement to
  the same ceiling). 3 misses: brave-squirrel#1, puzzle-licorice#1,
  swamp-language#1.
- **Manual recall, 3 known sessions** (aluminum-opossum/VCAST,
  awake-sheet/MCP-SSOT, confusion-subway/Jev): correct session +
  golden-answer content surfaced via T1 and/or T2 every time.
- **Hook end-to-end** SessionStart payload: additionalContext
  6292–7915 chars (<=8KB); session-title query join confirmed.
- **Fail-open:** dead MDDB_RECALL_URL => T2-only output exit 0;
  missing session_recall.py => memory-tail-only exit 0.
- T2 index on tony-dell built during verification: 786 files /
  594,815 chunks at `~/.local/share/devin/session-recall/index.db`.

## Residual / how to verify

- **Not deployed anywhere.** `~/.config/devin/scripts/` on tony-dell,
  tony-omen has the older notebooklm-recall.sh (no hybrid call) and no
  session_recall.py; tony-macbook has the flat 1604B version. Deploy =
  scp both files together (same pattern as runner-agent):
  `scp scripts/devin/session/{notebooklm-recall.sh,session_recall.py}
  <host>:~/.config/devin/scripts/`
- Verify after deploy: start any Devin session on the host; the
  SessionStart hook injects "# Session recall — hybrid T1 semantic +
  T2 transcript keyword"; or run
  `python3 scripts/devin/session/session_recall.py --reindex` then a
  query.
- First index pass per host is budget-bounded (45s/call) — recall is
  partial until caught up over successive hook fires.

lessons:
- bench-recall fixture sessions were already pruned from every
  sessions.db — the corpus sidecar must be rebuilt from the T2 archives
  themselves (`cli/summaries/<name>.md` compaction dumps survive on
  tony-dell, 912MB/786 files); they are the real post-prune T2 corpus.
- cli/summaries/<name>.md dumps stub Tool messages to
  [CORTEX_STEP_TYPE_*] and repeat message lists across compaction
  sections — dedupe by content hash when extracting.
- python3 nohup output is block-buffered — a silent bench log != a stuck
  bench; check /proc/<pid>/io and socket count before assuming a hang.
- mddb ada-ha-bank-devin-tony is 100% session docs — status=active is
  already the bank scope; subject filters only perturb ranking.
