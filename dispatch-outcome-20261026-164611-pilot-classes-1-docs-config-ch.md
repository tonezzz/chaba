# Dispatch outcome — pilot-classes-1-docs-config-ch (OPS-0885 docs/config leg)

## What changed

- **`docs/ssot/jobs/devnest/2026-10-26-free-lane-savings-pilot.yml`** (new) —
  the pilot definition: three pilot classes, the required card contract
  (`target_host`, `base_ref`, `verifier`, `expected_artifact`,
  `stop_condition`), the OPS-0885 run-record capture schema with a
  field→source map (model, prompt/session timestamps, LiteLLM spend delta,
  tokens in/out, wall time, gate result, human intervention minutes, merge
  success, escalation, cost per passed gate), the matched Devin-baseline
  comparison method (devin-usage.py transcript metrics + the two existing
  devin-lane pilot runs), and the enablement gate.
- **`docs/ssot/kanban/cards/devnest-fl-pilot-{doc,code,report}.yml`** (new) —
  the three pilot jobs, one per class. Each carries `action.host:
  tony-dell`, `action.lane: free_lane`, `action.model:
  litellm/gemini-3.5-flash-lite` (pinned in YAML — claim-time keyword
  classification is what routed the earlier doc/code runs to the `devin`
  lane, making them non-datapoints), plus a `pilot:` block declaring the
  contract fields, baseline pair, and run-record path. All in `backlog`
  with `action.status` unset — nothing auto-claims on merge.
- **`docs/ssot/infrastructure/ssot.devnest-lanes.yml`** — OPS-0846 marked
  proven (2026-10-26 Dell closeout probe); `free-opencode` status, open
  gaps, and references updated.

## Board actions

- Comment posted on `devnest-free-lane-savings-pilot` summarizing the
  definition work.
- Request `supervised-pilot-queue` raised for Tony: queue all three on
  tony-dell now / queue doc first / hold — suggested: queue all three.

## Key findings

- OPS-0846 (opencode-lane-branch-closeout) is `done` — the Dell probe
  verified the full OpenCode closeout path, so the spec's "after OPS-0846
  proof" precondition is satisfied. Remaining gate is supervision +
  confirming `OPENCODE_LANES=1` in the pinned host's runner-agent env
  (idc02's env has it unset and no `JEV_LANE`; Dell is the proof host).
- `action.lane` is not settable via board-api `/card` (`ACTION_KEYS` drops
  it) — lane pinning must come from the card YAML or the claim body, which
  is why the cards are committed as YAML rather than created via API.
- Class-2 pilot job intentionally delivers
  `pilot_metrics.cost_per_passed_gate()` — the helper the pilot's own
  headline metric needs.

## Result

Success — pilot fully defined and staged; awaiting the supervised-queue
decision on the card request. No push, no deploy, nothing queued.

## Verify

- `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in
  glob.glob('docs/ssot/kanban/cards/devnest-fl-pilot-*.yml')]"`
- `node scripts/ssot-validate-all.mjs` — all new files Valid (the single
  repo error is pre-existing in `jobs/ada/2026-10-26-repeat-user-reask-detector.yml`).
- Contract check: each card has `pilot.{class,target_host,base_ref,
  verifier,expected_artifact,stop_condition}` + `action.{host,lane,model}`
  and no `action.status`.
