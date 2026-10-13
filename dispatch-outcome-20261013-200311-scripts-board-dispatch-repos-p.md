# dispatch-test-gate-venv — outcome

Card: `dispatch-test-gate-venv` · runner: tony-omen · 2026-10-13

## What changed

`scripts/board/dispatch_repos.py` — the merge test gate no longer assumes
system `python3`. A python-led test command now gets its interpreter
resolved per repo before it runs:

- New `gate_python(wt, repo_name, cfg)`: first candidate
  `{tree under test, canonical checkout (git-common parent), repos.conf
  path}/{.venv,venv}/bin/python[3]` that can `import pytest` wins.
  Explicit `REPO_TESTS[repo]["python"]` pin is the escape hatch;
  `""` keeps system python3.
- New `_resolve_gate_cmd`: substitutes the command's leading
  `python`/`python3`/`python3.x` token (shlex-quoted); non-python
  commands pass through untouched.
- `run_test_gate` result dicts gain a `python` key naming the
  interpreter that ran; `command` records the resolved command so held
  merges show which python produced the failure.
- Resolution block documented in the test-gate comment and in
  `scripts/devin/dispatch-repos.conf`'s header.

Key design point: the probe is `import pytest`, not file existence —
`~/CascadeProjects/chaba/venv/` has a python but NO pytest, so existence-
only resolution would have flipped chaba's gate from real-suite-under-
system-python to fail-open skip. Verified on this host: ada-pi resolves
to `~/CascadeProjects/ada-pi/.venv/bin/python` (pytest + google.genai);
chaba correctly falls back to system `python3`.

ada-pi needs no pin — worktrees resolve through `git --git-common-dir`
to the canonical checkout's `.venv` on any runner whose repos.conf (or
BUILTIN_REPOS fallback) maps the name.

## Verification (synthetic held-merge scenario)

New tests in `tests/board/test_dispatch_close_out.py`:

- `test_gate_venv_python_unholds_merge` — reproduces the incident
  end-to-end: a suite that imports a dep only the venv provides is red
  under system python3 (the held-merge half), then green via the
  canonical checkout's `.venv` shim → merge lands, `python`/`command`
  assert the venv interpreter ran.
- `test_gate_skips_venv_without_pytest` — `python3 -S` shim venv is
  probe-rejected; gate falls back to system python3 and merges.
- `test_gate_prefers_tree_venv_over_checkout` — candidate order.
- `test_resolve_gate_cmd_pin_and_nonpython` — pin wins; `make test`
  untouched.

`python3 -m pytest tests/board -x -q` → **109 passed** (was 105 before
this change; the 4 new tests all ran, none skipped on this host).

## Files

- `scripts/board/dispatch_repos.py` — venv interpreter resolution
- `scripts/devin/dispatch-repos.conf` — header documents resolution
- `tests/board/test_dispatch_close_out.py` — 4 new tests
- `docs/ssot/jobs/kanban/2026-10-13-test-gate-venv.yml` — job record

## Note

The `ada-pi` side needs no change: its deploy gate
(`scripts/deploy-ada.sh`) already runs `.venv/bin/python -m pytest`.
Only the dispatch merge gate (this repo) used bare `python3`.
