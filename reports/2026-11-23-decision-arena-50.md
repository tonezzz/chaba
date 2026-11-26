# decision-arena — 3-backend run on corpus v2 (2026-11-23)

Card: `decision-arena-benchmark-decision-models-72ab92` (BEN-0826)
Harness: `scripts/ops/decision-arena.py` (corpus v2 = 50 labeled cases)
Run host: idc03 (dispatch worktree on tony-dell drove it over ssh).
Arms: **jev-student** (tony-omen:8780, jev-student-distilmulti),
**jevos** (idc03:8017, jevos-v5 openvino-int8, `./jev serve`),
**laya** (in-process, `convaiinnovations/laya` 0.5.3, CPU torch 2.15).
Real Jev API arm: not run — no key (KNB-0822 still open).
Cost: all three backends self-hosted → $0 marginal.

Spec drift found and corrected this run: card spec still says
jev-student idc03:8778 — it migrated to tony-omen:8780 on 2026-11-18;
idc03:8778/8779 are dead. jevos binary+model were absent fleet-wide;
re-fetched `feder-cr/jev` release to `idc03:~/jev-bench/` and serving
on 127.0.0.1:8017. Laya needed a declared env → `idc03:~/.venvs/laya-bench`
(CPU torch). Harness defaults already match these addresses.

## Results

| backend     | acc   | confirm | tool  | pipe  | stag  | noul ECE | choice ECE | lat p50 | lat p90 |
|-------------|-------|---------|-------|-------|-------|----------|------------|---------|---------|
| jev-student | 0.480 | 1.000   | 0.062 | 0.600 | 0.417 | 0.325    | —          | 40.5ms  | 48ms    |
| jevos       | 0.720 | 0.500   | 0.812 | 0.600 | 0.917 | 0.120    | 0.260      | 752.5ms | 2264ms  |
| laya        | 0.540 | 0.500   | 0.625 | 0.400 | 0.583 | 0.306    | 0.211      | 2959.5ms| 6295ms  |

(acc = overall; family columns = per-family accuracy. noul ECE over the
34 noul cases using raw `noul` probabilities; choice ECE over the 16
tool cases using per-option `probabilities` — jev-student emits no
distribution, so its choice ECE is undefined.)

Raw per-case records (150 rows, incl. raw answer objects):
`evals/results/jev/decision-arena-50-20261123.json`.

## Failure signatures — each backend fails differently

- **jev-student**: confirm-gate perfect 12/12 (incl. Thai + embedded-ok
  traps). Choice head still dead — 15/16 tool cases collapse to
  `answer` at confidence 0.0. Pipe rubber-stamps `false` on all 4 valid
  edges (p≈0.004 — confidently wrong). Stag under-detects: 7/8
  stagnant-true judged progressing (p≈0.004).
- **jevos**: best overall. Stag 11/12, tool 13/16. **But confirm-gate
  is inverted-weak**: 5/6 true affirmations scored p=0.17–0.42 (under
  the 0.5 threshold) plus one false-positive on "confirm delete the old
  page" (p=0.72). Pipe same false-bias as student on valid edges
  (p≈0.35–0.38, borderline). Choice ECE 0.260 — overconfident picks.
- **laya**: middling everywhere, mirror-image biases — pipe
  rubber-stamps `true` on all 6 INVALID edges (p≈0.96–0.98), stag
  over-flags progressing trajectories as stagnant, confirm leans
  toward affirmation. Slowest by 4–40× (CPU torch, p50 ~3s).

## Routing-gate read

- Tool-routing gate: **jevos 0.812** is the only usable choice head;
  student (0.062) and laya (0.625, low-confidence) are not.
- Confirm-gate: **jev-student 1.000** remains the only correct arm;
  jevos would silently drop most real confirmations at threshold 0.5.
  A threshold sweep on jevos noul outputs might recover it (true-class
  p's cluster 0.17–0.42) — post-hoc, unverified.
- Stagnation gate: **jevos 0.917**; student (0.417) and laya (0.583)
  both unreliable.
- Pipeline-compat: nobody solves it — student/jevos bias false, laya
  biases true. 10 cases may be too subtle for these backends, or the
  edge semantics need richer state than "Block A: x. Block B: y."

## Harness changes shipped

- `--out` records now carry `raw` (full answer object → probabilities
  for ECE) and laya writes per-case records like the HTTP backends
  (previously aggregate-only).

## Verifier / rollback

- `python3 scripts/ops/decision-arena.py --corpus-only` → 50 cases,
  errors=[] (noul balanced 17/17).
- Reproduce: on idc03,
  `~/.venvs/laya-bench/bin/python scripts/ops/decision-arena.py --out <path>`
  (defaults already point at omen:8780 student + 127.0.0.1:8017 jevos).
- Rollback: harness is bench-only; `git revert` restores prior records
  format. jevos serve on idc03:8017 is a manual `./jev serve` process —
  not a declared unit (host-hygiene gap, see Next).

## Next

1. Declare jevos as a unit/env on idc03 (currently an ad-hoc process
   from `~/jev-bench/jev`) or document it as bench-only.
2. Jevos confirm-gate threshold sweep before any routing use.
3. Real Jev API arm still blocked on key (KNB-0822).
4. ECE for choice needs per-option probabilities — student emits none;
   consider a temperature/calibration pass if student is ever revived.
