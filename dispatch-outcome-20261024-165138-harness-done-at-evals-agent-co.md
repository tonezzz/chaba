# Dispatch outcome — ai-workforce-eval m1 rescore (idc02 → dell ~/evals)

## What I found

- The eval harness lives on **tony-dell** `~/evals` (agent-cost-bench, uv tool).
  The card spec's "pilot running" was stale: the flash-lite pilot finished
  Oct 23 (all 8 cells timeout @1800s); the frontier had moved to a new
  `m1-behavioral` verifier authored 16:49 by a concurrent dell session, which
  also launched a live Fable run at 16:54 while I worked.
- **Verifier sanity (independently re-verified in /tmp/m1b-verify):** parent
  ed1ff11 = 0.5 (hardcoded-healthy bug caught), reference fix c0850f0 = 1.0.
  Bidirectionally sound — with nuance: parent's `IsHealthy()` exists but uses
  the banned time-since-last-entry semantics.

## What I changed / produced

1. **Rescored every m1 attempt workspace** under the new behavioral gate
   (restored verifier-clobbered test files to HEAD first):
   paid lane = **3/4 real attempts fully correct** (fable-r1, or3-r1,
   or-openhands), 1/4 real partial (or3-r2: client fixed, handler not wired).
   Old coupled verifier had recorded 0/7 — compile-boundary conflation.
   Full table: `dell:~/evals/m1-behavioral-rescore-20261024.md`.
2. **Corrected devin-kb** `docs/tools/ai-workforce-eval.md` (commit b8258e5,
   local): fable-r2 had zero edits (the "131-line" was injected-test diff);
   the fresh m1beh-fable 0.5 was an **OpenRouter 402 credit exhaustion**
   (weekly key cap ~spent at 16:55), not a capability result.
3. **Board comments ×2** on ai-workforce-eval: corrected matrix + verifier
   caveats. **OR paid lane is DOWN until ~Oct 26 reset or key raise** —
   card ask #1 is now the live blocker.
4. **Filed card BEN-0828** `bench-verifier-inject-clobber`: score.py injects
   held-out tests by filename → overwrites tracked repo tests + leaves
   contaminating residue (r2 build-failed on stale injected tests until
   restored). m2 needs the same behavioral-task treatment.
5. **SSOT trail**: `docs/ssot/jobs/bench/2026-10-24-m1-behavioral-rescore.yml`.

## How to verify

- `ssh dell 'cat ~/evals/m1-behavioral-rescore-20261024.md'`
- `ssh dell 'cd /tmp/m1b-verify && python3 ~/evals/tasks/m1-behavioral/verify/score.py
   parent ~/evals/tasks/m1-behavioral'` → 0.5; same on `fix` → 1.0
- devin-kb log: `cd ~/CascadeProjects/devin-kb && git show b8258e5`

## Caveats

- I injected `behavioral_test.go` into 4 historical workspaces while scoring
  (verifier's normal side-effect; noted for the next reader).
- devin-kb commit is local-only (no push — concurrent dell session pushes).
- m2 rescore NOT done — needs its own m2-behavioral task (same clobber pattern).
