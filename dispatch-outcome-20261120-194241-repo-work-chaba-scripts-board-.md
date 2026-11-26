# dispatch-outcome — board-api /card-set routing-field door

card: `board-api-card-lane-executor-edit` (attempt 2; attempt 1 died on a
provider rate-limit, not a code bug — prior worktree on idc02 was dirty
and its work was lost).

## What changed (branch `dispatch/20261120-194241-repo-work-chaba-scripts-board-`, commit 5b50f56ce3, rebased on origin/master)

- `scripts/board/board-api.py`
  - New `POST /card-set {id, set:{lane?, executor?, tags?}, from, reason}`
    — whitelisted routing-field edit on an EXISTING card, under the same
    card flock as every other write (no network/git inside it).
  - `lane` must be in `valid_lanes()` = `dr.LANE_MODELS ∪
    dr.LANE_EXECUTORS` minus lanes `ssot.devnest-lanes.yml` marks
    removed/retired (new `_retired_lanes()` mirrors the
    RETIRE_RE semantics of `tests/board/test_runner_tooling_contract.py`,
    yaml first, line-scan fallback). `executor` must be in
    `dr.EXECUTORS`. Empty string clears the field. `devin` is still NOT a
    lane — `executor=devin` is the pin (documented, not widened).
  - `tags`: list form replaces (≤20, each ≤40 chars — refuses, not
    truncates) or `{add:[], remove:[]}` merges into existing.
  - An explicit lane set pops `lane_source` → author-set, wins over
    `_apply_classify_at_queue` on the next queue.
  - Refused (400) while `action.status` is running/claimed/starting or a
    `runner` holds the claim. `reason` required; appends comms line
    `routing edited: <fields> by <from>: <reason>` for audit.
  - `/card` lane validation now uses the same `valid_lanes()` helper —
    one definition of the admitted-lane set.
  - Selftest block covers: set lane (+lane_source drop), set executor,
    tags add/remove and replace, lane/executor clear, refusal when
    running, refusal when claimed (runner set, status queued), invalid
    lane (`jules`, `devin`), invalid executor, workflow-field refusal
    (`column`), missing reason/set, bad tags shapes, and the comms audit
    line.
- `scripts/board/board-cli.py` — `card-set` subcommand:
  `card-set CARD --reason "why" [--lane L|''] [--executor E|'']
  [--tags a,b | --tag-add a --tag-remove b]` (client-side refuses an
  empty set; usage line updated).
- `docs/kb/board-api-write-door.md` — endpoint table row + an endpoint
  note covering the whitelist, the `devin`-is-an-executor rule, clear
  semantics, audit line, and the run/claim refusal.

## Result / verify

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`
  (the `No module named 'lib'` stderr line is pre-existing on
  origin/master, verified by running selftest on the pre-change file).
- `python3 -m unittest tests.board.test_runner_tooling_contract` → 7/7
  OK (rebased onto the lane-retirement-guard commit).
- `py_compile` clean on both touched scripts; `board-cli.py card-set
  --help` renders; empty-set call refused client-side.
- NOT deployed: idc03 chaba-board-api untouched, no restart — promotion
  needs Tony's explicit approval. The new endpoint is dead code until
  then; old endpoints are behavior-identical (only shared helper added).

## where_filed

- code diff → commit 5b50f56ce3 on dispatch branch (local only, not pushed)
- runbook row/note → docs/kb/board-api-write-door.md (same commit)
- progress + outcome → card comms via board-api /comment
- this note → repo root, per dispatch rails

## next_action

Tony reviews the branch; if approved, merge + deploy to idc03's served
checkout and restart chaba-board-api (normal promotion path).

lessons:
- attempt-1 failure was a provider rate-limit mid-run, not a code bug — check card comms/result signature before assuming the diff approach failed.
- origin/master landed a lane-retirement contract test (test_runner_tooling_contract.py) mid-session: rebase onto origin/master before finishing or you miss new gates that judge your diff.
- ssot.devnest-lanes.yml was invalid YAML (unquoted colon in jules status) until upstream commit 18597619d1 fixed it — /card-set's retired-lane read does yaml-load with a line-scan fallback and shares the contract test's RETIRE_RE.
- 'devin' is deliberately not an action.lane at /card; executor=devin is the pin — do_card_set's error message says so to steer callers.
