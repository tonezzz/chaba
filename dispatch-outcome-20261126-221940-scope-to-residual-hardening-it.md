# Dispatch outcome — idc03 writer hardening: index.lock stale recovery

Card: `idc03-writer-hardening-index-lock-race-l-f77129` (residual
hardening item 1 only; `.local-conflict` debris cleanup untouched —
separate card).

## What changed

`scripts/board/kanban-commit.sh` — when `.git/index.lock` exists the
sweep now recovers from a stale lock instead of stalling:

- **Stale criteria** (either one): a holder pid that is dead, OR lock
  mtime older than **N = 900 s (15 min)**, env-overridable via
  `KANBAN_INDEX_LOCK_STALE_S`. 15 min is far longer than any legit
  index write (milliseconds) yet short enough to self-heal a crash
  within one or two 15-min ticks.
- **Holder pid detection**: git 2.53 leaves `index.lock` EMPTY (0
  bytes — verified empirically), so "holder pid" covers (a) a bare-pid
  first line when some writer records one, and (b) `fuser`-visible
  processes holding the file open (psmisc; absent → age decides).
  Liveness via `/proc/<pid>` existence with `kill -0` fallback (the
  `/proc` check also survives EPERM on foreign-uids).
- **Recovery**: `recover_stale_index_lock()` removes the lock at most
  once per tick (`INDEX_LOCK_RECOVERED` flag — a pathological recreate
  can't spin). It runs proactively before the `git add` loop (whose
  failures are swallowed by `|| true` — the silent-stall path) and on
  every `index.lock` error inside `git_lock_retry`, so both `git add`
  and `git commit` self-heal.
- **Live-lock no-op behavior**: a fresh lock with a live holder is left
  alone — `git_lock_retry`'s existing ~17 s backoff still applies, adds
  fail, nothing stages, the tick exits 0 and defers the commit to the
  next cycle. A fresh lock with NO identifiable holder also gets the
  benefit of the doubt until it ages past N (pinned by test).

`tests/board/test_kanban_commit_index_lock.py` — new pytest e2e file
(same scratch-repo pattern as `test_kanban_commit_guard.py`), 4 cases:
stale-age, stale-dead-pid (fresh mtime still removed), live-lock
(fuser-held, left alone, no commit), fresh-lock-no-holder (left alone).

## Verification

- `python3 -m pytest tests/board/test_kanban_commit_index_lock.py -x -q`
  → **4 passed in 40.57s** (live-lock cases burn the retry backoff).
- `python3 -m pytest tests/board/test_kanban_commit_guard.py -x -q`
  → 5 passed (no regression).
- Chaba merge gate (`REPO_TESTS["chaba"]` 14-file set, `-x -q`)
  → **300 passed in 58.78s** — gate green.
- `bash -n scripts/board/kanban-commit.sh` clean.

## How to verify after merge

- `python3 -m pytest tests/board/test_kanban_commit_index_lock.py -q`
- On idc03: `touch -d '1 hour ago' ~/CascadeProjects/chaba-tony-dell/.git/index.lock`
  then run `scripts/board/kanban-commit.sh` — journal shows
  `cleared stale index.lock` and the tick commits normally.

lessons:
- git's index.lock is EMPTY on git 2.53 — no pid is recorded; "holder
  pid" detection needs fuser (or a pid-token fallback for foreign
  writers), with mtime age as the primary stale criterion.
- kanban-commit's `git add` loop swallows failures (`|| true`), so a
  permanently stale index.lock stalled the sweep SILENTLY (exit 0,
  nothing committed) — failure-path-only recovery would not have been
  enough; the proactive pre-add check is what closes the stall.
- Live-lock e2e tests are slow by design: git_lock_retry's 8-attempt
  backoff is ~17s per `git add` call; keep fixture generated-dirs
  minimal to halve it.
- Pytest scratch-repo fixtures must `.gitkeep` every dir a test writes
  into — git doesn't track empty dirs, so the clone lacks `cards/`.
