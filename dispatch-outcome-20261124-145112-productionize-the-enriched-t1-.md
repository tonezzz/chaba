# dispatch-outcome — distiller-enrich-productionize (attempt 3, idc02)

## What changed

Productionized the enriched T1 distiller + hybrid T1/T2 recall path
(card distiller-enrich-productionize / OPS-0778; bench evidence
reports/bench-recall-v2-20261022.md: T1 semantic alone 66.7% hit@3,
hybrid = 91.7%). Prior attempts never merged (macbook exit-code x2,
tony-dell oom-kill) — rebuilt lean; the OOM was almost certainly
bench-recall.py's in-memory KeywordIndex over full transcripts, so the
production T2 lane is disk-backed sqlite FTS5 instead.

- `scripts/ada/sync-devin-summaries.py`
  - Sticky `## Artifacts`: `_artifacts_tail()` re-appends the remote
    section verbatim whenever a run can't re-mine the transcript
    (post-delete, or a non-enrich invocation). Byte-exact roundtrip —
    the unchanged-check still hits, no rewrite storm.
  - T2 dump (default-on): `dump_transcripts()` writes
    `~/.local/share/devin/transcripts/<name>.md` for every
    `devin-session/*` session still in sessions.db, refreshing only
    when `last_activity_at` passes the dump mtime. `--no-transcripts` /
    `--transcript-dir` flags; `DEVIN_TRANSCRIPT_DIR` env override.
- `scripts/devin/session/session_recall.py` (new): hybrid recall —
  T1 = mddb `/v1/vector-search` on `ada-ha-bank-devin-tony`
  (status=active, threshold 0.45, topK 6, 8s timeout, fail-open);
  T2 = sqlite FTS5 (porter unicode61, bm25, snippet) over an
  incremental index at `~/.local/share/devin/session-recall/index.db`
  covering `transcripts/*.md` + `cli/summaries/*.md` + `summaries/*.md`.
  45s/call index budget; `--session/--project/--json/--reindex/--no-index`.
- `scripts/devin/session/notebooklm-recall.sh`: appends the <=4KB
  hybrid block to SessionStart `additionalContext` (query = session
  title from sessions.db + project name; memory tail preserved).
- `systemd/devin-summaries-sync.service` + `systemd/ada-memory-pull.service`:
  `--enrich` added (jobs.yml tony_omen job + generated unit already had
  it). Without this, those units would strip Artifacts pre-sticky-fix.
- `ansible/playbooks/session-capture.yml`: stats `session_recall.py`
  presence alongside the other hook scripts.
- `docs/ssot/infrastructure/ssot.jobs.yml`: devin-summaries-sync note.
- `docs/ssot/jobs/infrastructure/2026-11-24-distiller-enrich-productionize.yml`: full trail.
- `tests/devin/test_session_recall.py`: 11 tests (fts query, chunking,
  BM25 retrieval, incremental index + stale removal, sticky tail).

## Verification (all on idc02)

- `sync-devin-summaries.py --enrich --dry-run` → exit 0, full pipeline.
- `sync-devin-summaries.py --enrich --max-writes 3` → exit 0, 3 docs
  upserted to the production bank (idempotent keys).
- `enriched()` mined a live `## Artifacts` (+1263 chars) from this
  session's transcript; `_artifacts_tail` roundtrip byte-exact.
- `session_recall.py --session chain-fact --project chaba` → T1 6
  semantic hits + T2 FTS5 hits (top T2 hit was literally the
  bench-recall-v2 transcript). `--json` OK; MDDB-down fail-open OK.
- `notebooklm-recall.sh` end-to-end with a SessionStart payload →
  valid hookSpecificOutput JSON, 3999-char context.
- `pytest tests/devin/test_session_recall.py` → 11 passed.

## Deploy notes (not done — repo-side only per dispatch rules)

- Hook pair must be scp'd together to `~/.config/devin/scripts/` on
  interactive hosts (same manual pattern as runner-agent):
  `scripts/devin/session/{notebooklm-recall.sh,session_recall.py}`.
- sync-devin-summaries.py reaches hosts via chaba-repo-sync (automatic);
  updated systemd units need the usual unit redeploy flow.
- Follow-up worth a card: idc02 runs dispatch sessions but has NO
  devin-summaries-sync timer — its cli summaries reach the bank only on
  manual runs.

lessons:
- In-memory BM25/index-over-all-transcripts is what OOM-killed the prior dispatch; sqlite FTS5 with mtime+size incremental indexing is the safe production shape.
- Enrichment must be a ratchet: without sticky ## Artifacts, any bare `sync-devin-summaries.py` run (ada-memory-pull, post-delete) silently strips the section on next compare.
- SessionStart hooks have no user query — the sessions.db session title + project dir name is the best free recall query.
- session ids in sessions.db are friendly names ('chain-fact'), NOT the dispatch task ids or cli history hex ids — transcript_for/dumps only resolve devin-session/<name> keys.
- FTS5 'porter unicode61' + bm25() + snippet() covers the BM25 lane with zero deps; budget-cap indexing so first run on big archives can't stall the 180s hook.
