# dispatch outcome — nest-micro-training (agent-owned train→bench→promote loop)

## What the card asked

Five deliverables for the Nest micro-model evolution loop: per-specialist
task suites (golden/hard/adversarial), a model registry, named training
lanes, a loop owner, and a promotion gate in the CAM++/client_noul
shadow posture.

## What changed

**ada-pi** (worktree `dispatch-wt-20261007-211928-1-task-suites-per-specialist-ada-pi`,
branch `dispatch/20261007-211928-1-nest-micro-training`, commit `ca9bcde` —
NOT pushed/merged; needs merge to ada-pi main to go live on the prod checkout):

- `tests/bench/suites.yml` — per-specialist tier registry. Four
  specialists (confirm-gate, tool-routing, memory-bank, dispatch-triage),
  each with golden (frozen regression, never trained on), hard (rotates
  in from corpus harvest), adversarial (frozen attack-shaped) tiers
  resolved to `orch-bench --sets` names. Rotation policy
  (into_hard/into_golden/into_adversarial) + promotion gate + bench
  invocation documented in-file.
- `tests/bench/orch-adv-confirm-cases.jsonl` (21 rows) +
  `orch-adv-tool-cases.jsonl` (14 rows) — seeded adversarial tiers.
  Immediately discriminating: champ scores 12/21 adv-confirm vs 10/10
  golden (meta-references, imperative bait, relayed/Thai affirms,
  `yesn't`, trailing negation false-fire; `y`/`k`/`mm-hmm`/`affirmative`
  under-fire — the v6 target list).
- `tests/bench/topologies.yml` — new `models:` registry (task,
  checkpoint, corpus version, bench scores, status
  train|shadow|prod|retired): jev-student-v5 first entry (prod, live-
  measured golden 10/10, hard 27/35, adv-confirm 12/21, p50 0.07s) +
  gemma-3-1b/4b zero-shot lanes + jev-gemma-head-v1 (train). New
  `lanes:` section: tony-omen GTX1650 (distilbert FT ~11min, 1b LoRA via
  4-bit), colab-mcp burst (bigger runs, jev/*-colab.ipynb), idc01 cold
  batch (post-retirement role + pre-migration corpus archive).
- `tests/bench/orch-bench.py` — `--suite <name>` expands a suites.yml
  specialist to its non-spec tier sets (narrows default 'all');
  unknown suite exits 2 with valid keys.
- `scripts/serve-jev-student.py` — `JEV_CKPT` env override.
- `scripts/train-jev-student.py` — `JEV_OUT` env override.

**chaba** (this worktree, branch `dispatch/20261007-211928-1-task-suites-per-specialist-l`):

- `scripts/ada/nest-train-loop.py` — the loop owner:
  harvest (idc03 live + idc01 archive corpora over ssh) → merge
  (merge-corpus.py + augment-corpus.py) → train (open-jev venv, GTX1650)
  → serve candidate on 127.0.0.1:8878 via JEV_CKPT → orch-bench
  champ-vs-candidate over suite tiers → gate (cand >= champ every tier,
  zero case-level regressions) → publish `bench/train-*` doc to
  ada-ha-scenario-reports → board request on the owning card only when
  the gate passes. Never deploys, never restarts prod, never edits the
  registry. Exit 0 on gate FAIL — a rejected candidate is normal.
- `docs/ssot/infrastructure/ssot.nest-training.yml` — spec layer:
  stages, corpus sources, the label gap (106 diverged rows pending
  labels — the real corpus-growth bottleneck), lane posture, promotion
  gate, shadow posture citation.
- `docs/ssot/jobs/ada/2026-10-07-nest-micro-training.yml` — trail.

## End-to-end verification (real run, tony-omen GTX1650)

`nest-train-loop.py` ran the full loop tonight:

- harvest: 4280 live rows (idc03 783 post-migration + idc01 3483
  archive), 1205 mined, 33 reviewed; 106 diverged pending labels.
- merge: 3540 train rows (322 pos) + 1295 aug.
- train: distilbert FT, 756 steps / 17 min on the 1650, val acc 0.974.
- serve+bench: candidate on :8878 vs champ on idc03:8778.
- result: **gate FAIL, correctly** — golden 10/10 = champ, adv-confirm
  13/21 (+1), but hard 26/35 (−1) with case-level regression
  `mm hmm go for it`. No promotion request queued; candidate archived
  under `~/jev-student-candidates/jev-student-v6-cand-20261007-215016`.
- doc: `ada-ha-scenario-reports` key `bench/train-20261007-220823`
  (kind:benchmark, gate:fail) — published.

The loop demonstrated the gate doing its job: trading a hard-set
regression for an adversarial gain does not promote.

## Findings recorded

- `scripts/jev-retrain.sh` is stale post-migration — it harvests corpus
  from idc01 and trains on idc02; the live corpus moved to idc03. The
  new loop supersedes it; worth a comment/redirect in a follow-up.
- Label gap: diverged corpus rows (106 and growing) are excluded from
  training until labeled — that queue is what actually grows the
  corpus. An arbiter-label pass (L2/L3 adjudicate + spot check) is the
  next iteration; noted in ssot.nest-training.yml open_questions.
- transformers 5.17 in the open-jev venv ran train-jev-student.py
  unmodified.
- tool-routing/memory-bank/dispatch-triage suites are registered but
  have no trained incumbent (student choice head is a stub — 4/20 toolx
  is the baseline to beat). The multi-question successor is a
  gemma-3-1b LoRA on the colab lane.

## How to verify

```bash
# chaba side (merged with this dispatch branch)
python3 scripts/ada/nest-train-loop.py --harvest-only --no-publish

# ada-pi side (in the worktree until merged)
cd /home/tony/CascadeProjects/dispatch-wt-20261007-211928-1-task-suites-per-specialist-ada-pi
python3 tests/bench/orch-bench.py --suite confirm-gate --structure student \
    --student http://100.102.134.91:8778

# mddb doc
curl -s http://100.102.134.91:11023/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"ada-ha-scenario-reports","key":"bench/train-20261007-220823","lang":"en"}'
```
