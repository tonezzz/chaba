# dispatch-outcome — board-api-queue-write-verify-lost-race-f85f2f

Two dispatch-pipeline robustness fixes from the 2026-11-18/19 lessons:
silent `/action` write loss to the git-safe-pull autostash race, and
merge test-gate timeouts treated as test failures on docs-only diffs.

## What changed

### 1. `/action` verify-or-loud — `scripts/board/board-api.py`

`POST /action do:queue|retry|close|hold` no longer answers on
write-and-hope. After the card flock releases, the handler:

1. nudges + bounded-flushes the post-lock commit worker
   (`commit_pending_flush`, `BOARD_API_ACTION_VERIFY_S`, default 8s);
2. re-reads the card file and compares `_action_fp()` — a fingerprint
   of the fields the verb mutates (`column`, `awaiting_action`, the
   whole `action` dict, `claim.session`; comms/requests/updated
   excluded so concurrent legit writers don't false-positive);
3. `fp == after` + `git status --porcelain` clean on the card path →
   committed and un-losable → `200 {"verified": true}`;
4. `fp == before` → the write was reverted (autostash pop or
   equivalent) → `_reapply_action()` re-applies the verb once under
   the flock (refuses to stomp: only mutates when disk still shows the
   pre-write fingerprint) and re-verifies — response notes
   `write re-applied after pull race`;
5. anything else (still dirty, a concurrent writer's third state,
   failed re-read, exhausted re-apply) → `503 {"verified": false,
   "retry_after_s": 5}` — loud, and `queue`/`retry` are idempotent so
   a retry converges (`already queued` verifies trivially).

`claim`/`move`/`finish`/`archive`/`unarchive` are unchanged (runner
paths with their own idempotency; archive moves the file). Escape:
`BOARD_API_ACTION_VERIFY_S=0` restores fire-and-forget.
`BOARD_API_ACTION_VERIFY_LOCK_S` (default 10s) bounds the re-apply
flock wait. Runbook note added to `docs/kb/board-api-write-door.md`.

### 2. Git-side backstop — `scripts/git-safe-pull.sh`

`_resolve_autostash_pop()` now preserves the stash side (stage 3 —
verified empirically to be the autostash copy of the dirty write) of
card-YAML pop conflicts as `<card>.local-conflict-<ts>` BEFORE
resolving upstream-wins, so the EXIT-trap
`reconcile-local-conflicts.py` folds the raced write back semantically
(comms union, action per-key newer-wins). Covers the cases the
card-union merge driver can't: modify/delete conflicts (upstream
archived/deleted the card mid-write) and driver failures on
non-mapping YAML. Modify/modify card conflicts still union-merge
inline via the driver (verified: "Applied autostash", zero unmerged,
both comms + newer-wins action landed).

### 3. Test gate: timeout is flake, not verdict — `scripts/board/dispatch_repos.py`

- `run_test_gate()` retries a timed-out suite once
  (`KANBAN_TESTGATE_TIMEOUT_RETRIES`, default 1); an exhausted timeout
  returns `timeout: true` + `attempts: n` so callers can distinguish
  flake from a red suite.
- `baseline_aware_test_gate()` returns early on timeout — a suite that
  can't finish can't enumerate a failure set; the baseline compare
  would just burn another full timeout.
- `_merge_and_gate()`: on `timeout:true`, `_docs_only_paths()` checks
  `git diff --name-only <base> HEAD` — every path matching
  `^(docs/|stacks/)|\.md$` (unreadable/empty diff is NOT docs-only)
  flips the result to `ok:true, timeout_override:true`. Assertion
  failures still hold regardless of paths.
- `close_out_notes()` reports `test gate timed out — docs-only diff
  merged anyway (gate: timeout-override)` so the merge is flagged, not
  silent.

## Tests

- `tests/test-kanban-commit.sh` — new section L (13 checks): L1
  modify/modify pop conflict union-merges the raced write inline; L2
  modify/delete pop conflict preserves stage 3 as `.local-conflict-*`
  with the raced content while upstream's deletion wins; L3
  reconcile folds a preserved sidecar back into the canonical card
  (queued status + unioned comms) and keeps an orphan sidecar for
  review. Also fixed a pre-existing fixture gap: `alert_card` in
  kanban-commit.sh imports `card_io` from the checkout's
  `scripts/board/` — the fixture now provides it (sections F/J
  'alert card filed' checks were failing on base too).
- `tests/board/test_dispatch_close_out.py` — 4 new tests: retry-then-
  pass merges, docs-only timeout merges flagged, mixed docs+code diff
  still holds, `_docs_only_paths` unit coverage; existing timeout test
  now asserts `attempts==2`/`timeout:true`.
- `tests/board/test_board_api_action_persistence.py` — 4 new tests:
  verified response on queue, re-apply after simulated lost write,
  no-stomp + failure on concurrent third state, 503 mapping on verify
  failure. setUp patches `BOARD_CLASSIFY_AT_QUEUE` and
  `queue_unclaimable_warn` for determinism.

## Verification

- `pytest tests/board/test_board_api_action_persistence.py` — 7 pass
- `pytest tests/board/test_dispatch_close_out.py` — 48 pass
- full chaba merge-gate smoke set (the exact `REPO_TESTS["chaba"]`
  command) — **240 pass**
- `bash tests/test-kanban-commit.sh` — **79 pass, 0 fail**
- `board-api.py --selftest`, `reconcile-local-conflicts.py --selftest`,
  `merge-card-yaml.py --selftest` — all OK
- manual git experiments confirmed: autostash engages with zero local
  commits; stage 3 = stash side for both modify/delete (`DU`, stages
  1+3 only) and modify/modify pop conflicts.

Done conditions: queue writes are verified-or-loud (200 verified /
re-applied / 503), and a docs-only dispatch branch lands flagged
`gate: timeout-override` when the suite times out — no human merge
needed for the OPS-0200/ADA-0201/KNB-0212 case.

lessons:
- autostash pop conflicts stage the stash side as stage 3 (`git show :3:<path>` recovers the raced write; stage 2 is HEAD/ours); the card-union merge driver DOES run during stash pops — modify/modify resolves inline with zero unmerged entries, so `.local-conflict-*` preservation only matters for modify/delete and driver failures.
- `subprocess.run(timeout=N)` kills only the direct child — a `sleep` grandchild keeps the stdout pipe open and stretches the effective timeout to the sleeper's lifetime; gate test commands should `exec sleep` so the kill lands.
- `git pull --rebase --autostash` engages autostash even with zero local commits (fast-forward + pop) — dirty-tree pull races reproduce without needing local commits.
- test-kanban-commit.sh fixture checkouts have no scripts/ — kanban-commit's alert_card `import card_io` dies on ImportError unless the fixture copies scripts/board/card_io.py in (pre-existing F/J failures).
- board-api's commit worker defers while the card flock is held — `commit_pending_flush` must run after `lf.close()`, never inside the locked region, or the flush can only time out.
