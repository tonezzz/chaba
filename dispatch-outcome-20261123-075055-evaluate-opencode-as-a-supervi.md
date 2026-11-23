# Dispatch outcome — opencode-standard-procedure-rollout (attempt 3, mn01)

## What changed

- Wrote `docs/ssot/jobs/devnest/2026-11-23-opencode-standard-procedure-rollout-eval.yml`
  — the evaluation the card asked for. Verdict: **ADOPT-BOUNDED**.
- No code, config, SSOT, or lane-state changes. `OPENCODE_LANES`
  untouched (per-host opt-in), nothing runs in Colab, no procedure
  converted, no new enablement — evaluation document only.

## Prior-attempt context (why this ran again)

The 2026-11-20 tony-omen run completed the eval and committed
`1f317ed171` on `dispatch/20261120-213459-...`, but the unit exited
nonzero right after and the branch was never pushed (not on origin;
object not present). The artifacts were lost. This run re-derived the
eval from repo evidence — same conclusion, updated for the
2026-11-12 stor-01 S3→S0 rollback which postdates the lost eval.

## Findings

- **Every spec element already has shipped enforcement**: fresh
  task-scoped session (per-run rendered `opencode.json`, builtin agents
  disabled), isolated dispatch worktree (`start_opencode_lane`), per-task
  tool/path allowlist (envelope must narrow the profile), free lane
  default (flash-lite via LiteLLM, paid_frontier→devin escalation),
  declared artifact + independent verifier (envelope schema +
  `independent_devin` finalize-review attestation path), token/time/
  intervention record (`metrics.jsonl` + `lane_gate metrics`), S0–S2
  bound (stage admission + quota + weekly promote/hold/rollback),
  human-gated classes (hard-deny row: production/destructive/deploy/
  secret/payment/credential).
- **Pilot evidence**: 3/3 free-lane jobs passed 2026-10-26 with 0
  intervention/escalation, −30%/−38% wall vs paired Devin baselines,
  ~$0.07 measured list-price delta. Two honest rollbacks since
  (2026-10-29 S1, 2026-11-12 S3 stor-01) — the gate working, and the
  reason adoption stays bounded: the lane sits at S0 today, re-climb
  owned by card `opencode-lane-regraduation`.
- **Procedure triage** (78 entries in `ssot.procedures.yml`): ~19 stay
  scripts (they already are scripts/timers/APIs), ~15 have an
  OpenCode-eligible S0–S2 read-only/report/doc judgment slice
  (cms-report draft, place-report, feature-explore, backlog triage
  assist, audits/research/bench-analysis slices), the rest are
  human-gated (production/secrets/publication/keys/budget/restarts/
  Colab) or doctrine that isn't executor work.

## Result

Card spec satisfied: evaluation produced, bounds preserved, nothing
enabled. Recommended path on the doc: when the lane re-graduates to
S3, seed eligible procedure slices as `action.lane_envelope` cards
under `S3_STAGED_PROFILES` only.

## How to verify

- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/jobs/devnest/2026-11-23-opencode-standard-procedure-rollout-eval.yml'))"` — parses.
- Cross-check claims: `evals/opencode-lane/PROCEDURE.md` (stage table,
  hard-deny row), `scripts/board/runner-agent.py` `S3_STAGED_PROFILES`,
  `docs/ssot/jobs/devnest/pilot-runs/2026-10-26-devnest-fl-pilot-*.yml`
  (pilot metrics), `evals/opencode-lane/reports/2026-11-12-stor01-rollback-review.json`
  (current S0 state).

lessons:
- Commit AND push dispatch artifacts before doing anything else at session end — the 2026-11-20 run committed but died before push, and the branch/objects were lost entirely; an unverified branch is treated as partial work and GC'd.
- Prior dispatch branches aren't always recoverable: `git branch -a`/`cat-file` confirmed commit 1f317ed171 never left tony-omen — always re-derive from committed repo evidence, don't hunt ghosts.
- Lane stage is host-local state + committed reviews; the durable truth is `evals/opencode-lane/reports/*promotion-review.json` — the lane was S0 (stor-01 rollback), not S3 as the older lesson primer implied.
- Two rollbacks (2026-10-29, 2026-11-12) mean "adopt" for this card = adopt the contract, not expand enablement; check the newest rollback review before repeating S3-ready claims.
