# Dispatch outcome — nest-opencode-executor-eval (idc02, 2026-10-28)

## What was done

Evaluated opencode as a general Ada Nest job executor by building and
running the MEM-0871 mddb prune/compact checkable-sequence eval
template end-to-end through the existing graduated lane (S1).

**Shipped (all in this worktree):**
- `scripts/devnest/mddb_probe.py` — read-only bounded mddb probe
  (banks/health/vector-stats/config/expired-scan; GETs + read-only
  search paging only). The sole network tool in the profile's bash
  allowlist.
- `evals/opencode-lane/profiles/mddb-sequence/` — task-scoped profile
  (`profile.yml` + `fixture/{task.yaml,prompt.md,verify.py}`) for
  checkable-sequence runbook plans.
- `evals/opencode-lane/jobs/p1-mddb-sequence-idc02.yaml` — S1 envelope.
- `evals/opencode-lane/out/p1-mddb-sequence-plan.json` — landed
  artifact: 4-bank inventory + 5 retention rows + 7-step plan (all
  mutating steps executor=human, every step carries a check).
- `evals/opencode-lane/runs/p1-mddb-sequence-idc02-20261028-12{5038,5158}/`
  — run evidence (manifest, events, verdict, run.json).
- `evals/opencode-lane/reports/2026-10-28-executor-eval-mem0871.md` —
  full assessment.
- `docs/ssot/jobs/devnest/2026-10-28-nest-opencode-executor-eval.yml` —
  durable trail.
- `tests/devnest/test_opencode_profiles.py` — inventory lists updated
  for the 5th profile/job (53/53 pass).

## Results

- Run 1: `missing_artifact` — flash-lite early-stop after 7 clean
  calls; caught deterministically, escalated, 0 denials. ($0.005, 55s)
- Run 2: **PASS — 216/216 held-out verifier checks.** Live-recomputed
  bank health, complete collection inventories (2%/10-doc tolerance),
  retention rescans, plan structure + coverage. 0 denials / mutating /
  peeks / scope violations. ($0.005, 91s)
- **Verdict: opencode is viable TODAY for verified read-only +
  planning jobs** inside the gate stack; mutating/production classes
  correctly remain outside. Trust comes from profile surface + bounded
  probe + recompute verifier, not the model. Early-stop is the dominant
  cheap-model failure mode and is never silent.

## Notable findings

- S1 quota now 3/3 — next `lane_gate.py review` decides S2.
- Dispatch env's `LITELLM_KEY` on idc02 is stale (401);
  `litellm-chaba.env` holds the working key — noted as an `arm_env`
  hardening candidate.
- `escalation.max_retries` exists but `cmd_run` has no auto-retry on
  `missing_artifact`.
- Board: result comment posted to `nest-opencode-executor-eval`.

## Verify

```bash
python3 -m unittest tests.devnest.test_opencode_profiles   # 53 OK
python3 scripts/devnest/opencode_profiles.py lint mddb-sequence
cat evals/opencode-lane/reports/2026-10-28-executor-eval-mem0871.md
cat evals/opencode-lane/runs/p1-mddb-sequence-idc02-20261028-125158/verdict.json
```
