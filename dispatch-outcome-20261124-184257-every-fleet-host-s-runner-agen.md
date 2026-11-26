# Dispatch outcome — runner-agent deploy propagation gap (OPS-1026)

Card: `runner-agent-deploy-propagation-gap-repo-56a255`
Branch: `dispatch/20261124-184257-every-fleet-host-s-runner-agen` (commit `b72a53d32a`)

## What I found

The card asked for auto-propagate of `~/.local/bin/runner-agent` snapshots —
but it **already existed twice**:

- `runner-agent._self_update()` — at every pass start, installs a newer
  byte-compiling repo copy and re-execs (added 2026-11-02, OPS-1026).
- `scripts/devin/sync-runner-tools.sh` — runs at `git-safe-pull.sh`'s tail
  on every `chaba-repo-sync` tick, converging all six `~/.local/bin` tools
  under sha256 pins in `runner-tooling.manifest.json` (merged 2026-11-18).

The real break was upstream of both: **master's manifest pin was stale** —
`runner_agent` pin `d0a103cb…` vs actual source sha `9a42dc07…`. Commit
`7dc2187b7d` ("Compaction summary" checkpoint) changed `runner-agent.py`
without the same-commit pin bump, so `sync-runner-tools.sh` refused
runner-agent installs on every host, `runner-fleet-health`'s tool-pin audit
went red fleet-wide, and `test_runner_tooling_contract.py` failed on master.
Meanwhile `_self_update()` ignored pins entirely and happily propagated the
unpinned build — the two deploy paths disagreed about what "current" means.
The pre-commit pytest gate couldn't catch it: it runs `tests/board` under a
15s cap that swallows the contract test.

## What changed (commit b72a53d32a)

- `scripts/board/runner-agent.py`
  - new `_self_pin_ok()`: `_self_update` now installs only repo copies whose
    sha256 matches the `runner_agent` pin in the checkout's own manifest —
    the same fail-closed rule `sync-runner-tools.sh` applies (also refuses
    dirty-checkout state, since any byte change breaks the pin).
  - `_self_stale_check` decline message no longer advises manual scp; names
    the real causes (stale checkout / unpinned source).
- `scripts/devin/runner-tooling.manifest.json` — `runner_agent` pin bumped to
  the new source sha `b879b47f…`, healing the live master mismatch.
- `.husky/pre-commit` — new runner-tooling pin gate: when a pinned source or
  the manifest is staged, compares **staged blob** sha256s (`git show :path`)
  and blocks on mismatch. Only pin pairs the commit touches are checked, so
  inherited master breakage can't block unrelated commits. Opt-out:
  `CHABA_PRECOMMIT_PINS=0` / `--no-verify`.
- `tests/board/test_runner_self_update.py` — new hermetic suite (fake $HOME,
  extensionless snapshot via `SourceFileLoader`, `os.execv` mocked): 6 cases.
- `docs/ssot/jobs/kanban/2026-11-24-runner-agent-deploy-propagation.yml` —
  full write-up of the propagation model and verification.

The spec's alternative (ExecStart → repo path + hash wrapper) was rejected:
the snapshot+pin model already provides fast path, fleet path, blessed-version
gate, and the `_self_stale_check` drift gate — running the checkout file
directly would silence that gate and couple agent version to checkout
freshness.

## Verification

- `pytest tests/board/test_runner_self_update.py
  test_runner_tooling_contract.py` (+ lane/gate/defer/push-guard suites):
  **64 passed**.
- Pre-commit pin gate exercised in a scratch repo: tool-change-without-pin
  **blocked**, tool+pin together **pass**, pin-only catch-up **pass**,
  unrelated file **skipped**, inherited-broken-pair + clean other-tool
  change **pass**.
- `sync-runner-tools.sh --verbose` in a sandboxed canonical checkout:
  refreshed a drifted `~/.local/bin/runner-agent` to the pinned build,
  mode 0755 preserved; never-downgrade guard kept a newer dest.
- This commit itself ran the armed `.husky` hook including the new pin gate.

## Residual / how to verify fleet-wide

Post-merge, each host converges on its next `chaba-repo-sync` tick
(`sync-runner-tools.sh`, pin now consistent) and/or next `runner-agent`
pass (`_self_update`). The card's "push a change → all hosts run it" check is
observable as: no new `installed runner-agent drifted` deferrals after one
sync cycle, and `runner-auto-<host>` cards auto-closing. Hosts still on a
pre-2026-11-02 snapshot (no `_self_update`) are bootstrapped by
`sync-runner-tools.sh` once — after that they self-heal.

lessons:
- The 15s-capped pytest gate in `.husky/pre-commit` swallows `tests/board` —
  contract tests there never gate commits; pin-class invariants need their
  own staged-blob check.
- Two deploy paths for the same artifact must share ONE validity rule —
  `_self_update` ignoring the manifest pin let unpinned code propagate while
  `sync-runner-tools` refused it.
- Compaction-summary checkpoint commits bypass review — they can land tool
  changes without the same-commit pin bump; the new pre-commit pin gate
  catches them on armed checkouts.
