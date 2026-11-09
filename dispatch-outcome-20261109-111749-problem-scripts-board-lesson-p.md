# Dispatch outcome — cross-repo-lesson-harvest

Moved the lesson_primer outcome-doc corpus to the mddb devin-handoff
bank so dispatches on non-chaba repos (ada-voice/sunsynk-card/mddb-fork)
contribute lessons. `dispatch_repos.close_out` now runs
`bank_outcome_lessons(card, session)` before the merge path: it parses
the session outcome doc's `lessons:` list (worktree glob, `git ls-tree`/
`git show` fallback on the session branch when the worktree is gone) and
POSTs each line to `ada-ha-bank-devin-handoff` as `lesson/<task_id>/<n>`
(meta kind:[lesson], job_id, repo, card, ts, source:[dispatch-outcome];
upsert-by-key dedupes re-runs; stderr-warn-only failures so it never
gates the merge). `lesson_primer` gained `_bank_candidates()`: kind=lesson
docs fetched over `/v1/search` (`MDDB_BASE_URL`, default
http://100.102.134.91:11023/v1 — kanban-dispatch convention), 60s
in-process cache, fail-open stderr warn, ranked at the outcome-doc tier
(rank 0); the repo-root glob remains as fallback. `LESSON_BANK=0`
disables both sides. Chose `close_out` over devin-dispatch-watch because
it is the one place every dispatch passes with task_id + worktree + card
all in scope (runner-agent on the runner, kanban-dispatch locally).
Verify: `pytest tests/board` green (506 passed, 6 skipped) incl. new
tests covering the banked keys/meta, dedupe-by-key on re-run, fail-open
on mddb failure, branch-fallback when the worktree is GC'd, bank-source
ranking, request shape, cache TTL, and the env kill-switch; a live loop
on the real bank from mn01 confirmed add→search→_bank_candidates()→delete
end-to-end. Trail: docs/ssot/jobs/kanban/2026-11-09-cross-repo-lesson-harvest.yml.

lessons:
- dispatch_repos.py is imported by runner-agent on remote runners where
  lesson_primer may not exist — keep the lessons: parse local (tiny
  duplication beats a fragile cross-module import on single-file deploys).
- mddb /v1/search returns contentMd + key + meta; meta values are
  string arrays everywhere (kind, job_id, source — match that shape).
- /v1/add upserts by (collection,key) — dedupe is free if the key is
  deterministic (lesson/<task_id>/<n>), so re-runs never duplicate.
- never let a network write sit on the merge critical path unbounded:
  per-doc 10s timeout + break-on-first-failure keeps a dead mddb cheap.
- .venv-test-style scratch dirs are NOT covered by the .venv/ gitignore
  pattern — delete them before session end or checkpoint sweeps them in.
