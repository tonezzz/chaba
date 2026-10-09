# ci-test-gate — outcome

Wired a pytest gate into the dispatch close-out merge path and the served-checkout
pre-commit hook. A dispatch branch whose merged tree breaks the suite no longer
auto-merges — it requeues with the failing test names in `action.last_failure`.

## What changed

- `scripts/board/dispatch_repos.py` — new `REPO_TESTS` per-repo table
  ({command, timeout}; `command: null` opts out), `test_gate_config()`,
  `run_test_gate()`, and `_merge_and_gate()`. `close_out` runs the gate inside
  the throwaway merged worktree **after** `_merge_in` and **before**
  `push HEAD:<base>` (both the initial merge and the resync-retry). Red suite or
  suite timeout → `res["test_failures"]` + `res["tests"]`, no push; session
  branch is still pushed first so work isn't stranded. `close_out_notes` emits
  "test gate failed — merge held: <names>" / "passed" / "skipped" lines.
  `KANBAN_TESTGATE=0` off-switch. Fail-open (merge_guard convention) on missing
  pytest, no `tests/` dir, and pytest rc 5 (nothing collected).
  - chaba: `python3 -m pytest tests -x -q` (240s)
  - ada-pi: `python3 -m pytest tests -k 'not slow' -x -q` (300s)
  - others: default command, but only when the merged tree has `tests/` —
    effectively none.
- `scripts/board/kanban-dispatch.py` — `merge_pending_one` treats
  `test_failures` like conflicts: `verified=False` + auto-retry requeue with
  `last_failure` populated from the gate note. Module docstring updated.
- `scripts/board/runner-agent.py` — `close_out_merge` returns
  `verified=False` on `test_failures` so remote-runner finishes stamp it too.
- `.husky/pre-commit` — fast pytest step before the SSOT early-exit: staged
  `tests/<d>/` or `scripts/<d>/` changes run `pytest tests/<d>` under
  `timeout 15` (`scripts/lib` → `tests/board`). Real failures block; missing
  pytest / rc 5 / 15s budget warn only. `CHABA_PRECOMMIT_TESTS=0` opts out.
- `scripts/devin/dispatch-repos.conf` — comment pointing at `REPO_TESTS`.
- `docs/ssot/kanban/ssot.kanban.yml` — `close_out` doc renumbered (merge →
  test gate → push), `verified` semantics + pre-commit variant documented;
  chaba-ci program note extended.
- `docs/ssot/jobs/kanban/2026-10-09-ci-test-gate.yml` — trail entry.

## Suite-rot fixes (required for `pytest tests` to be gate-safe)

A bare `python3` run of `tests/` was red before this change:

- `tests/camwall/test_cam_wall_cms.py` — added the `scripts/cam-wall`
  `sys.path` insert the script's `import zone_meta` needs. This unmasked a real
  bug: `cam-wall-cms.py` defined `regen_reports_index()` (commit 0630e01c) but
  never called it — now invoked in `main()` when not `--dry-run`, so the
  reports index regenerates in the same cycle as lifecycle marks.
- `tests/ada_memory/test_obsidian_app.py` / `test_secrets_console.py` — skip
  (not error) when fastapi/httpx/uvicorn/cryptography are absent; those suites
  are documented as ada-pi/secrets-venv tests.
- `test_noop_run_skips_silently` — fixed a stale assertion (was failing on
  HEAD): a no-commit session is `noop`, not `merged`.

## Verify

- `python3 -m unittest discover -s tests` → 109 tests, all pass/skip (28
  venv-gated skips).
- `tests/board/test_dispatch_close_out.py` now covers: red suite holds merge
  with names in `test_failures` + branch still pushed; green gate merges;
  `KANBAN_TESTGATE=0`; timeout holds; missing-runner fail-open; no-tests-dir
  skip; `merge_pending_one` requeue with `last_failure`; real-pytest naming
  (auto-skips when pytest absent).
- Pre-commit hook exercised end-to-end: staged `tests/board/` change → gate
  fires; fake failing pytest → hook exits 1; `scripts/board/` change maps to
  `tests/board`.

## Caveats / follow-ups

- **This host (idc02) has no pytest and no pip** — the gate fail-opens here by
  design. For the gate to bite on real merges, dispatch-capable hosts need
  `python3-pytest` (tony-dell, omen, idc01-03, mn01). Noted on the card.
- `node`/`ssot-validate-all.mjs` unavailable on idc02 — SSOT files parse-checked
  with PyYAML only.
- ada-pi's gate command is configured but unverified (repo not present here).
