# dispatch-lesson-primer — outcome

Dispatches no longer start from zero. `kanban-dispatch` now injects a
`KNOWN_PITFALLS` block into every dispatch prompt — the top 8 lesson
lines (≤~1.5k tokens) matched on host + repo + task keywords — and
every outcome doc self-seeds the corpus via a `lessons:` list.

## What changed

- `scripts/board/lesson_primer.py` — new module. `build(card, host,
  repo, root)` collects candidates from four ranked sources, scores by
  distinct keyword hits (task tokens len≥4 minus stopwords + host + repo
  tokens), requires ≥2 hits, dedupes, returns top 8 lines within 5500
  chars:
  1. `dispatch-outcome-*.md` `lessons:` lists (self-seeded — rank 0)
  2. `docs/ssot/jobs/**/*.yml` — `method_notes`/`side_findings`/`gotchas`/
     `lessons`/`pitfalls` fields at any depth; paragraphs split on
     sentence/GOTCHA: boundaries, only signal-word lines kept (rank 1)
  3. kanban card comms matching `gotcha|failed|lesson|do not|never`,
     prefixed `[card-id]` (rank 2)
  4. `docs/kb/**/*.md` runbook pointer lines on title+abstract match
     (rank 3)
- `scripts/board/kanban-dispatch.py`:
  - `build_task` appends `---\nKNOWN_PITFALLS …` immediately after
    TASK_RAILS (before RETRY_RAILS/REPORT_RAILS); lines recorded in
    `LAST_PRIMER_LINES`
  - `start_pending` logs injected lines to card comms:
    `primer injected N lesson(s): <80-char previews>` (auto-capped 500)
  - TASK_RAILS gained the self-seeding bullet: every dispatch-outcome
    doc must end with a `lessons:` list (0–5 gotcha lines)
  - `KANBAN_PRIMER=0` env disables; primer exceptions are warn-only and
    never block a dispatch
- `tests/board/test_lesson_primer.py` — new: all-sources harvest,
  signal-word filtering, MIN_SCORE drop, format_block (synthetic repo
  root in tmpdir)
- `tests/board/test_merge_sweep.py` — fixture fix: local git identity on
  the `served` clone. Was red on hosts without global `user.email`
  (tony-dell has none) — would have wedged the merge test-gate.
- `docs/ssot/kanban/ssot.kanban.yml` — `execution.lesson_primer` doc +
  `task_rails` note on the outcome-doc `lessons:` contract
- `docs/ssot/jobs/kanban/2026-10-09-dispatch-lesson-primer.yml` — trail

## How to verify

- `grep -l KNOWN_PITFALLS scripts/board/kanban-dispatch.py` (the card's
  auto_done_when gate)
- `python3 -m pytest tests/board tests -x -q` → 107 passed, 37 skipped
- Live smoke: `build_task(dispatch-lesson-primer card)` renders
  KNOWN_PITFALLS after TASK_RAILS with 8 real lines; ~3s corpus scan,
  runs in phase B so the board flock is never held

## Result

Spec points 1–4 all landed. Next dispatch on this host already picks up
contextual lessons (the smoke run surfaced the stale-runner DEVIN_MODEL
incident for a dispatch-scoped card). Corpus quality compounds as
sessions write `lessons:` lines.

lessons:
- "job-doc lesson fields are prose paragraphs — split on sentence and GOTCHA:/NOTE:/WARNING: boundaries and keep only signal-word lines, or the primer cap fills with narrative"
- "card specs are keyword-dense (scripts/docs/kanban match everything) — MIN_SCORE=2 distinct keyword hits is the noise floor for primer relevance"
- "test_merge_sweep fixture relied on global git identity — tony-dell has none (repo-local only); tmp-repo fixtures must set user.name/user.email locally or the merge test-gate goes red"
- "a card's own comms get harvested with [card-id] prefix — self-match is a feature: retries see their own failure trail in KNOWN_PITFALLS too"
