# Dispatch outcome — embed-space-eval

**Verdict: paid Gemini space stays.** Built and ran a staged recall@k
harness (`scripts/ada/embed-space-eval.py`) over all 24 vector-searched
tony mddb collections — 8,109 active docs — on 48 real mined
`ada_memory_search` queries (34 EN / 14 TH) with flash-lite-judged
pooled relevance labels. Arms: gemini-embedding-2, nomic-embed-text raw,
nomic on EN-translated text, plus the live mddb index as reference.

**Result:** nomic+translate reaches ~86% of gemini's recall@5
(.399 vs .465 — outside the card's ~5% migration band), and the gap is
worst exactly where migration hoped to win: Thai queries (.311 vs .406,
–23% relative). nomic raw trails further (.330). The prod mddb index
arm (.450) lands within 3% of the doc-level gemini arm, validating the
methodology. MRR tells the same story (.761 vs .820). Nomic is ~25x
faster per query (0.056s vs 1.42s) but recall loses too much.

**Artifacts:** report + raw metrics + job record under
`docs/ssot/jobs/ada/2026-10-15-embed-space-eval.{md,json,yml}`.
Verify: read the .md (full method/metrics), rerun via the command in
its Reproduce section. Workdir with vectors/qrels: idc03:/tmp/embedeval.

**Cost:** $0.38 OpenRouter embed tokens (2.53M @ $0.15/Mtok — OR Vertex
route verified identical space, cos=1.0). Everything else $0 (free keys
for translate+judge, local Ollama for nomic).

**Findings worth keeping:** (1) `gemini-embedding-001` and `-2` are
*different* vector spaces — a silent mid-corpus fallback poisons an
index; the harness pins `-2`. (2) Free-tier embedding quota saturates
~2.3K calls — corpus-scale embeds need OR. (3) `sessions` +
`ops-scenarios` are ops-routed/keyword-ranked in production — not part
of the embedding space at all. Card commented with the verdict.
