# Dispatch outcome — arch: JEV router cheap-agent cascade (BEN-0811)

Card: `cheap-agent-cascade` · runner: tony-omen · branch:
`dispatch/20261024-165204-arch-task-jev-router-l0-codemo`

## What was produced

- **`docs/kb/cheap-agent-cascade.md`** — the full architecture design
  the card asked for: task → feature extract → **entry-level-prediction
  router** → L0 codemod / L1 cheap local (jev-student gates,
  hermes3:8b, qwen3:8b, gpt-oss:20b, OR :free rotation) / L2
  gemini-3.5-flash-lite / L3 frontier (fable-5.1, OR paid, Devin), with
  gate-verdict escalation. Key design decision: the router predicts
  WHERE to enter rather than always starting at the bottom — blind
  L0→L3 escalation on a hard task costs more than frontier-only.
- **`docs/ssot/jobs/bench/2026-10-24-cheap-agent-cascade-design.yml`** —
  durable job record (design summary, evidence base, build order).
- **Education lesson `cheap-agent-cascade`** — posted via board-api
  /lesson, upserted as post 2258 (`lesson-b41cf57e2899`), level deep.
- **Card comms** — start + completion posted on cheap-agent-cascade.

## The design in one paragraph

Primary metric is **cascade cost** (sum of every lane attempt along a
task's escalation path, router included), under the constraint that
arm pass-rate ≥ the frontier-only arm. Three arms: A frontier-only,
B cascade without patterns, C cascade with patterns (L0 + per-family
entry classifier trained on the P5 outcome log). Three families: dev
(t1/t2/m1/m2), chores (o1-o4), edu (bench-edu-manage.py fixture).
≥3 reps per cell — same fixture scored F1 1.0 (omen CPU) vs 0.889
(Colab T4), single runs are noise. Router ladder: v0 rules → v1 learned
classifier → v2 real-Jev Choice (jev-student proven decision-plane
only: noul in-domain, choice dead, no OOD).

## Findings / blockers surfaced

- **Verifier quality is the real bottleneck**, not model quality:
  m1/m2 held-out tests couple to original internals (every frontier
  lane produced real correct Go edits and still "failed"); t2 has no
  verifier at all. Dev family must get behavioral verifiers before the
  cascade bench is honest. Chores o2-o4 are unwritten.
- edu family is bench-ready today; local lanes are latency-bound not
  capability-bound (same model 15s T4 vs 78s CPU).

## How to verify

- `cat docs/kb/cheap-agent-cascade.md` — the design.
- Lesson: WP lesson post 2258 / topic cheap-agent-cascade in Education.
- Card comms on `cheap-agent-cascade` carry the summary + next steps.
- Commit `949d74928` on the dispatch branch (not pushed).
