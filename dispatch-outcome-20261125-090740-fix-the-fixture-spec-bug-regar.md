# Dispatch outcome — ops-readonly fixture required_keys + runner-agent sync

Card: `fixture-spec-bug-ops-readonly-artifact-e-95ef6e` (ref OPS-1176)
Date: 2026-11-25

## Result: done — fixture spec fixed + pinned by tests; runner-agent already synchronized fleet-wide

### Fixture spec bug

The 2026-11-07 `ada-opencode-live-demo-opsread` failure was diagnosed on
the card as `expect.required_keys=[artifact,tests,verifier]` not matching
the ops-readonly artifact shape. That expect shape is the
branch-code/devin result-review contract — it was never valid for a
health-JSON artifact. In current code `action.expect` is only consumed
by `executor=kk_mac_local` (`scripts/devnest/kk_mac_executor.py`); the
opencode lane verifies via the profile's held-out `fixture/verify.py`,
so the durable fix is to make the fixture spec itself carry the correct
flat key list.

Changes:

- `evals/opencode-lane/profiles/ops-readonly/fixture/task.yaml` — added
  `contract.required_keys`: the 12 health-JSON keys, with a comment
  marking it the canonical `action.expect.required_keys` value for
  ops-readonly cards and naming the branch-code shape as the bug.
- `tests/devnest/test_ops_readonly_fixture.py` — new 7-test suite:
  `required_keys` == `required_fields` keys == the `req` tuple
  ast-extracted from `verify.py`; every key appears in `prompt.md`; the
  branch-code expect shape is absent; `verify()` passes end-to-end on a
  real `host_snapshot.collect()` artifact and fails on a dropped
  required key or wrong host.
- `docs/ssot/jobs/devnest/2026-11-25-ops-readonly-fixture-required-keys.yml`
  — trail doc.

### runner-agent synchronization

Verified live over ssh — no redeploy needed (same convergence the
sibling drift card found ~40 min earlier):

| host | `~/.local/bin/runner-agent` | `<checkout>/scripts/board/runner-agent.py` |
|---|---|---|
| idc02 | 1514c75c… | 1514c75c… |
| idc03 | 1514c75c… | 1514c75c… |
| tony-macbook | 1514c75c… | 1514c75c… |
| tony-dell (this worktree) | 1514c75c… | 1514c75c… |

All match `origin/master` blob `09cebebf27f3cd839db93449d36e468ffc67a64e`.
A manual `scp` would have been a byte-no-op, so none was performed.

## Verification

- `python3 -m unittest tests.devnest.test_ops_readonly_fixture` — 7/7 OK.
- `python3 -m unittest tests.devnest.test_opencode_profiles
  tests.devnest.test_host_snapshot tests.devnest.test_ops_readonly_fixture`
  — 104 tests OK.
- `python3 -m unittest discover -s tests/devnest` — 406 tests; only
  pre-existing environmental error (`test_ada_result_review` needs the
  `pytest` module, unrelated).
- `python3 -m unittest discover -s tests/board` — 1019 tests; 6
  failures + 2 errors, all environmental (missing `pytest` module /
  fail-closed test gate, mddb-down warnings) and unrelated to this
  diff — the diff touches only the ops-readonly fixture yaml, a new
  devnest test, and a jobs trail doc.
- runner-agent sha256 triple-match verified on all four hosts above.

## How to verify

```
python3 -m unittest tests.devnest.test_ops_readonly_fixture -v
ssh idc02 'sha256sum ~/.local/bin/runner-agent ~/CascadeProjects/chaba/scripts/board/runner-agent.py'
# repeat for idc03, tony-macbook — expect 1514c75c… twice per host
```

lessons:
- action.expect.required_keys is only consumed by executor=kk_mac_local (kk_mac_executor.py); opencode/profile lanes verify via the held-out fixture verify.py — expect blocks on opencode cards are inert metadata, so "expect mismatch" diagnoses should check which executor actually reads the field.
- Drift-defer cards are often already healed by the time a dispatch lands — sha256 BOTH ~/.local/bin/runner-agent and <checkout>/scripts/board/runner-agent.py before touching anything; a manual cp is a byte-no-op on converged hosts.
- The ops-readonly fixture now carries contract.required_keys as the single source for card expect.required_keys — keep it in sync with verify.py's `req` tuple; test_ops_readonly_fixture.py fails loudly if they drift.
