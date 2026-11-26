# Dispatch outcome — jev-code-decision-layer-construct-templa-77e184

Card: `jev-code-decision-layer-construct-templa-77e184` (OPS-0825)
Branch: `dispatch/20261124-154245-architecture-1-code-decision-s`
Commit: `7305e3b2a2` (8 files, +986)
Date: 2026-11-24, host tony-omen

## What was delivered (all three spec items)

**1. code-decision service** — `scripts/jev/code-decision.py`
- Input `{task, code, constraints[], candidates{name: rubric}}` →
  `Choice(which construct/template/library)` + three `Noul` gates scoped
  to the winner: semantics preserved, convention match, minimality.
- Wire shape `/v1/systemone` (same as decision-arena / jev-student / real
  Jev API). Interfaces: stdin-JSON/flags CLI, importable `decide()`,
  stdlib `--serve` (`POST /decide`, `GET /health`, default :8890 — 8790
  is a voice service on this host).
- Backend routing per question type: real Jev API (`JEV_API_URL` +
  `JEV_API_KEY`) → jevos (`JEVOS_URL`) → jev-student (`JEV_STUDENT_URL`).
  Stub detection (student choice head returns confidence=0.0), honest
  `degraded[]` + `backends{}` in every response, `assume_winner` lets the
  caller's own pick be gated when choice is down, and an OOD-collapse
  detector flags noul backends that return identical near-zero p for all
  gates (observed live: p≈0.005 ×3).

**2. agent skill** — `.agents/skills/code-decision/SKILL.md`
- Call before construct/template/library/replacement choices; skip for
  mechanical edits. Candidate-rubric rules (2–6 options, rubric text not
  bare names), verdict table for all six verdict states, live-verdict
  logging to `evals/results/jev/code-decision-live.jsonl`.

**3. eval pack** — `scripts/jev/code-decision-corpus.jsonl` (19
human-verified cases: 13 choice grounded in measured repo idiom counts —
urllib 261 vs requests 6, pathlib 353, f-string 510, argparse 322,
yaml.safe_load 181, subprocess 221, os.system 0, datetime 249/dateutil 0
— + 6 hand-labeled gate cases) and `scripts/jev/code-decision-eval.py`
(`--corpus-only` verifier, per-backend independent scoring, `--out`
JSONL records + `.summary.json`).

## Measured result (the honest part)

Ran the eval live 2026-11-24 (`evals/results/jev/code-decision-eval-20261124.*`):

- Only **jev-student** was reachable (tony-omen:8780). jevos down
  fleet-wide (was ad-hoc on idc03:8017, never declared); **no real Jev
  API key** (KNB-0822 still open).
- jev-student choice: **0/13** (all stubs, as known).
- jev-student gates: 3/6 nominal but **all 6 cases flagged
  `ood_suspect`** — the noul head ignores question text and returns
  p≈0.004–0.005 for every gate; the 3 "correct" are expected=false cases
  matching the universal low-p. Meaningless, exactly as the design doc's
  Phase-0 composer probe predicted.

**Verdict:** the layer's shape is delivered and verified end-to-end
(CLI, serve mode, degradation paths all tested live), but no current
backend can make a real code-decision. The eval pack is the instrument
that scores the real Jev API (or a declared jevos unit) the day either
lands. Job record: `docs/ssot/jobs/bench/2026-11-24-jev-code-decision-layer.yml`;
design doc updated with a phase-1 addendum.

## How to verify

```bash
python3 scripts/jev/code-decision-eval.py --corpus-only   # 19 cases, 0 errors
echo '{"task":"t","code":"c","candidates":{"a":"x","b":"y"}}' | \
  python3 scripts/jev/code-decision.py                    # honest degraded verdict
python3 scripts/jev/code-decision-eval.py --out /tmp/cd.jsonl   # live bench
```

## Follow-ups (on the job record)

- KNB-0822 real Jev API key → rerun eval for the real verdict.
- Declare jevos serve as a proper unit or mark bench-only (host hygiene)
  → would give a local choice head meanwhile.
- Grow `code-decision-live.jsonl` from real agent runs (skill instructs).

lessons:
- jev-student's noul head ignores question text entirely — out-of-domain it returns identical p≈0.005 for every question; always check for collapsed/identical gate probabilities before trusting noul verdicts.
- tony-omen port 8790 is already a voice service — code-decision --serve defaults to 8890.
- Write-tool path typos can silently create stray directory trees outside the worktree — verify absolute paths before writing.
- eval --out flag colliding summary+records into one file — separate `.summary.json` suffix pattern works.
