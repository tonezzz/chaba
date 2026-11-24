# Dispatch outcome — jev-pilot-decision-layer-for-card-triage-d47b53

Date: 2026-11-24 · Branch: `dispatch/20261124-155244-phase-1-today-run-jev-student-` · Commit: `4587aadbdf5`

## What was done

**Phase 1 — 10-card systemone triage (durable report shipped).**
New `scripts/jev/card-triage.py` asks each card three questions in one
`/v1/systemone` call — `lane` (choice over the 5 dispatch lanes,
criteria mirroring `classify_lane`), `priority` (score, 5-level
**list** criteria — dict 422s on openjev), `ready` (noul) — across
live backends, with the production keyword classifier's verdict as a
reference column. Ran 10 real backlog cards (fetched live from
board-api) against jev-student (`tony-omen:8780` distilmulti) and
student-1b (`tony-omen:8778` gemma-3-1b). Report:
`docs/reports/jev-card-triage-2026-11-24.md`; raw records:
`evals/results/jev/card-triage-2026-11-24.json`.

Findings: jev-student choice/score heads remain dead (`answer`@0.0 on
all 10, score collapses to the noul prob). student-1b produces real
choice distributions but argmax collapses to `devin` 9/10 (safe-default
prior — little added value over the classifier fallback); its priority
score is degenerate ("high"@0.96 on all 10). The production keyword
classifier showed live false-positives: 3 cards routed `free_lane` on
broad substring keywords (camwall-retire→"documentation",
spend-guardrails→"unit test", excise-jules→"installed"). heavy-4b is
not viable for batch triage (>300s per 3-question card call on CPU).

**Phase 2 — noul-gate agent skill.** `scripts/jev/noul-gate.py` (CLI:
exit 0 clear / 3 gate / 2 fail-open) + `.devin/skills/noul-gate/SKILL.md`
(the skill pattern: when to gate, backend table, polarity rule,
advisory-only semantics). Measured on live endpoints: only the
heavy-4b (`omen:8777`) discriminates destructive-op nouls correctly —
`rm -rf` prod repo p_safe=0.003 → GATE vs git-status/ls/restart
0.977-0.991 → CLEAR (~75s/call). jev-student-distilmulti is confirmed
domain-locked (p=0.006 → CLEAR on `rm -rf` prod — must NOT be the gate
backend despite the card spec naming it). The 1b students order roughly
but compress (rm -rf p=0.50 exact). Question polarity is load-bearing:
"is it SAFE to run unattended?" separates; the approval-phrased variant
made the 1b gate everything (git status p=0.75).

Runbook: `docs/ssot/jobs/bench/2026-11-24-jev-card-triage-noul-gate.yml`.
Card comms posted (progress + final).

## How to verify

- `python3 scripts/jev/card-triage.py --cards <json> --out out.json` —
  or re-run with `--backend name=url` arms.
- `python3 scripts/jev/noul-gate.py "git status"` (cheap arm:
  `--url http://100.75.102.88:8778`) and
  `python3 scripts/jev/noul-gate.py "rm -rf / prod path"` (default 4b,
  ~75s).
- Report table vs `evals/results/jev/card-triage-2026-11-24.json`.

## Notes / drift flagged

- idc03:8778/8779 dead; `ssot.audit.hosts.yml` still expects
  `jev-student.service` active on idc03 — stale vs the
  idc03-structural-capacity card (moved to omen:8780). Recorded in the
  runbook followups; not fixed here (SSOT edit belongs to the audit
  flow).
- jevos ad-hoc serve on idc03:8017 (from the 11-23 arena) is down
  again — still not a declared unit.
- Real Jev API arm still blocked on key (KNB-0822).

lessons:
- openjev ScoreQuestion.criteria must be a LIST of level descriptions — a dict returns HTTP 422; choice wants dict, noul wants dict.
- jev-student-distilmulti collapses choice AND score onto the noul head — any non-noul question returns degenerate output; check raw answers, not just labels.
- Noul question polarity is load-bearing: "needs approval?" made the 1b gate everything; "is it SAFE unattended?" separates correctly on the 4b.
- gemma-3-4b CPU openjev (~75s/question-call) is fine for single gates but >300s for 3-question card-sized states — don't use it for batch triage.
- prod lane classifier substring-matches keywords ('installed' hits 'install', 'unit test' hits specs mentioning tests) — single broad kws false-positive to free_lane; word-boundary matching exists only for manual/codemod lanes.
