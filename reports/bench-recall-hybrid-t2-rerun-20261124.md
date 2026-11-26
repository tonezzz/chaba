# bench-recall hybrid_t2 live rerun — post-prune archives — 2026-11-24

Card: `wire-hybrid-recall-t1-semantic-t2-keywor-ef89a0` · Runner: tony-dell ·
Judge: gemini-3.5-flash-lite (LiteLLM gateway) · Fixture: same 22 sessions /
36 goldens as bench-recall v2.

## What changed vs the 2026-10-22 run

The fixture sessions are **gone from every reachable sessions.db** (pruned —
the end-state this bench exists to justify). Their raw transcripts survive
only as the local T2 archives: `~/.local/share/devin/cli/summaries/<name>.md`
compaction dumps on tony-dell (912MB across 786 archive files). The corpus
sidecar was rebuilt from those dumps (user/assistant/assistantthought
messages, 8KB/msg cap, 600KB head+tail/session cap, cross-section dedupe) —
5.1MB total vs the original sessions.db extraction. Some sessions are thin
(e.g. awake-sheet 2.5KB — tool-stubbed dumps), which is the real post-prune
T2 corpus, not a benchmark artifact.

## Result — hybrid verdict reproduces exactly

| lane | hit@1 | hit@3 | p50 |
|---|---|---|---|
| mddb semantic, T1 enriched bank (status=active) | 38.9% | 63.9% | 1.96s |
| transcript/archive BM25 (T2, surviving dumps) | 58.3% | 66.7% | 0.11s |
| **hybrid T1 ∪ T2 (6 items)** | 38.9% | **91.7%** | 1.83s |

Original v2 run: hybrid_t2 = **91.7%** hit@3 — identical. T1 alone stayed
below AQ (63.9% < 80%), T2 alone dropped to 66.7% on the thinner archives —
the two lanes still complement each other to the same 91.7% ceiling.

hybrid_t2 misses (3/36): `brave-squirrel#1`, `puzzle-licorice#1`,
`swamp-language#1` — vs original residual `awake-sheet#1`,
`brave-squirrel#2`, `confusion-subway#1`.

## Companion verification (same session)

- `session_recall.py` manual recall, 3 known sessions on tony-dell
  (aluminum-opossum/VCAST, awake-sheet/MCP-SSOT, confusion-subway/Jev):
  correct session surfaced in T1 and/or T2 with golden-answer content in
  the snippet for all three.
- Full `notebooklm-recall.sh` SessionStart payload on tony-dell:
  additionalContext 6292–7915 chars (**≤8KB**), session-title query join
  verified, T2 index = 786 files / 594,815 chunks.
- Fail-open: `MDDB_RECALL_URL` dead → T2-only output, exit 0;
  `session_recall.py` absent → memory-tail-only output, exit 0.

Raw: `reports/bench-recall-hybrid-t2-rerun-20261124.json` (force-added;
reports/ is gitignored). Bench command:

```
python3 scripts/bench-recall.py --lanes mddb transcript hybrid_t2 \
  --corpus /tmp/bench-recall-corpus-20261124.json \
  --json /tmp/bench-hybrid-t2-20261124.json   # on tony-dell
```
