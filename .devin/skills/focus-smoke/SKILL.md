---
name: focus-smoke
description: CLI smoke tests for the chaba focus_dispatcher / mcp_focus consolidation.
trigger: When asked to test or smoke-test the focus system, focus_dispatcher, or mcp_focus focus router in the chaba repo.
---

# Focus-system smoke tests

Runs the canonical CLI checks for the focus state-mutation engine.

## Preconditions

- Working directory is the chaba repo root.
- Current branch is the focus-consolidation PR branch (e.g. `devin/focus-consolidation-20260820`) or `master` with the new code.
- Python 3 and PyYAML are available (`python3 -c "import yaml"` succeeds).
- `docs/ssot/ssot.focus.current.yml` is present.

## Commands

1. Capture baseline SSOT state:
   ```bash
   git status --short
   git diff -- docs/ssot/ssot.focus.current.yml
   md5sum docs/ssot/ssot.focus.current.yml docs/ssot/ssot.focus.yml
   ```

2. Syntax-check changed Python files:
   ```bash
   python3 -m py_compile \
     scripts/focus_dispatcher/actions.py \
     scripts/focus_dispatcher/log.py \
     scripts/focus_dispatcher/tests/test_dry_run.py \
     scripts/mcp_debug/focus.py
   ```

3. Run the dry-run unit tests:
   ```bash
   python3 -m unittest scripts.focus_dispatcher.tests.test_dry_run -v
   ```

4. Run the real `--next` dispatcher check. With an incomplete active branch focus it should report `ok: False` and **not** write `ssot.focus.current.yml`:
   ```bash
   python3 scripts/focus-dispatcher.py --next
   git diff -- docs/ssot/ssot.focus.current.yml
   ```

5. Read-only status check via the thinned `mcp_debug/focus.py` delegate:
   ```bash
   python3 -c "import sys; sys.path.insert(0,'scripts'); from mcp_debug.focus import mcp_focus; print(mcp_focus(mode='status'))"
   git diff -- docs/ssot/ssot.focus.current.yml docs/ssot/ssot.focus.yml
   ```

6. Recommendation check:
   ```bash
   python3 -c "import sys; sys.path.insert(0,'scripts'); from mcp_debug.focus import mcp_focus; print(mcp_focus('check focus system status', mode='recommend'))"
   ```
   - This should return a recommendation dict without crashing.
   - It appends a decision entry to `docs/ssot/ssot.focus.decisions.yml` by design; verify that `ssot.focus.current.yml` and `ssot.focus.yml` remain unchanged.

## Expected pass criteria

- `py_compile` exits 0 with no output.
- Unit tests print `Ran 3 tests` and `OK`.
- `--next` exits 0, contains `'ok': False` and the active branch focus label, and `git diff` for `ssot.focus.current.yml` is empty.
- `mode='status'` exits 0, contains `'ok': True` and the active shared/branch focus labels, and does not modify any SSOT file.
- `mode='recommend'` exits 0 and returns a non-empty recommendation dict without corrupting `ssot.focus.current.yml` or `ssot.focus.yml`.

## Known gotchas

- `mcp_focus(mode='recommend')` always appends to `docs/ssot/ssot.focus.decisions.yml` because it calls `focus_dispatcher.log.log_decision` without a `dry_run` parameter. If a pristine working tree is required, save/restore `ssot.focus.decisions.yml` around the test.
- The exact recommendation action depends on the active focus and backlog; only crash/empty-result should be treated as a failure.
- `focus-dispatcher.py --next` performs a real run and will advance the focus if the active branch focus is complete and a parked/deferred candidate exists. Run with care if the working tree must stay clean.

## Devin Secrets Needed

None.
