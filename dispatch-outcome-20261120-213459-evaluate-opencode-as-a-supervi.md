# Dispatch outcome — opencode-standard-procedure-rollout (attempt 2)

## What was produced

`docs/ssot/jobs/devnest/2026-11-20-opencode-standard-procedure-rollout-eval.yml`
— the evaluation job doc: verdict, evidence chain, spec→machinery map,
procedure decision matrix, operating contract, gaps, rollout decision,
references.

## Result

**ADOPT, BOUNDED.** OpenCode is a viable supervised executor for the
judgment-needing slices of Chaba standard procedures at the Tony-approved
S0–S2 scope (read-only reports, doc drafts, bounded research, small
verifiable chores) — but only through the existing admission machinery
(task-scoped profiles + lane_gate + `action.lane_envelope` dispatch
contract). No new machinery was needed: the graduated-routing build-out
already implements every element of the card spec (fresh task-scoped
session, isolated worktree/message-mode artifacts, per-task tool/path
allowlist, free lane default, declared artifact + independent verifier,
token/time/intervention metrics, hard-deny gated classes).

Key calls in the doc:

- Deterministic procedures stay scripts (board-report, key-watch,
  deploy-diff scan, ssh-mesh, backups, timers…).
- ~15 procedures have an OpenCode-eligible judgment/report slice
  (backlog-audit triage, session/drift/incident report writing,
  ssot-research, storage-dryrun, bench report writing…), mapped to the
  enabled profiles.
- Production/secrets/publication/keys/budget/restart classes stay
  human-gated — including every deploy/HA/edge/member/messaging/mutation
  procedure, matching the lane's hard-deny class row.
- OPENCODE_LANES stays per-host opt-in (not fleet-wide); no OpenCode in
  Colab; branch-code stays disabled pending the S5/strong-model decision.

## Evidence base

- 3-job free-lane pilot 2026-10-26: 3/3 merged, 0 interventions,
  30–38% faster than matched Devin baseline, $0.0700 list-price.
- Graduated lane: S0 requalified (OPS-1255), S1 watched canary, S2 5/5
  independent attestations; lane at S3 on idc02 per 2026-11-19 preflight.
- stor-01 tool_denial correctly triggered S3→S0 rollback (2026-11-12) —
  gate works as designed.
- Failure modes all caught deterministically: early-stop
  missing_artifact (dominant), denied bash probes, free-model schema
  variance, dead free model routes.

## Open gaps (carded in doc)

S3 needs 10–20 genuine read-only samples fed by real backlog cards;
waiting_cards verifier duplication; free-route preflight probe;
bounded auto-retry for early-stop; runner-agent fleet redeploy;
procedure executor-affinity tags as follow-up.

## How to verify

- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/jobs/devnest/2026-11-20-opencode-standard-procedure-rollout-eval.yml'))"` — parses (done).
- `python3 scripts/ssot-prose-smell.py` — 0 flagged (done).
- Cross-check decision matrix against `docs/ssot/ssot.procedures.yml`
  and profile stages in `evals/opencode-lane/profiles/*/profile.yml`.

## Prior-failure note

Attempts 1 (tony-omen, 11-17) and the macbook retry (11-20) died at
runner level — exit-code / provider rate-limit signatures before any
task work; nothing to repeat or fix in the approach itself.

lessons:
- Free model routes must be preflight-verified before queueing an
  opencode envelope — a dead route yields 0 tokens + missing_artifact
  and still consumes the attempt (ada-ocb canary, 2026-11-19).
- The lane's current stage is host-local state
  (~/.local/state/opencode-lane/stage.json on idc02), not in the repo —
  check card comms/preflight for the last-reported stage.
- waiting_cards.py only honors a top-level action.verifier, not
  lane_envelope.verifier — duplicate it on queued opencode cards.
