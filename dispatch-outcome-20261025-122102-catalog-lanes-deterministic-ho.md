# Dispatch outcome — DevNest lane catalog + monthly savings report (OPS-0869)

Card: `devnest-token-savings-lane-catalog` · runner: mn01 · branch:
`dispatch/20261025-122102-catalog-lanes-deterministic-ho`

## What was produced

- **`docs/ssot/infrastructure/ssot.devnest-lanes.yml`** — the production
  lane catalog. 8 entries (the 7 spec'd lanes + `manual` as the
  never-dispatched terminal): deterministic scripts, codemod (L0),
  jev-routing (decision plane), local-gpu-packs, free-opencode,
  paid_frontier, devin fallback. Each carries the six spec fields —
  task_classes, verifier, target_host, expected_cost/tokens,
  evidence_artifact, escalation — plus measured numbers from the
  cascade/bench evidence base (t1 codemod 7/7@0.7s, gpt-oss:20b T4
  p50 14.7s vs 78.3s CPU, fable 7/7@60s, opencode probe 2355 tokens).
  Also records the routing model (entry-level prediction, not a
  bottom-up ladder), env gates (JEV_LANE / OPENCODE_LANES /
  JEVOS_URL), and open gaps (OPS-0838 queue-time classify, OPS-0846
  OpenCode closeout, KNB-0822 real Jev key, dev-family verifiers).
- **`scripts/board/lane-savings.py`** — monthly savings reporter.
  Evidence-bound per the spec's hard rule: a lane use counts only
  when the run completed AND left usage evidence (action.result,
  step-finish token JSON, declared artifact, comms measurement);
  unevidenced uses are counts, never dollars. Sources: card YAMLs
  (action.*, auto_close), merged dispatch-outcome files, and
  pack/bench JSON artifacts (`scores.<lane>.loop.tokens_in/out/
  cost_usd` shape). Detects opencode-lane runs via the step-finish
  signature in action.result since no card persists `action.lane` yet.
- **`docs/reports/lane-savings-2026-10.{md,json}`** — first monthly
  run. October: 420 devin-lane dispatches done (the paid baseline —
  lane routing only landed 2026-10-25 and classify-at-queue-time is
  still backlog), 5 deterministic script runs, 1 free-opencode probe
  (2,355 measured tokens), 18 measured pack/bench runs totaling
  983,829 tokens at cost_usd 0.0. Honest bottom line: savings ≈ zero
  claimed — the machinery now measures it.
- **`ssot.reports.yml`** — registered `lane-savings` L2-domain node
  (generator + monthly cadence + artifact pattern).
- **`docs/ssot/jobs/nest/2026-10-25-devnest-lane-catalog.yml`** — job
  trail.
- Fixed pre-existing YAML syntax error in
  `jobs/bench/2026-10-24-m2-behavioral-verifier.yml` (unquoted `:`
  in list scalar — the suite's one red file).

## Findings surfaced

- No card persists `action.lane` — classify runs at claim under
  `JEV_LANE=1` (set on no runner unit yet) and `OPS-0838` queue-time
  classify is still backlog. Until then, unset-lane cards run the
  paid devin default: the catalog's measured savings stay near zero
  by design, not by failure.
- Devin dispatch sessions log CPU/mem but no token counts — the
  opencode executor's step-finish JSON is currently the only
  per-session token evidence on the board.

## How to verify

- `python3 scripts/board/lane-savings.py --month 2026-10 --out-dir
  docs/reports` — regenerates the report (read-only scan).
- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/
  infrastructure/ssot.devnest-lanes.yml'))"` — parses.
- Pre-commit SSOT gate ran clean on all touched files; the remaining
  suite error (m2-behavioral-verifier.yml) is fixed in this branch.
- Commits: `1036b472` + `7f1fed50` on the dispatch branch (not
  pushed, per rails).
