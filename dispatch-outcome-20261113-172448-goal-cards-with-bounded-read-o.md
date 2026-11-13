# Dispatch outcome — kk-mac-auto-lane-classifier

Date: 2026-11-13 · Runner: tony-omen · Branch: dispatch/20261113-172448-goal-cards-with-bounded-read-o

## What changed

Queued dispatch cards with bounded read-only task classes now auto-route to
`executor=kk_mac_local` at queue time — no author pin needed. The canonical
rule is `kk_mac_route(card)` in `scripts/board/dispatch_repos.py` (next to
`classify_lane`): a card self-routes only when nothing is already routed (no
`action.executor`/`action.lane`), no host pin exists
(`host`/`target_host`/`runner`), the card is dispatch-typed, an admitted class
is declared (`summary`, `operator_brief`, `structured_extract`, `safe_route`)
or unambiguously inferred from prompt keywords, the card text carries no
mutation/side-effect intent (`KK_MAC_MUTATING_RE`), and the resolved prompt is
non-empty and ≤6000 chars. Wired at both routing surfaces:

- `board-api.py::_apply_classify_at_queue` tries `kk_mac_route` before the
  lane classifier, stamps `executor`+`task_class`+a comms note; it now also
  runs on the `do_create` `queue:true` and `on_exists:'queue'` paths, which
  previously armed queued status with no classification at all.
- `do_create` accepts a bare admitted `task_class` as the auto-route hint
  (explicit pins to other executors and unadmitted classes still fail
  closed); `do_claim` persists `task_class` only when paired with
  `executor=kk_mac_local`.
- `runner-agent.py::claim_pass` (JEV_LANE path) runs the same rule for cards
  that queued outside board-api and pins `executor`+`task_class` atomically
  in the `/action do=claim` body.

Explicit executor/lane/host routing always wins and is never overwritten;
the try-first executor contract is unchanged (a mis-route costs one
admission probe, then the claim runs the next lane — never starves, never
runs outside admitted classes).

## Verification

- `python3 -m pytest tests/board/test_queue_time_classify.py
  tests/board/test_executor_contract.py -q` — 97 passed (18 new cases:
  classifier positives/negatives incl. pins, host pins, mutation intent,
  6000/6001 prompt boundary, keyword inference, create+queue, claim-time
  atomic pin).
- `python3 -m pytest tests -q` — **1446 passed, 47 skipped, 1 failed**:
  `tests/ops/test_render_jobs.py::GeneratedTree` — pre-existing drift
  between `docs/ssot/infrastructure/ssot.jobs.yml` and
  `systemd/generated/idc03/` (chaba-cached-videos, chaba-review-digest,
  chaba-starboard-tracker, fleet-jobs-report). Unrelated: this change
  touches neither the manifest nor the generated tree.
- Queue eligibility (the card's verify ask):
  `test_task_class_summary_auto_routes_and_is_claimable` — a card queued
  with `task_class=summary` and no executor gets
  `executor=kk_mac_local`+comms note via `/action do=queue`, and
  `runner.claimable(card)` returns `dispatch` with `KK_MAC_LANES=1`.
- `py_compile` on the three edited scripts: clean; job-record YAML valid.

## Files

- `scripts/board/dispatch_repos.py`, `scripts/board/board-api.py`,
  `scripts/board/runner-agent.py` (+tests: `test_queue_time_classify.py`,
  `test_executor_contract.py`) — committed in `731893dbfc`.
- `docs/ssot/infrastructure/ssot.devnest-lanes.yml` — added the missing
  `kk_mac_local` lane section (env gate, bounded classes, auto-route).
- `docs/ssot/ssot.procedures.yml` — ai-lane-delegate trigger no longer
  states a manual executor pin is required.
- `docs/ssot/jobs/devnest/2026-11-13-kk-mac-auto-lane-classifier.yml` —
  durable job record.
- Not touched: the unrelated `ssot.dev-system.assessment.yml` working-tree
  modification. No pushes, no deploys.
