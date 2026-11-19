# dispatch-outcome: board-api-residual-lock-holds

## What changed

`scripts/board/board-api.py` — follow-up to f1f0b (post-lock commit
worker), fixing the retry-storm and adding in-flock observability:

- **A — verify by repo state (`_rels_dirty` + `_commit_paths`).**
  `git status --porcelain -- <rels>` is now the batch's truth source.
  `git commit -- <rels>` rc=1s whenever the queued paths are already
  clean while OTHER files are dirty — the served checkout always is
  (~9-10 commits ahead of origin plus unrelated dirty/untracked
  files), and the error text is "Changes not staged for commit", not
  the literal "nothing to commit" the code screened for. So every
  batch the kanban-commit sweep beat to the punch requeued every
  COMMIT_RETRY_S (5s) and logged `board-api commit skipped` until
  COMMIT_MAX_TRIES. Now: after `git add`, a provably-clean batch
  returns done WITHOUT attempting the commit; on add/commit transient
  failure the batch ends only when paths are provably clean, else it
  requeues exactly as before. Lock-held deferral, the rebase/merge
  gitdir guard, per-path add fallback, COMMIT_MAX_TRIES aging, and
  BOARD_API_COMMIT=0 are all unchanged.
- **B — in-flock phase timing.** `load()`, `save()`, `card_path()`
  accumulate milliseconds into a thread-local armed by do_POST while
  it owns the card flock; `mutate_ms` is the hold remainder (do_*
  helpers, delivery queueing, validation). The existing slow-lock
  journal line (wait_s or hold_s >= BOARD_API_LOCK_SLOW_S) now prints
  `load_ms= mutate_ms= save_ms= card_path_ms=`, so the next residual
  hold names its phase instead of needing a new investigation.
  Off-request callers (selftest, _append_comms_note, post-write
  worker) pay one getattr and record nothing.
- **C — soak comm.** The post-f1f0b /lock-stats + journal evidence was
  posted to `board-api-lock-contention` (landed on retry — the live
  board 503'd twice during posting, itself a symptom of the residual
  holds).
- Selftest extended: sweep-race case — a queued path committed
  externally while the card flock is held must finish the batch with
  HEAD still the sweep commit and unrelated dirt untouched.
- SSOT trail: `docs/ssot/jobs/infrastructure/2026-11-19-board-api-residual-lock-holds.yml`.

Commit on the dispatch branch: `ceddecb0bb`. Not pushed, not deployed.

## Result / verification

- `python3 scripts/board/board-api.py --selftest` → ok (includes new
  sweep-race coverage).
- `python3 -m unittest tests.board.test_board_api_reads
  tests.board.test_board_api_mutations
  tests.board.test_board_api_action_persistence` → 58 tests OK.
- Sandboxed HTTP smoke (throwaway repo with permanent unrelated dirt,
  /tmp/bapi_smoke.py): (1) normal /comment still commits promptly;
  (2) externally committed queued path → batch ends silently — zero
  `commit skipped` lines, no spurious commit, unrelated dirt
  untouched; (3) slow-lock lines carry all four phase fields, sum
  <= hold.
- Live symptom reproduced in-session: two `board write lock
  saturated` 503s while posting the soak comm at ~12:5x ICT —
  residual holds are real and ongoing; the phase fields will identify
  the phase on the next occurrence.

## Still needed (outside this dispatch)

- Merge to master + restart `chaba-board-api` on idc03 (normal service
  restart path), then verify `/lock-stats` resets and hold_s_max <5s
  for /comment /action /card /inbox with zero `lock wait >25s` 503s
  over 24h. The first new slow-lock line should name the residual
  phase (suspects per the card: save_ms for atomic fsync on a slow
  disk, mutate_ms for do_* helper/subprocess work, load_ms for a
  large card YAML, card_path_ms for the id-drift glob scan).

lessons:
- "git commit -- <pathspec>" rc=1 output over already-clean paths is
  "Changes not staged for commit" (the other dirty files), not
  "nothing to commit" — verify done-ness with `git status --porcelain
  -- <paths>`, never by matching commit output text.
- Truth-check polarity matters: on failure paths, "batch done" must
  require provably-clean (False), not "not provably clean" — an
  inconclusive status check must keep the retry or dirty writes drop
  to the sweep.
- docs/ssot/jobs/*.yml IS yaml-validated by the pre-commit gate and
  requires a `title:` field; a `- word: rest` item parses as a nested
  mapping, and items starting with a backtick/colon need quoting —
  the merged 2026-11-19-board-api-commit-outside-lock.yml is
  currently invalid YAML and worth a fix-up commit.
- Live board-api still 503s on /comment under residual holds — post
  card comms with a retry loop, the dedupe window makes repeats safe.
