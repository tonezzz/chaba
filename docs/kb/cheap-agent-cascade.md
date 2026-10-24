# Cheap-agent cascade — full design (OPS-0810 / BEN-0811)

Tony's ask (2026-10-24): *"can we train cheap models for very specific
tasks, JEV chooses which to process/cascade/group/team nest style, big
model last resort — also for dev + hermesbot/clawbot."*

This is the design doc. Companion lesson: `cheap-agent-cascade` in
Education (WP lesson CPT). Evidence base: OPS-0792 (workforce eval),
OPS-0809 (pattern library, codemod 7/7), OPS-0823 (lane delegation
procedure pilots), edu-agent-benchmark, jev-code-decision.md
composer probes, OR :free scorecard.

---

## 1. The claim being tested

> A routed cascade of cheap lanes, entered at the *predicted* cheapest
> passing level and escalated only on gate failure, matches the frontier
> pass-rate at a fraction of the frontier cost — PROVIDED every lane has
> a cheap, honest verifier.

The cascade is not "start at the bottom and climb." It is
**entry-level prediction + gate-gated escalation**. On a task the
router predicts L3 will need, it dispatches L3 directly — a blind
L0→L1→L2→L3 chain on a hard task costs *more* than frontier-only
(wasted cheap attempts + latency).

## 2. Pipeline shape

```
task ─► feature extract ─► ROUTER (entry-level predictor)
   │        ▲                              │
   │        │ cascade-outcomes log (P5)    ▼
   │        │                    ┌─ L0 codemod ─gate─┐
   │        │                    ├─ L1 cheap local ─gate─┤
   │        └─ mined patterns    ├─ L2 flash-lite ──gate─┤ pass►done
   │                             └─ L3 frontier ────gate─┘
   └── gate fail ─► escalate one lane, record (task,lane,verdict,cost)
```

Two planes, kept separate:
- **work plane**: the lane that does the task (codemod, agent+model)
- **decision plane**: router Choice + per-action Noul gates + the
  verifier that decides pass/escalate. jev-student / real Jev /
  deterministic checkers live here — they never write work output.

## 3. Lane inventory (all measured, 2026-10-23/24)

| lane | what | cost | latency | proven on | fails on |
|---|---|---|---|---|---|
| L0 | deterministic codemod from pattern library (mddb `code-patterns`, P3 codemod arm) | $0 | 0.7s | t1: **7/7** — beats every model lane | anything without a matching pattern |
| L1a | jev-student (DistilBERT confirm-gate, idc03:8778 `/v1/systemone`) | $0 | ~ms | in-domain Noul 10/10 | choice head dead; zero OOD generalization — **decision plane only** |
| L1b | hermes3:8b (omen ollama, adopted T1 tool-call slot: native 80%, prompted-JSON 100%) | $0 | ~11-15s/call | tool-loop shapes | edu F1 0.545 — too weak alone |
| L1b | qwen3:8b (colab T4 / ollama) — tool-capable | $0 | T4 ok; omen CPU too slow for loops | t1 6/7 zero-edit on CPU | CPU agent loops |
| L1b | gpt-oss:20b (T4/omen) | $0 | 14.7-16.1s p50 (T4), ~78s omen CPU | edu **13/13, F1 1.0** on T4 | latency-bound on CPU — batch/async only |
| L1c | OR :free rotation (GhostRoute) — super-vl/laguna-s composite 100, flint 85 | $0 | 1-5s | side-tool composite (classify/JSON/routing) | unreliable by design — never alone on gated work |
| L2 | gemini-3.5-flash-lite via LiteLLM proxy | ~$0-quota | 13s (o1), ~167s (t1) | o1 1.0; single-step verifiable ops; edu current pipeline 5.0 draft-Q | multi-step remote diag (loses thread); t1 6/7 |
| L3 | fable-5.1 (OR/native), Gemini OR paid, Devin | $$$ | 60s (fable t1) | t1 7/7; only lanes that explain their fix; real correct Go edits on m1/m2 | cost; OR weekly key cap already burned once |

## 4. The router

Output: **entry lane ∈ {L0,L1,L2,L3}** (entry-level prediction), not a
binary per-lane decision. Objective:

```
entry = argmin_L  cost(L) + P(fail | task, L) · E[cost of path above L]
subject to predicted pass-rate contribution keeping fleet pass ≥ frontier baseline
```

Inputs: family label, pattern-match hit + confidence (JEV matcher top-k
over `code-patterns`), estimated step-count, target host, per-
(family,lane) historical pass rates from the outcome log.

### Router versions (same interface, increasing quality)

- **v0 rules** (build first — it's the bench's arm-B router):
  pattern-hit ≥ threshold → L0; single-step verifiable chore → L2;
  classify/JSON shape → L1c/L1b; multi-step or novel-code → L3.
- **v1 learned per-family classifier**: features = task embedding
  (nomic local) + metadata (repo, file-types, step estimate); trained
  on the cascade-outcomes log + mined patterns (P5). Small model —
  logreg/GBM, not an LLM — this is the "per-task classifiers from mined
  patterns" deliverable.
- **v2 JEV router**: real Jev API `Choice` over a shortlisted lane set
  ($0.042/MTok, ~100ms; needs key — jev-pilot card KNB-0822), Noul
  pre-gate on risky actions. Local fallback = jevos with
  precondition-rich criteria + agent-side shortlist pruning (composer
  probes v2-v4: usable, imperfect). jev-student stays in-domain Noul
  only — probes proved it cannot fill any other slot.

## 5. Gates — the part that decides everything

A lane attempt ends in a **verdict from a cheap verifier**, not the
agent's self-report. Without gates the cascade amplifies noise.

