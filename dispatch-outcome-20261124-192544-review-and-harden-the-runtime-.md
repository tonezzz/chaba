# Dispatch outcome — nest-job-done-evidence-gate (OPS-0923), attempt 2

Review and harden the runtime job status contract after the OPS-0922
lifecycle SOP. Read-only reconciliation only — no auto-cancel, no claim
clears, no deploy, no production status mutation.

## Prior-attempt recovery

Attempt 1 (idc02, `dispatch/20261124-165943-…`) completed the bulk of
the work but merge-sweep could not land it: conflict in
`docs/kb/board-api-write-door.md`. Tony answered the merge-conflict
request: "resolve — let devin resolve the conflict and land it ★".

This session cherry-picked both attempt-1 commits onto current
`origin/master` (`a6c1b4ff9e`), resolved the conflict (kept master's
newer `queue-mgr.timer` wording, appended the OPS-0923 contract
paragraph), and re-verified. Attempt-1 content:

- `do_job` enforces `JOB_TRANSITIONS` (terminal `done`/`cancelled`
  exit only via `queued`/`failed`) and a terminal-done gate:
  `status=done` requires `result_ref` + verified artifact evidence
  (`evidence[]`, `verified:true`, `artifact_verified`, or
  `confidence=verified`) → HTTP 400 before any WP write.
- `_pub_job_send` fires only for explicit `job` refs (card/project
  events no longer mint `nest_job` posts — fixes the silent-completion
  bug where every runner-lifecycle milestone fell back through
  `card`/`project` and implied `done`); `milestone` no longer maps to
  `done`; contract rejections surface as `skipped` receipts.
- New `GET /nest-jobs` read endpoint + `scripts/ops/nest-job-reconcile.py`
  (read-only cross-check of WP mirror vs pack markers vs packs-index
  vs queue/lease; never mutates).
- Tests + docs (`job-package-status-sop.md` §5, `colab-mcp-jobs.md`
  lifecycle/storage map, write-door contract, SSOT trail).

## Attempt-2 hardening (new commit `151afa2de9`)

Review found two real gaps the attempt-1 gate missed:

1. **`meta.status` bypass** — `do_job` gated only the top-level
   `status` field, but `meta.status` rides the same `JOB_META_KEYS`
   merge ungated. `{"slug","meta":{"status":"done","result_ref":"x"}}`
   wrote `done` with no transition check and no evidence check
   (reproduced live before fixing). Fix: `meta.status` is folded into
   the gated `status` before validation; a top-level/meta disagreement
   is a 400; bogus values in `meta.status` hit the same enum check.
2. **queue-mgr deploy-blocker** — `scripts/ops/queue-mgr.py` (the only
   `POST /job` producer in the repo; runs from the tony-dell exec
   checkout synced hourly) sent `result_ref` but no `evidence` on done
   writes — every pack completion would 400 once the gate deployed.
   `derive()` now emits `evidence[]` = the done marker for pack/env/
   work children, and aggregates up to 10 child done markers (queue
   dir fallback) for the derived root `done`.

Also corrected the SSOT trail: attempt 1 claimed queue-mgr was "not in
this repo" — it is (`scripts/ops/queue-mgr.py`), which is why the
evidence fix lands on the same merge.

## Verification

- `python3 -m unittest tests.board.test_board_api_mutations
  tests.board.test_publication tests.ops.test_nest_job_reconcile
  tests.ops.test_queue_mgr` — 157 tests, OK (incl. new meta.status
  bypass/conflict tests and queue-mgr done-evidence test).
- `python3 scripts/board/board-api.py --selftest` — ok.
- `nest-job-reconcile.py --jobs-file … --no-drive` smoke run —
  correctly flags DONE-NO-RESULT-REF (error) + missing pack markers.
- Full `tests/board` discovery: 950 tests, 7 failures/errors — all
  environmental (pytest/numpy not installed on this host), unrelated.
  `tests/ops` discovery: same class of pre-existing env failures
  (numpy/pytest imports, one render-jobs manifest drift).
- Producer audit: runner-agent/waiting_cards/unattended-report all
  publish card/project-scoped events → now correctly skip the job
  sink; queue-mgr is the sole `/job` writer and now satisfies the gate.

## Landing state

Branch `dispatch/20261124-192544-review-and-harden-the-runtime-`
carries: cherry-picked attempt-1 commits (`6c1edf5dc8`, `240b9307b0`)
+ hardening commit `151afa2de9`, based on current master — the
board-api-write-door.md conflict is resolved, so merge-sweep should
land cleanly. Repo landing only; board-api deploy is a separate gate.
Deploy-order note: if board-api deploys before tony-dell's
chaba-repo-sync picks up queue-mgr, bare done writes 400 and retry
each tick — self-healing once synced.

lessons:
- do_job gates must normalize EVERY carrier of a gated field — meta.* keys that ride JOB_META_KEYS (status, result_ref) can bypass top-level-only validation; fold-then-gate, and reject conflicting duplicates.
- Before landing a write-door contract change, audit ALL producers of that door in-repo (queue-mgr was the only POST /job caller and would have 400'd every done write on deploy).
- merge-sweep conflicts on docs files are cheap to fix by cherry-picking the orphaned dispatch branch onto fresh master — check `git ls-remote origin` for the prior attempt's branch first.
- unittest discover over tests/board takes ~9.5 min; the focused per-file runs are the practical gate on dispatch hosts without pytest.
