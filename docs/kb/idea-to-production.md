# Idea → CI → Production — the pipeline standard (2026-10-09)

How a Tony idea becomes production behavior, with the quality gates
that make it trustworthy. Companion to the monitoring standard — that
doc owns detection; this owns delivery.

## The pipeline

```
1. IDEA        kanban card (requests entry, or session → Devin files card)
                ↓ card carries: spec, AQ acceptance, links
2. BUILD       worktree per session · linear history · no live-checkout edits
                ↓
3. CI GATE     on commit/PR — must all be green:
                · ssot-validate-all (YAML + structure)
                · monitor-coverage-lint (new services need checks/exempts)
                · repo CI (mcp-smoke, camwall-smoke, ssot.yml)
                ↓
4. QA GATE     verify live state on the STAGING surface, not prod:
                ada → idc02 checkout (ff-only, scenarios there)
                HA  → michael-dev dashboards
                svc → the service's own health check endpoint
                ↓
5. BENCH       scenario suites score the behavior change:
                smoke  — hourly tier (cheap, always-on)
                tools  — Friday 03:30 (kanban_review, ada_board_write…)
                gate   — promotion-blocking suite
                suite score must not regress vs prior run
                ↓
6. PROD        explicit same-session approval. Always.
                ada-pi → deploy-ada.sh (idc03; snapshots dirty trees)
                HA    → promote-michael.sh / promote-tony.sh
                infra → stack units + SSOT update in same commit
                ↓
7. OBSERVE     ops-digest + health checks + coverage lint prove the
                change landed healthy; misses loop back to step 3's lints
                ↓
8. CLOSE       card → done with evidence (bench score, digest line)
```

## Where each repo deploys

| Repo | Edit point | Stage | Prod | Gate |
|---|---|---|---|---|
| chaba | any worktree | this host | master + served checkout | commit hooks |
| ada-pi | tony-dell | idc02 (scenarios) | idc03 via deploy-ada.sh | tools suite green |
| sunsynk card | worktree | michael-dev | michael-ha/tony-ha | promote-*.sh + approval |

## Scenario benchmarks — the QA muscle

- Author: `tests/scenarios-live/<name>.yaml` — turns with `calls_any`,
  `response_contains_any`, honesty probes (`no-such-card` turn must
  fail honestly), generous `timeout_s` for write paths.
- Register: suite list in `tests/benchmark.yml` (`write_allowed_in`
  for mutating scenarios); tier `smoke` = hourly, else weekly/manual.
- Score: `scenario-benchmark.py --suite <s>` → pass=1/flaky=.5/fail=0,
  trended via `benchmark/<suite>-<date>` docs in MDDB; regression diffs
  fire on regress.
- Rule: a feature without a scenario ships on hope. kanban_review.yaml
  is the model — full lifecycle + gates + honesty probe.

## The kanban-work scenario specifically

`tests/scenarios-live/kanban_review.yaml` already exercises the whole
loop on a probe card (file → doing → review → close + Tony-decides-move
must be gated + board question → card request). It lives in the `tools`
suite (weekly Fri 03:30). To benchmark a kanban feature change:

```
python3 scripts/scenario-benchmark.py --suite tools   # idc02/ada-dev
```

plus the smoke tier before merge. A kanban scenario fails promotion if
its suite score regresses — that's the gate.

## Failure-mode honesty

- A scenario that can't reach the board counts as fail, not skip.
- Never tune a scenario's expectation to pass — fix the behavior.
- "Ran on my machine" isn't QA: the staging surface is the record.
