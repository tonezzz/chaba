# Dispatch outcome — classifier-readonly-audit-class-reroute

Card: `classifier-readonly-audit-class-reroute` (parent `devin-usage-reduction`,
DEV-0044 lever 1 first pick). Branch `dispatch/20261125-093311-parent-card-devin-usage-reduct`,
commit `126be8990e5`. Host: tony-dell.

## What changed

`classify_lane` (scripts/board/dispatch_repos.py + lockstep vendored copy in
scripts/board/runner-agent.py) now routes cards whose TITLE leads with an
audit/assessment/review/investigate/sweep marker to `free_lane`
(source `kw:audit-ro`, conf 1.0), evaluated at the free_lane slot of the lane
loop — after explicit lane, timer-alert pin, manual keywords, LANE_COMPARE,
paid_frontier, and codemod; before devin keywords and the jevos fallback.

- `AUDIT_RO_TITLE_RE`: title-scoped lead match — optional leading `[...]` tags,
  then either a bracket tag containing the stem (`[audit] ...`), a bare stem
  followed by space/punctuation (`Audit unlanded ...`, `Assess sys-mon ...`),
  or a hyphenated slug with >=2 hyphens (`audit-miss-unlanded-oct06-...`).
- `AUDIT_RO_MUTATION_RE`: title veto on fix/implement/deploy/migrate/merge/
  repair/patch/cleanup/build/create (stems, word-boundary — `fixture`/`prefix`
  safe).
- NOT added to `LANE_KW['free_lane']` — a raw `audit` substring would match
  spec bodies fleet-wide.
- `scripts/devin/runner-tooling.manifest.json` sha256 pins bumped for both
  sources (required by test_runner_tooling_contract).

## Design deviation worth noting

The card spec's pattern (`audit|assessment|review|investigate|sweep` lead,
with a mutation-verb title exclusion) was implemented with two tightenings found
during the open-card snapshot verify:

1. **Slug form needs >=2 hyphens.** `vcast-audit-cast` ("audit-cast runaway
   guard fails — CB_RSS unbound variable") is a bug-fix card whose title leads
   with the *component name* `audit-cast`, not an audit task. Single-hyphen
   compounds followed by a space no longer match; the spec's required positive
   `audit-miss-unlanded-oct06-dispatch-artifacts` (multi-hyphen slug) still
   does.
2. **Bare keyword must be followed by space/punctuation** — same guard.

## Verify results

- `pytest tests/board/test_queue_time_classify.py
  tests/board/test_codemod_lane_gate.py tests/board/test_runner_tooling_contract.py`
  — 72 passed. Full `tests/board/` run: 1025 passed, 2 failed — both
  `test_control_pane_projection` cases needing gitignored generated fixtures
  (`stacks/web/public/apps/board2/index.html`, `cards.json`) absent in this
  worktree; pre-existing/environmental, unrelated to this diff.
- Open-card classifier snapshot (756 cards, `JEVOS_URL` unreachable -> fallback):
  **9 cards devin -> free_lane**, all audit-cohort:
  `audit-miss-unlanded-oct06-dispatch-artifacts`,
  `investigate-devin-handoff-job-ledger-ter-408e7a`,
  `or-direct-bypass-leak-audit` (was `kw:repoint` — audit-ro now correctly
  pre-empts the spec-body devin keyword), `audit-miss-ada-chaba-home-snapshot`,
  `audit-miss-education-lesson-write-timeout`, `audit-oc-mutating-command-*`
  x3, `sweep-stale-mddb-endpoint`.
  3 more changed source tag only inside free_lane (`audit-oc-artifact-not-
  durable`, `audit-oc-denied-tool`, `sweep-pagination` — lane unchanged).
  `vcast-audit-cast` stayed devin. Zero unrelated lane changes.
- New tests: 12 cases in `AuditRoClassifyTest` + one queue-path test +
  lockstep regex assertion in `test_codemod_lane_gate.py`.

## How to verify

```
python3 -m pytest tests/board/test_queue_time_classify.py \
    tests/board/test_codemod_lane_gate.py -q
# snapshot: classify_lane(with_detail=True) over docs/ssot/kanban/cards/*.yml
```

## Deploy note

Hosts pick this up via the normal chaba checkout sync
(chaba-repo-sync.timer) for `dispatch_repos.py` consumers (board-api,
kanban-dispatch, card-triage) and `sync-runner-tools.sh` /
runner-tooling manifest pins for the `runner-agent` single-file install —
remote claimants classify with the vendored copy, so fleet sync matters for
consistent routing (same class as the earlier runner-agent drift defers).

lessons:
- runner-tooling.manifest.json sha256-pins runner-agent.py AND dispatch_repos.py — any edit to either must bump pins in the same commit or test_runner_tooling_contract fails.
- "audit-"-prefixed component names (audit-cast) false-positive naive audit-title rules; require >=2 hyphens for slug forms.
- dispatch worktrees lack gitignored generated fixtures (stacks/web/public/apps/board2/*) — 2 test_control_pane_projection failures there are environmental, not regressions.
- free_lane substring kws ('try' inside 'telemetry', 'report' in 'sweeps report') already misroute some mutation cards — pre-existing, worth a future card if it bites.
