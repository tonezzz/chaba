# dispatch outcome — lesson-primer-scoring-fixes

## What changed

`scripts/board/lesson_primer.py`:

1. **Word-boundary scoring** — `_score()` now intersects the line's
   token set with the keyword set instead of substring `k in tl`.
   Compound tokens (`ada-voice`, `ssot.kanban`) count both whole and by
   alnum parts; edge punctuation is stripped on both sides so
   `'tony-omen.'` still matches `tony-omen`. `'test'` no longer matches
   `latest`/`protest`, `'card'` no longer matches `discard`.
2. **Task-keyword eligibility** — `keywords()` returns
   `(task_kws, host_repo_kws)`. A candidate line now needs `>=1` task
   hit AND combined score `>= MIN_SCORE`. Host/repo tokens still rank
   but cannot alone qualify a line.
3. **Staleness** — `STALE_DAYS = 90`: lines from source files whose
   mtime is older score `-1`. `RETIRED_RE` (module constant, currently
   `\bidc01\b`, commented as needing periodic review) drops lines
   referencing retired infra unless they hit `>=2` task keywords.
4. **Bug fix found in live smoke** — `_comms_candidates` crashed on
   cards whose `comms:` entries are bare strings (`'str' object has no
   attribute 'get'` — the warn seen in test_kanban_dispatch_rails).
   Now handles both dict and string comms.
5. Contracts kept: `MAX_LINES=8`, `MAX_CHARS=5500`, `LINE_CAP=240`,
   `MIN_SCORE=2`, rank order outcome<job<comms<kb, `KANBAN_PRIMER=0`
   off-switch, warn-only primer failure inside `build_task`
   (kanban-dispatch.py untouched).

`tests/board/test_lesson_primer.py`: +4 tests —
substring false-match (unit + end-to-end), host-only line rejected /
task+host accepted, stale demotion (score-2 dropped, score-3 survives),
retired-host filter with the 2-task-kw escape.

`docs/ssot/jobs/kanban/2026-11-09-lesson-primer-scoring-fixes.yml`: job
trail incl. the comms-string and YAML-fold gotchas.

## Result / how to verify

- `python3 -m unittest tests.board.test_lesson_primer
  tests.board.test_kanban_dispatch_rails` — 10/10 ok. (pytest is not
  installed on idc02 and the chaba venv deliberately lacks it; the
  tests are unittest-style so `pytest tests/board/` will collect and
  pass them wherever pytest exists.)
- Live smoke `lp.build()` on real cards: `dispatch-merge-sweep`
  (host=idc02, repo=chaba) → 8 lines, all merge-sweep/dispatch-related;
  `ada-tool-guide-lesson-sweep` (idc02, ada-voice) → 8 lines, all
  deploy/ada-voice/lesson-sweep-related. Every selected line carries
  >=1 task keyword; no host-only fillers remain.

lessons:
- "real card comms entries can be bare strings — always
  isinstance-check before .get() when walking card yaml"
- "YAML '>' folded scalars merge lesson lines into one string; tests
  asserting per-line filtering need '|' literal blocks"
- "word-boundary matching needs ._- stripping on compound tokens or
  trailing punctuation silently drops hits substring matching caught"
