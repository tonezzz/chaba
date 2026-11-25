# Dispatch outcome — chore-excise-jules-lane-code

## What changed

Commit `a6845f00297` on `dispatch/20261125-154043-goal-is-to-excise-retired-jule`
(14 files, +38/−107). `runner-agent.py` needed no edits — master already
carries zero jules references.

- `docs/ssot/infrastructure/ssot.devnest-lanes.yml` — removed the `jules`
  lane doc block and the `JULES_LANES` env_gates entry; also removed an
  accidental duplicate `nlm_batch` block (identical YAML key appeared
  twice — one silently won).
- `scripts/board/dispatch_repos.py` — removed the jules tombstone comment
  in the executor-contract header.
- `scripts/board/kanban-dispatch.py` — `("jules", "nlm_batch")` tuples →
  `nlm_batch`-only in both the claimable gate and the claim loop;
  closeout-defer comment no longer names jules.
- `scripts/board/board-api.py` — selftest invalid-value fixtures
  `lane=jules`/`executor=jules` → `bogus-lane`/`bogus-executor` (same
  fail-closed assertions); reason string de-jules'd.
- `scripts/board/lane-savings.py` — dropped `jules` from `CHEAP_LANES`
  and `EXECUTOR_LANES`.
- `scripts/board/runner-fleet-health.py`, `.github/workflows/repo-lint.yml`,
  `scripts/ops/kk-mac-runner-onboard.sh`, `.devin/skills/card-ops-sweep/SKILL.md`
  — stale comments/description scrubbed.
- `docs/kb/{card-status-and-processing,kk-mac-launchd-runner,ada-ocb-tools-mcp-workflow-education}.md`
  — live procedure docs updated (one also had a wrong lane allowlist).
- `tests/board/test_runner_tooling_contract.py` — the old
  `test_ssot_still_declares_jules_retired` would fail once the lane entry
  is gone; replaced with `test_excised_lane_stays_excised` (asserts no
  `jules` lane key and no `scripts/jules/`). The generic retired-lane
  contract tests still run off SSOT `status:` fields for any future
  retirement.
- `scripts/devin/runner-tooling.manifest.json` — `dispatch_repos`
  sha256 bumped to the new source hash (pin gate requires same-commit
  bump).

## Verification

- `python3 tests/board/test_runner_tooling_contract.py` — 15 tests OK.
- `python3 scripts/board/board-api.py --selftest` — `selftest ok`.
- `python3 -m unittest` on test_kanban_dispatch_rails, test_queue_time_classify
  (41), test_kanban_dispatch_card_index, test_waiting_cards (27),
  test_board_api_mutations (37), test_kanban_stats_lane, test_executor_contract,
  test_claim_order, test_runner_agent_lane — all pass.
- `test_dispatch_close_out` has 6 failures, all environmental: the merge
  gate fails closed with "pytest unavailable — no test evidence" on this
  host (no pytest installed); unrelated to the diff.
- YAML parses; `lanes:` keys now: codemod, deterministic, devin,
  free-opencode, jev-routing, kk_mac_local, local-gpu-packs, manual,
  nlm_batch, paid_frontier.
- Deployment check: installed `~/.local/bin/runner-agent` on **tony-dell**
  and **idc02** both sha256 `1514c75c…` = repo pin, 0 jules refs — the
  drift deferrals in card comms were stale-checkout noise already healed
  by `_self_update`/`sync-runner-tools`. `runner-agent.py` is unchanged by
  this commit, so no redeploy was needed; `dispatch_repos.py` reaches
  hosts via the bumped manifest pin on the next sync cycle, and
  `kanban-dispatch.py`/`board-api.py` via the normal served-checkout pull.

## Deliberately left alone

- Kanban card YAMLs, `docs/reports/jules-*.md`, bench corpora
  (`scripts/bench/**`), evals results, focus-inbox entries, job docs —
  historical records, not live code.
- `docs/ssot/jobs/**` and `docs/kb/ada-ocb-triage-lessons-2026-11-20.md`
  mention jules as incident history.
- `stacks/idc02/boards-lesson-redirects.caddy` keeps the
  `Education:Devnest-Jules-Lane` lesson redirect — removing it would
  break links to a published lesson; flag for Tony if he wants it gone.

lessons:
- The jules excision was already ~90% done on master; the card's line
  numbers were stale — grep the tree before trusting comms citations.
- Editing any file in `runner-tooling.manifest.json`'s source list
  (dispatch_repos.py counts) requires bumping its sha256 pin in the same
  commit or `test_runner_tooling_contract` fails.
- ssot.devnest-lanes.yml had a duplicated `nlm_batch` block (YAML
  silently keeps the last); worth a yaml-key-dup lint if it recurs.
- "installed runner-agent drifted" deferrals were false positives —
  `_self_update` had already converged both hosts to the repo pin.
