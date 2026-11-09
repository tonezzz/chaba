# Dispatch outcome — positive-signal-primer (KNOWN_GOOD channel)

Card: `positive-signal-primer` · runner: tony-omen · 2026-11-09

## What changed

`scripts/board/lesson_primer.py`

- `_positive_candidates(root)` — harvests one distilled line per
  `docs/ssot/kanban/cards/*.yml` with `action.verified == true` and
  `attempts <= 1` (absent = 0): the first substantive (>=30 chars)
  comms/`action.outcome`/`action.result`/`outcome` line carrying a
  success signal (`worked|clean|merged|verified|passed first|first
  try`, word-bounded so `unmerged`/`unverified` don't count), falling
  back to the card's own spec-summary first line when comms have no
  signal. Lines render as `[<card-id>] <what worked>` (clipped at
  `LINE_CAP=240`). Process-noise comms (queued/dispatched/merge-sweep/
  auto-merged/push-fatal/worktree-kept…) are filtered by
  `GOOD_NOISE_RE`. Plus `_good_job_candidates`: `wins`/`worked`/
  `success_patterns`/`what_worked` fields (key walk, any depth) in
  `docs/ssot/jobs/**/*.yml`.
- `build_good(card, host, repo, root)` — top `GOOD_MAX_LINES=4` lines
  within `GOOD_MAX_CHARS=1200`, sharing the new `_select()` helper
  with `build()`: same `keywords()`/`_score`/`MIN_SCORE` eligibility,
  dedupe, and rank ordering. The scoring-fixes card edits `_select`
  once and both channels inherit it — no hard dependency on its new
  signature.
- `format_good_block(lines)` — emits `---\nKNOWN_GOOD — approaches
  that verified clean on similar work:` + bullet lines; visually
  distinct, always rendered after KNOWN_PITFALLS.
- Robustness fixes landed along the way: `_comms_candidates` and
  `_card_good_line` now skip non-dict comms entries (a real card had a
  bare-string comm that crashed `lp.build` — warn-only, but it silently
  produced zero pitfalls), and all four candidate loops skip non-dict
  YAML docs.

`scripts/board/kanban-dispatch.py` (`build_task` + `start_pending`)

- `LAST_GOOD_LINES` tracks injected good lines alongside
  `LAST_PRIMER_LINES`.
- `build_task` appends the KNOWN_GOOD block after KNOWN_PITFALLS when
  non-empty; `KANBAN_PRIMER_GOOD=0` disables; wrapped in the same
  warn-only fail-open try/except as the pitfalls path.
- The `primer injected` card comms entry now appends ` | good: <lines>`
  (80-char-per-line preview, comms_add caps at 500 chars).

`tests/board/test_lesson_primer.py`

- `_mkroot_good` fixture: eligible verified card, spec-fallback card,
  excluded retry card (attempts=3), excluded unverified card, job doc
  with a `wins:` field.
- `GoodPrimerTest`: harvest eligibility/content (incl. noise and
  exclusions), `build_good` scoring + caps, `format_good_block`.
- `BuildTaskGoodTest`: KNOWN_GOOD lands after KNOWN_PITFALLS and is
  absent under `KANBAN_PRIMER_GOOD=0` (lp.* stubbed — no real scan).

## Verify

- `python3 -m pytest tests/board/` — 474 passed (full suite, 20 min),
  plus re-runs on final code: test_lesson_primer +
  test_kanban_dispatch_rails 11 passed; test_executor_contract +
  test_queue_starvation + test_dispatch_close_out 121 passed.
- Live smoke: real `kd.build_task()` on card
  `voice-dub-recipe-lan-url` → `KNOWN_GOOD` block with 4 lines
  (`[vcast-auto-displays]`, `[boards-public-origin-502]`,
  `[nest-io-fabric]`, `[nest-lane-metrics]`) after 8 KNOWN_PITFALLS
  lines. `_positive_candidates` yields 135 lines on the real board
  (~32s scan, same order as the existing comms harvest).

## Notes

- The good channel roughly doubles primer scan cost per `build_task`
  (~30s → ~60s on this board) since it re-reads all card YAMLs. A
  shared card-doc cache could halve it later; kept independent now to
  stay composable.
- Line quality is heuristic — spec-summary fallbacks describe what the
  card asked for (which is what verified clean), comms lines describe
  the approach where a signal-bearing one exists.

lessons:
- kanban comms entries are not guaranteed dict-shaped — a bare-string
  comm crashed lp.build via `'str'.get`; guard isinstance before .get
  anywhere comms are walked.
- signal regexes need word boundaries: `merged` substring-matches
  `unmerged`, and `verified` matches inside `unverified`.
- card specs can contain the literal block header string (this card's
  spec literally names KNOWN_GOOD) — when smoke-testing injected
  blocks, grep for `\n---\nKNOWN_GOOD` or check LAST_GOOD_LINES, not
  the bare phrase.
