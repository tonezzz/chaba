# dispatch-outcome — dispatch-prompt-budget-measure

Card: `dispatch-prompt-budget-measure` (parent `devin-usage-reduction`,
DEV-0044 lever 4). Read-only measurement — no dispatch-path code
changed.

## What was done

- Pulled `devin-usage.py --fleet --days 30 --json`: 494 sessions
  (idc02 186, tony-omen 175, tony-dell 98, mn01 35). **idc01
  unreachable** (ssh timeout); **idc03 = 0 in-window** — all its Nov
  dispatches rate-limit-died before transcript write. 62/494 sessions
  have empty final_metrics.
- Joined all 494 rows to per-host task dirs (prompt.txt bytes, spec
  bytes, KNOWN_PITFALLS/KNOWN_GOOD line+byte counts, attempt_n,
  run-log count, meta result/exit_code, transcript steps + wall span).
- Outcome-classified a sample of all 44 top-decile sessions + 40 random
  median-band sessions via remote git merge-state probes + task-anchored
  card comms slices (archive-aware card index).

## Headline numbers

- 432 metriced sessions = **1.89B prompt tokens**, 90.7% cached,
  26,276 steps → avg 72k tokens/step. Median session 3.45M / 57 steps.
- **steps ↔ prompt tokens: r=+0.96** — the sole real driver.
  spec_bytes r=+0.06, prompt.txt bytes r=+0.07, primer_bytes r=+0.07,
  attempt_n r=+0.07 — all noise.
- Fixed per-step context floor measured 22–32k tokens/step (system +
  rules + skills + MCP descriptions + ~37KB tool_definitions) ≈
  **31–40% of all prompt tokens** is fixed resend.
- Top decile = long sessions (steps p50=112), not big prompts.
- Non-landing outcomes ≈19% of sampled tokens.
- attempt≥2 retries = 58 sessions / 231.8M (12.3%).

## Deliverables

- `docs/reports/dispatch-prompt-budget-2026-11.md` — full report: dataset,
  distributions, correlations, outcome table, cap proposals.
- `docs/ssot/jobs/devnest/2026-11-25-dispatch-prompt-budget-measure.yml`
  — job doc.

## Cap proposals (evidence in report)

1. Step-budget gate: steps>100 excess ≈84.7M/30d (4.5%); >80 ≈215.6M
   (11.4%). Warn-wrap ~80, ceiling ~150.
2. Dispatch-lite context profile: −20KB fixed ≈140M/30d (~7.4%).
3. Deliverable-checkpoint rail for long sessions (~19% non-landing
   sample share — estimate).
4. Formalize 2-attempt ceiling → scoping escalation.
5. Rejected: spec-length caps, tighter primer, per-host quotas.

## Verify

`python3 scripts/devin/devin-usage.py --fleet --days 30 --json`
reproduces the dataset (idc01 reachability permitting). Report has the
full method + caveats.

lessons:
- devin-usage.py --fleet only sees sessions with transcript.json + parseable meta.json; rate-limit deaths leave run.N.log + exit_code but no transcript — they count as sessions with 0 tokens.
- meta.finished_at is only stamped by devin-dispatch-watch; unstamped metas fall back to started_at, so wall-time must come from transcript step timestamps (t_first/t_last).
- Done+verified cards leave /cards dump — archived cards live in docs/ssot/kanban/cards/archive/*.yml; outcome joins need the archive index.
- Card comms 'at' is +07:00 minute-precision; per-session outcome attribution works by anchoring on the comm containing the task's YYYYMMDD-HHMMSS id, not by wall-clock window.
