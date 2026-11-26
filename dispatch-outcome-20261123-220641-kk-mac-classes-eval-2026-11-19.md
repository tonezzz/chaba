# dispatch-outcome — kk-mac-admitted-classes-narrow (attempt 2)

## What happened

Attempt 1 (21:18, tony-omen) had already completed this exact change set —
its session was killed by a provider rate-limit AFTER the work was done but
BEFORE merge, and the session-end hook auto-committed the checkpoints onto
`dispatch/20261123-211800-kk-mac-classes-eval-2026-11-19`. This attempt
recovered that work, reviewed it line-by-line against the live tree, fixed
one real bug in it, added the missing deliverable (follow-up card + job
trail doc), verified, and committed.

## What changed (commit 07df45f3ed, 18 files)

kk_mac_local lane admission narrowed to `{summary, structured_extract}`
at every declaration site:

- `scripts/devnest/kk_mac_llm.py` `ALLOWED_TASKS` (root; executor
  TASK_CLASSES, lane_worker claim check, CLI choices all derive)
- `scripts/devnest/kk_mac_capacity_producer.py` `TASK_CLASSES`
- `scripts/devnest/kk_mac_plan_validator.py` `ALLOWED`
- `scripts/devnest/devnest_capacity_broker.py` `KK_CLASSES`
- `scripts/board/dispatch_repos.py` `KK_MAC_TASK_CLASSES` +
  `KK_MAC_ROUTE_KW` (held-class keywords removed; inferred classes
  re-checked against the admitted set)
- `scripts/board/runner-agent.py` `KK_MAC_TASK_CLASSES` (single-file mirror)
- Lane contract + docs: `ssot.devnest-lanes.yml`, `ssot.procedures.yml`,
  `docs/kb/devnest-capacity-aware-dispatch-procedure.md`,
  `docs/kb/jevnest-kk-mac-capacity-procedure.md`
- `scripts/bench/kkmac-classes/score.py` — corpus sanity now gates on
  verifier-supported classes (`JSON_CLASSES | summary`) instead of the
  live admission set, so held classes keep being scored for re-eval;
  report rows for non-admitted classes are flagged `(HELD — not admitted)`
- Held classes stay verifier-supported (`kk_mac_executor.verify` /
  `JSON_CLASSES` unchanged) — re-eval path preserved.
- New fail-closed tests: board-api rejects held classes (pinned + bare
  hint), lane_worker never claims them, producer quarantines held-class
  inbox specs, executor `run_contract` returns `class_not_admitted`.
- Job trail: `docs/ssot/jobs/devnest/2026-11-23-kkmac-admitted-classes-narrow.yml`

## Fixes made on top of the recovered diff

- `tests/board/test_executor_contract.py::test_kk_mac_rejects_held_classes`
  used card ids `c-bad-operator_brief`/`c-bad-safe_route` — underscores
  violate the `[a-z0-9-]` id rule, so the test failed on id validation
  before reaching the class check. Renamed to `opbrief`/`saferoute`.
- `score.py` HELD flag added (recovered diff scored held classes but did
  not mark them in reports — a future "READY" row could be misread as
  admitted).
- Excluded the prior checkpoint's unrelated swept-in file
  (`ssot.dev-system.assessment.yml` — automated assessment regen churn).

## Follow-up filed

`kk-mac-held-classes-fix-operator-brief-f-dd32ac` (OPS-0048, queued,
executor=devin, repo=chaba): fix operator_brief `expect.facts` echo
format in the bench corpus + producer guidance, re-bench safe_route with
a safer model (respecting the lane memory floor; route whitelist / class
rethink as fallback), then readmit passing classes through the same
mirror checklist.

## Verification

- `pytest tests/devnest` — 317 passed
- `pytest tests/board/test_executor_contract.py` KkMac classes — 27 passed
- `pytest tests/board/test_queue_time_classify.py` + board-api mutation
  tests — pass
- `score.py --entity mock-oracle` — 51/51 corpus selftest passes; held
  classes flagged HELD
- `node scripts/ssot-validate-all.mjs` — 5772 files, 0 errors
- Pre-commit fast gate + SSOT validation passed on commit

## How to verify after merge

- `python3 -c "from scripts.devnest import kk_mac_llm; print(sorted(kk_mac_llm.ALLOWED_TASKS))"` → `[summary, structured_extract]`
- `grep -n "KK_MAC_TASK_CLASSES" scripts/board/dispatch_repos.py scripts/board/runner-agent.py` → both `{summary, structured_extract}`
- A card pinned `executor=kk_mac_local, task_class=operator_brief` is rejected by board-api `/card`.

lessons:
- A dispatch "failed (exit=1)" can still contain complete, committable work — always check `git branch -a` for the prior attempt's `dispatch/<ts>-*` branch and its checkpoint commits before redoing the task.
- Session-end auto-checkpoints save unmerged work but the card still records failure; recovering via `git checkout <old-branch> -- <paths>` beats rewriting.
- Test card ids must match `[a-z0-9-]` — underscores in f-string ids fail validation before the assertion under test runs.
- Auto-checkpoint commits can sweep in unrelated dirty files (e.g. ssot.dev-system.assessment.yml regen churn) — audit the file list before reusing.
- bench score.py corpus validation must gate on verifier-supported classes, not live admission, or held classes can't be re-benchmarked.