| family | gate | status |
|---|---|---|
| dev (t1/t2/m1/m2) | held-out tests | works for t1; **m1/m2 biased** — tests couple to original internals (rc.connected); **t2 has no verifier** (0/0 no-op). Fix = behavioral verifiers + mockable interfaces before bench |
| chores (o1-o4) | inline verifier script → score 0..1 (o1 health.json shape) | proven; needs o2-o4 written |
| edu | capture-F1, dedupe, sched/ops, recall, draft-Q (fixed flash-lite judge), loop completion | proven — bench-edu-manage.py, 13-task fixture, mock WP store |

Plus two cross-lane gates: **Noul pre-action gate** on destructive ops
(jev-student in-domain today), and **stagnation gate** (BEN-0824:
CONTINUE/REPLAN/HALT inside agent loops — bounds wasted spend).

## 6. The experiment

### Families / corpus
- **dev**: t1 (terrology predicate), t2, m1/m2 (mddb Go replication) —
  archaeology tasks w/ held-out tests, `~/evals` harness
- **chores**: o1 (endpoint-health) + o2-o4 ops chores w/ inline verifiers
- **edu**: bench-edu-manage.py fixture — F1/dedupe/draft-Q/sched/recall/loop

### Arms
- **A — frontier-only**: every task → L3. Sets the pass-rate ceiling
  AND the cost ceiling.
- **B — cascade w/o patterns**: router v0, lanes L1→L3, no L0, no
  learned classifier.
- **C — cascade w/ patterns**: L0 enabled (matcher + codemod), router
  v1 trained on accumulated outcomes.

### Metrics
- **Primary: CASCADE COST** = Σ cost of every lane attempt on a task's
  escalation path (router cost included — ~0 local, ~$0.0000x Jev).
  Arm metric = mean cascade cost per task.
- **Constraint**: arm pass-rate ≥ arm-A pass-rate (the frontier
  baseline). A cheaper arm that passes less fails the experiment.
- Secondary: p50/p95 latency per task, escalation rate per lane, gate
  precision/recall (false-pass = worst failure mode), and for edu the
  fixture subscores.
- Report head-to-head per family and pooled.

### Repeats (P4 — mandatory)
≥3 reps per (task, arm, lane) cell, median + spread reported. Proven
need: same edu fixture scored capture F1 1.0 on omen CPU (10-23) vs
0.889 on Colab T4 (10-24) — single-run cheap-lane scores are noise.

## 7. P5 feedback loop (the training flywheel)

Every run — bench or production — appends to the `cascade-outcomes`
log (mddb collection): `(task_id, family, features, lane_path,
gate_verdicts, cost, latency, final_pass)`. Consumers:

1. **Pattern miner** → new L0 codemod patterns. Leak-safe rule (hard):
   never mine benchmark-task commits; mine fix+test pairs from rich
   repos (terrology/mddb/mddb-fork — chaba/ada-voice history proved
   feature-dense, only 3 fix-class candidates).
2. **Router trainer** → weekly per-family classifier retrain (v1).
3. **JEV calibration** → noul/choice corpus grows from real verdicts.
4. **Verifier linter** → outcomes where every lane "fails" but produced
   real work flag verifier bias (the m1/m2 lesson — gate bugs masquerade
   as model failures).

## 8. Build phases

- **P0 done**: all components exist and are measured (codemod 7/7,
  o1 flash-lite 1.0, edu fixture + lanes, fable L3, jev services,
  LiteLLM proxy, kanban→lane adapter proven by eval-o1-opencode).
- **P1 harness**: `scripts/bench-cascade.py` — one driver over the 3
  families × 3 arms × N reps; emits `reports/bench-cascade-<date>.{json,md}`.
  Reuse: cascade-sim.py cost extension, agent-cost-bench surfaces
  (opencode/openhands), bench-edu-manage corpus, o1 verifier shape.
- **P2 outcome log + router v0** (deterministic rules above).
- **P3 patterns+classifier**: expand L0 library (mine mddb-fork), train
  v1 per-family entry predictors.
- **P4 JEV router**: real Jev Choice (needs key — decision-arena
  BEN-0826 is the selecting bench) + Noul pre-gates; arena-compare
  v1-classifier vs JEV-choice routing accuracy.
- **P5 productionize**: kanban→lane adapter is already proven
  (writer-seed script card → runner claims → agent+verifier → score in
  comms). Go-live governed by OPS-0823 delegation procedure + go-live
  matrix; L3 calls pass the spend gate (OR weekly cap was burned once —
  quota check is part of the router).

## 9. Honest limits / risks

- **Gates are the bottleneck, not models.** m1/m2: every frontier lane
  produced real correct Go edits and still "failed" — verifier coupled
  to original internals. Cascade cost is meaningless until verifiers
  are trustworthy. First build task = fix the dev family gates.
- **Escalation waste is the failure mode.** If cheap-lane pass
  probability is low, entering low just taxes the frontier call. The
  entry-level router (not a fixed ladder) is what makes the math work —
  and it needs the P5 outcome data to be calibrated.
- **Local lanes are latency-bound, not capability-bound** (edu: same
  model 13/13 on T4 at 15s vs 78s CPU). Use them for batch/async work;
  they are not an interactive lane.
- **Free-OR rotation is unreliable by design** — fine inside a cascade
  as a cheap attempt, never the only path to a gate.
- **Router overreach**: jev-student choice head is dead and noul does
  not generalize OOD (composer probes). Only real Jev or jevos-shortlist
  can do lane Choice today — v0/v1 routers don't depend on it.
- **Sequencing**: edu family is bench-ready today; dev family blocked
  on verifier fixes; chores blocked on writing o2-o4.
