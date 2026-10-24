# Dispatch outcome — ai-workforce-eval: m2-behavioral verifier + BEN-0828 close-out (idc02 → dell ~/evals)

## What I found

- Harness on **tony-dell** `~/evals` confirmed; no active runs at session
  start (last finished 13:06:57 UTC).
- **OR paid lane still DOWN**: all four latest Fable runs (m2 12:18 UTC,
  m1-behavioral ×3 12:46–13:06 UTC) died on OpenRouter 402
  `openrouter_key_limit` ("requested 32000 tok, can only afford
  27739/30047"). The 452s m1beh run explored for 7.5 min then died
  mid-run — "zero edits" is credit truncation, NOT the capability
  verdict devin-kb recorded. Corrected in devin-kb.
- Concurrent dell session had already: added the 3rd m1-behavioral test
  (idle-lag semantics), applied zz_heldout_ prefix to m-task injectors,
  rewritten m2's held-out test — but that test still required
  reference-fix internals (`verifySnapshot`, `swapDatabaseVerified`) →
  same coupling class that invalidated m1 scoring.
- `eval-m1-behavioral` T4 pack staged 19:48 ICT, still **unclaimed**
  (Colab worker idle; will run on next worker).

## What I changed

1. **m2-behavioral verifier shipped** (`tasks/m2-mddb-snapshot-proof`):
   new `tests/behavioral_m2_test.go` — interface-agnostic, uses ONLY
   parent-commit symbols. Discriminator fixture: synced-freelist bolt DB
   + corruptBranchPage → file opens but fails tx.Check(). Tests:
   `rc.replaceDatabase(bad)` must pass (open-only snapshot path),
   `s.restoreFromBackup(bad)` must fail (untrusted keeps full check),
   healthy snapshot installs. Coupled held-out file retired to
   `.coupled`; score.py RUN → `TestZzBehav`.
   **Control: parent 60ac37c = 0.667 (bug caught), fix 497b982 = 1.0.**
2. **BEN-0828 completed**: both-era residue purge (zz_ + bare-name,
   git-status-guarded — only `??` files matching held-out names removed)
   in m1-behavioral/m1/m2 verifiers; tracked-file backup/restore
   (`.preheldout`) in t1-hint/t1/t2 (t2 collides with 7 tracked terrology
   tests). Verified on the contaminated /tmp/m1b-verify/fix ws → 1.0.
3. **devin-kb updated** (local commit `fb3830e` on dell): new section
   "m2-behavioral verifier + residue purge" — records the verifier,
   BEN-0828 completion, and corrects the 402-vs-capability conflation in
   "Fable honest m1/m2 verdicts".
4. **SSOT trail**: `docs/ssot/jobs/bench/2026-10-24-m2-behavioral-verifier.yml`.
5. **Board**: status comments on ai-workforce-eval + bench-verifier-inject-clobber.

## How to verify

- `ssh tony-dell 'python3 ~/evals/tasks/m2-mddb-snapshot-proof/verify/score.py
  /tmp/m2b-verify/parent ~/evals/tasks/m2-mddb-snapshot-proof'` → 0.667;
  same on `fix` → 1.0
- `ssh tony-dell 'cd ~/CascadeProjects/devin-kb && git show fb3830e'`
- Residue purge: re-run any m-task verifier twice on one workspace —
  second run must not see stale zz_/bare-name files.

## Caveats / next

- m2-fable agent ws scores 0.0 (uncompilable tree — its TDD tests
  reference the fix it never landed; 402-truncated run). Honest score.
- Paid-lane m1/m2 verdicts still need rerun post ~Oct 26 OR reset —
  every Fable datapoint today is credit-truncated.
- t-task restore happens only on the success path (early `emit` exits
  skip it — rare; noted).
- Post-run tidy of injected zz_ files still open on BEN-0828 (cosmetic;
  pre-run purge covers contamination).
- devin-kb commit is local-only on dell (convention: writer session pushes).
