# Dispatch outcome — runner-converge-dirty-pinned-source-guard

Card: `runner-converge-dirty-pinned-source-guard` (OPS-1512)
Date: 2026-11-27

## What happened

The requested pre-flight was **already implemented and pushed** before this
dispatch ran: commit `4b767cc7e1` on origin branch
`fix/20261127-runner-converge-dirty-guard` (author Tony, 2026-11-27 20:39
+0700), documented in the card comms at 20:40. The auto-dispatch wave queued
the card at 20:47 regardless.

This session verified the implementation and cherry-picked it onto the
dispatch branch (`91285c1300`, `-x` provenance retained) so it lands via the
normal dispatch close-out merge. The separate `fix/…` branch can be deleted
after merge (its content is identical).

## What the change does

`scripts/devin/runner-tools-converge.sh` gains a `checkout_sources_clean()`
pre-flight, invoked at the top of `converge()` — so it guards BOTH the local
pass and the controller's fleet pass:

- Reads `scripts/devin/runner-tooling.manifest.json` from the checkout the
  script runs from (`$ROOT`, overridable via `RUNNER_CONVERGE_ROOT` for
  tests/dry-runs).
- sha256-hashes every manifest `source` file and compares to its `sha256`
  pin. Missing files count as dirty.
- On any mismatch: logs `DIRTY_PINNED_SOURCES=<path (checkout <sha12> != pin
  <sha12>)|…>` plus "skip this pass — refusing to deploy unpinned sources"
  and returns 0 — no check/apply/audit runs, no bytes that would fail the
  post-copy assert are installed, no runner-agent restart fires.
- On clean: logs `PINNED_SOURCES_OK` and proceeds as before.

This mirrors the guard `sync-runner-tools.sh` already had (src sha != pin →
warn + skip) and closes the gap that let idc02's uncommitted
`dispatch_repos.py` JEVOS_URL edit get deployed, fail the post-copy assert,
restart runner-agent, and re-arm `runner-tool-drift-fleet` ~50× on
2026-11-27 (evidence:
`docs/ssot/jobs/infrastructure/2026-11-27-idc02-runner-tools-local-edit-drift.yml`
— note the card spec cited a slightly different filename,
`…-runner-tool-drift-fleet-idc02-wip.yml`, which does not exist; the
`-idc02-runner-tools-local-edit-drift` doc is the same incident).

The spec's "alternative/complement" (post the dirty-file list to the drift
card) was NOT added — the primary guard eliminates the churn source, and
drift findings still reach the card via the existing
`runner-drift-rearm.py` audit path. Worth a follow-up card only if the
journal-only warn proves too quiet.

## Tests

`tests/devin/test_runner_tools_converge.py` (+47 lines): two new scratch-
checkout tests —

- `test_dirty_pinned_source_skips_all_playbooks`: dirty source →
  `DIRTY_PINNED_SOURCES` names the file, zero playbook invocations, rc=0.
- `test_clean_pinned_source_proceeds`: clean source → `PINNED_SOURCES_OK`,
  playbooks run with `--limit idc02`.

## Verification performed here

- `git cherry-pick -x 4b767cc7e1` — clean apply (target files unchanged on
  master since the branch's merge-base).
- `bash -n scripts/devin/runner-tools-converge.sh` — OK.
- pytest is not installed on this host; ran the suite via a stdlib harness
  calling each `test_*` with a fresh tmp dir: **9/9 PASS** (all pre-existing
  scope/guard tests plus the two new dirty/clean pin tests).
- All 7 manifest pins verified against this worktree's sources — no pin
  bump needed (no pinned source was modified).

## How to verify after merge

1. `python3 -m pytest -q tests/devin/test_runner_tools_converge.py` on a host
   with pytest (or the same stdlib harness).
2. On any managed host, dirty a pinned source in its chaba checkout
   (`echo x >> scripts/board/runner-agent.py`), run
   `scripts/devin/runner-tools-converge.sh`, expect
   `DIRTY_PINNED_SOURCES=scripts/board/runner-agent.py …` and no ansible
   playbook calls; restore the file afterwards.
3. `systemctl --user start runner-tools-converge.service` on idc02 post-merge
   should log `PINNED_SOURCES_OK` and converge normally.

## Files changed

- `scripts/devin/runner-tools-converge.sh` (+49)
- `tests/devin/test_runner_tools_converge.py` (+47)

lessons:
- The card was already implemented+pushed (fix/20261127-runner-converge-dirty-guard) minutes before the dispatch wave queued it — check card comms AND `git ls-remote origin 'fix/*'` for same-day fix branches before re-implementing.
- pytest is absent on dispatch hosts; tests/devin/test_runner_tools_converge.py is pytest-style but fixture-free (tmp_path only) — a ~15-line importlib harness runs the whole file.
- The card spec's evidence filename (2026-11-27-runner-tool-drift-fleet-idc02-wip.yml) doesn't exist; the real doc is 2026-11-27-idc02-runner-tools-local-edit-drift.yml — same incident.
