# Dispatch outcome — board-api-date-serialization-outage

Card: `board-api-date-serialization-outage` (hygiene follow-up to the
2026-11-09 board-api /cards 502; reader side fixed at ca8d850275).

## What changed

- `scripts/board/card_io.py` — new `json_safe(obj)`: recursive in-place
  rewrite of `datetime.datetime`/`datetime.date` to `.isoformat()`
  strings (tuples -> lists, dict keys untouched). Wired into
  `atomic_dump_card()`, which every parse-dump card writer already
  funnels through (merge-sweep, kanban-commit, answer-sweep,
  request-sweep, runner-fleet-health, deploy-preflight,
  board-render-guard, reconcile-local-conflicts, ref-backfill,
  lab-review-sweep, review-digest, audit-hosts, card-pipeline FileSink,
  ada/* health watchers).
- `scripts/board/board-api.py` — `save()` calls
  `card_io.json_safe(card)` before `yaml.dump`, covering the HTTP write
  door (/card /comment /action /move /respond /request ...).
- `tests/board/test_card_date_serialization.py` (new) — regression:
  writes a card carrying bare `created:`/`updated:`/`comms[].at` date
  scalars through BOTH doors and asserts the persisted YAML re-parses
  those fields as `str` and survives plain `json.dumps`; also covers
  nested `datetime` objects.
- `evals/shadow/fixtures/mcp-safety/task.yaml` — drive-by gate fix:
  unquoted `classification one of: ...` and quote-then-plain rule
  strings made the fixture unparseable (ci-qa yaml-parse was red on
  master since 0c7e3c1b3a).
- `docs/ssot/jobs/board/2026-11-26-card-yaml-date-scalar-normalization.yml`
  — trail doc (fields normalized, verification, residual).

## Fields normalized

Any `datetime.date`/`datetime.datetime` anywhere in the card structure
at write time — concretely `created` (bare date-only scalars, the ~16
cards flagged in triage) plus any nested `at:`/`updated:`-shaped
scalars that load as date/datetime. Plain strings are never touched;
the common `updated: YYYY-MM-DD HH:MM` form (no seconds — not a YAML
timestamp) already dumps as an unquoted str, so steady-state card diffs
stay minimal: only genuinely hazardous scalars get quoted on rewrite.
Existing on-disk bare scalars are NOT bulk-rewritten (Tony's triage —
the 2026-11-21 bulk rewrite re-stamped every card and stalled the
KNB-1178 archive timer for days); each card's next write through either
door quotes its own date scalars.

## Verification

- `pytest tests/board/test_card_date_serialization.py
  tests/board/test_card_io_atomic.py -q` -> 11 passed.
- chaba merge-critical gate (the `REPO_TESTS["chaba"]` 14-file set,
  `-x -q`) -> **300 passed in 57.69s** — gate green.
- `scripts/ci-qa.sh` -> 5/5 (was 4/5 on master before the fixture fix).
- `scripts/ci-standard.sh` -> 5/6; the jobs-manifest-render FAIL is
  pre-existing generated/ drift (con01 cline units vs tony_dell
  ansible-runner-tool-guard), unrelated.
- Full `tests/board` sweep: 1084 passed, 2 failed —
  `test_control_pane_projection` needs git-ignored generated
  `stacks/web/public/apps/board2/{index.html,cards.json}`; fails in any
  fresh worktree, unrelated.

## How to verify after merge

- `python3 -m pytest tests/board/test_card_date_serialization.py -q`
- Next card write through board-api or any sweep: `grep -n "created:"
  docs/ssot/kanban/cards/<that-card>.yml` shows a quoted scalar.

lessons:
- "chaba gate" for dispatch merges is the fixed 14-file pytest set in
  `dispatch_repos.REPO_TESTS["chaba"]` (~300 tests, 240s timeout) — NOT
  ci-all.sh; run that exact command to prove gate-green.
- PyYAML timestamp resolution needs seconds: `YYYY-MM-DD HH:MM` is a
  str, `YYYY-MM-DD` and `...T/space HH:MM:SS` become date/datetime —
  only the latter two are json.dumps hazards.
- SafeDumper auto-quotes strings that would re-resolve as timestamps,
  so normalizing date objects to str at write time yields quoted YAML
  with zero diff churn for already-safe scalars.
- ci-qa yaml-parse scans ALL tracked *.yml including evals/ fixtures —
  a broken fixture anywhere reds the gate; check `git status` on the
  failing file before assuming your diff caused it.
- jobs/*.yml trail docs are strict YAML too: `word: explanation` inside
  a plain list scalar breaks parsing — use `>-` folded items.
