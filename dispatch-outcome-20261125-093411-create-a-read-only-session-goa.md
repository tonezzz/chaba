# Dispatch outcome — openchamber-session-goals-adobe-stock-qc

**Result: COMPLETE (goal defined + verified contract).** Created Session
Goal `adobe-stock-reuse-qc-v1` — a read-only OpenChamber goal for Adobe
Stock reuse QC — with a machine-readable contract, held-out verifier, and
runbook. Commit `095db624f8` on `dispatch/20261125-093411-create-a-read-only-session-goa`
(not pushed, per dispatch rules).

## What changed

New `evals/adobe-stock-session-goal/`:

- `GOAL.md` — the Session Goal text: named campaign idea `"remote work
  home office"`, one `ada_adobe_stock_reuse(campaign_idea, compact=false)`
  MCP report call (1 retry max), candidate listing with verbatim
  provenance (`sha256/provider/job_id/source_ref/campaign_id`),
  missing-preview + open-question flags, three required artifacts
  (`adobe-stock-reuse-report.md`, `adobe-stock-reuse-report.json`,
  `run.json`), explicit stop conditions, and hard boundaries (no cards,
  uploads, generation, licensing, publishing, git, restarts).
- `goal.json` — machine-readable mirror: allowed calls, forbidden
  actions, artifact contract, `stop_when`, acceptance checks (incl.
  `expected_goals`-style file/command checks matching `scripts/lib/goals.py`
  grammar), recording requirements (`turns`, `cost_usd` null-allowed,
  artifact paths, `stop_reason`).
- `verify.py` — held-out verifier: artifact presence, JSON contract,
  report-call capture, per-candidate key/enum/provenance checks,
  no-duplicate/hallucinated asset ids in `missing_previews`, clean policy
  block, `no_mutation_receipt`, and `run.json` turn/cost/stop_reason
  recording. Exit 0/1.
- `fixtures/sample-out/` — contract-valid example built from 3 real
  provenance records of campaign `AS-2026-11-05-REMOTE-WORK-001`.
- `README.md` — how to run on idc02 OpenChamber (ada-ocb profile) and how
  to verify/interpret results, incl. honest `blocked:*` stop handling.
- `docs/ssot/jobs/devnest/2026-11-25-openchamber-session-goal-adobe-stock-qc.yml`
  — job trail with the full goal contract and open questions.

## Verification performed

- `python3 verify.py fixtures/sample-out` → **pass**, 34/34 checks.
- Negative test (mutated policy flag, emptied provenance sha256,
  hallucinated missing-preview id) → **fail** with named hard_failures
  (`policy_clean`, `provenance_fields_ok`,
  `missing_previews_known_ids`, `candidate_field_errors`).
- Pre-commit SSOT validation passed on the jobs yml.

## Honest scope note

The card's acceptance ("the agent stops when …; cost, turns, and final
artifact are recorded") describes how the **goal** must behave when run.
This dispatch could only *create* the goal — no opencode/ocb executor
exists on mn01, and driving a live OpenChamber session on idc02 is a
separate step (runbook in README.md). The goal's stop conditions are
encoded and mechanically checkable; the live end-to-end run remains the
card's open verification step.

## How to verify

```
cd evals/adobe-stock-session-goal
python3 verify.py fixtures/sample-out   # -> verdict pass
# live: run GOAL.md in an ada-ocb OpenChamber session on idc02, then
python3 verify.py <session-artifact-dir> # + check run.json stop_reason
```

Card comms posted with outcome + locations.

lessons:
- "Session Goals" has no existing repo artifact — the deliverable for this card class is the goal definition itself (prompt + machine-readable contract + verifier), not a code change; check for an executor on the host before assuming a live run is possible (mn01 has no opencode/ocb; idc02 does).
- `ada_adobe_stock_reuse` is the ada-ocb MCP surface for Adobe Stock reuse reports (ssot.tools.yml `media.adobe_stock_reuse`); its sig is `ada_adobe_stock_reuse(campaign_idea, compact)`.
- Reusing the adobe-stock-multirun provenance/preview_status/policy vocabulary keeps goal artifacts consistent with the already-verified eval contract.
- board-api `/comment` worked first try this session; the lock-saturation retry note from prior dispatches did not trigger.
