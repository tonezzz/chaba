# decision-arena — 50-case labeled corpus run (2026-10-25)

Card: `decision-arena-benchmark-decision-models-72ab92` (BEN-0826)
Job spec: `docs/ssot/jobs/nest/2026-10-25-ada-nest-real-job-seq.yml` → job2_jev_arena_50
Run host: mn01 (dispatch worktree) — jev-student arm only; jevos (:8017
idc03-local, :8777 not reachable from mn01) and Laya (no declared env)
arms not run here. Previous 27-case run (idc03, morning): student
0.481 / jevos 0.667 overall.

## Corpus v2 (27 → 50)

`scripts/ops/decision-arena.py`, `--corpus-only` verifier output:

| family   | n  | notes |
|----------|----|-------|
| confirm  | 12 | noul — 6 true / 6 false; embedded-affirmation + Thai + negation edge cases |
| tool     | 16 | choice — remember 4 / recall 4 / control 4 / answer 1 / search 3 (expansion weighted here per job doc: backends diverged most on choice) |
| pipe     | 10 | noul — 4 valid edges / 6 reversed-invalid edges (v1 had only valid edges — single-class, measured nothing) |
| stag     | 12 | noul — 6 stagnant / 6 progressing incl. explore-vs-loop + retry-with-distinct-failures |

noul labels balanced 17/17 overall. Indexed case ids (no more
first-12-char collisions). `--corpus-only` exits nonzero on duplicate
ids, out-of-criteria labels, or single-class types.

## Results — jev-student (idc03:8778, jev-student-distilmulti)

| backend    | acc   | noul  | choice | n  | lat_p50 |
|------------|-------|-------|--------|----|---------|
| jev-student| 0.480 | 0.676 | 0.062  | 50 | 452.5ms |

Raw per-case records: `evals/results/jev/decision-arena-50.json`.

## Failure analysis (26 misses)

- **tool-routing: 15/16 misses, all answered `answer`.** The choice
  head collapses to one class regardless of the turn — "turn off the
  living room TV", "save to memory", "what's the latest on the flood"
  all come back `answer`. This quantifies the known dead choice head:
  6% on a 16-case spread. jev-student cannot be used for Choice-type
  routing at all.
- **pipeline-compat: all 4 valid edges judged false; all 6 invalid
  edges correctly false.** Rubber-stamps `false` on this family —
  accuracy 0.6 by coincidence, discrimination zero.
- **stagnation: 7/8 stagnant-true judged false** (progressing). Biased
  toward "still working" even on 14×-identical-call loops — the
  stagnation gate cannot delegate to jev-student.
- **confirm-gate: 12/12 correct**, including Thai affirmations,
  embedded-ok negatives, and the "can you confirm…?" trap. The noul
  head works in-domain for confirm semantics.

## Routing-gate input

jevos choice-accuracy is the declared gate before more autonomy
(0.875 on the 27-case corpus). The jevos arm could not run from this
host — **it must re-run on idc03 against corpus v2 before the gate
number is comparable** (v2 adds 6 invalid-edge pipe cases and 9 new
choice turns; v1's pipe score was inflated by the single-class flaw).

## Harness fixes shipped with this expansion

- Backend ping now actually gates: `ask()` returns `_err` instead of
  raising, so a dead endpoint previously meant 50×120s silent timeouts.
- Laya model loads once per run (was per-case).
- `--out PATH` writes per-case records for disagreement analysis;
  backend URLs env-overridable (JEV_STUDENT_URL/JEVOS_URL/LAYA_URL).

## Verifier / rollback

- Verifier: `--corpus-only` reports exactly 50 unique labeled cases,
  errors=[]; per-case JSON lands at `evals/results/jev/decision-arena-50.json`.
- Rollback: corpus is in-script data — `git revert` restores v1-27.
  No production path reads this harness (bench only).

## Next

1. Re-run the jevos arm on idc03 (JEVOS_URL=127.0.0.1:8017) — the
   routing-gate number for the card.
2. ECE/calibration needs raw noul probabilities — `--out` records
   labels only; add `p` capture when the Jev API key lands (KNB-0822).
