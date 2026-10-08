# Chaba Nest — concept source: Neal Asher's Polity

Status: active guidance, 2026-10-08. Adopted by Tony as the conceptual
direction for Chaba Nest. Personal copy of the reading notes lives in
`devin-kb` (`docs/neal-asher-polity.md`).

## Attribution

Chaba Nest borrows its organizing ideas from **Neal Asher's Polity novel
series** (the "Polity universe" — Agent Cormac, Spatterjay, Transformation,
Rise of the Jain arcs). This is a deliberate, credit-where-due borrowing:
Asher worked out a coherent model of *hierarchical machine intelligence* and
we adopt his vocabulary and architecture intuitions as our compass. When we
say a Nest piece "is the EC persona pattern" we mean: the concept comes from
Asher; the implementation is ours.

Umbrella idea borrowed: the **AI hegemony** — a civilization run by a
hierarchy of minds (post-Quiet-War Polity). Nest is our small hegemony:
many narrow minds, coordinated, kept on leashes.

## What we borrow, and where it lives

| Asher concept | Nest implementation | Where |
|---|---|---|
| Earth Central / AI hegemony | Chaba orchestration layer; L0–L3 capability tiers | ada-pi `tests/bench/topologies.yml` |
| Lesser persona for a job | Dispatch sessions; L0 rules / L1 student specialists | `ssot.jobs`, dispatch pipeline |
| Tuned persona + telemetry leash | Shadow-deploy posture: a scorer observes & reports, never enforces until promoted; epoch fencing on brains | `ssot.nest-training.yml`, `ssot.nest-brains.yml` |
| Reprogram lesser minds at will | `nest-train-loop.py` train→bench→promote; promotion gated by a human-approved board request | `ssot.nest-training.yml` |
| Persona transported / respawned | Portable brains: versioned bundles, manifest, epoch fencing, `.nest-brain-state` lineage | `ssot.nest-brains.yml` |
| Compound intelligence (Penny Royal) | Collective-intelligence topologies: series/parallel/router/verifier cascades | card `nest-collective-bench`, `impl:chain` executor |
| Jain tech (corrupting supertech) | Adversarial bench tier; human-gated promotion is the anti-Jain safeguard | `tests/bench/suites.yml` |
| Runcible / U-space fabric | Tailnet + gdrive transport that makes the hegemony reachable | `ssot.nest-brains.yml` brain store |
| Black AI (rogue mind) | Split-brain respawn failure mode; fencing + manual respawn authority | `ssot.nest-brains.yml` policy_defaults |
| Haiman (human-AI symbiote) | Tony-in-the-gate: every promotion/deploy needs human approval; Tony+agent sessions | card promotion gates |

## One deliberate divergence

In the Polity, EC reprograms subminds unilaterally. In Nest, the loop may
train and bench a replacement candidate but **promotion is human-gated**
(board request → approval → shadow → promote). The parent mind proposes,
Tony disposes. That gate is the anti-Jain property — nothing external gets
to rewrite the minds unchecked.

## Where this direction points next

1. **Persona continuity** — dispatched personas start amnesiac today; brain
   `memory` blob role exists but is unused. "Submind returns with what it
   learned" is the gap: scoped memory slices that flow back to the parent.
2. **Arbiter-label pass** — open question in `ssot.nest-training.yml`:
   L2/L3 adjudicating diverged corpus rows = the greater mind correcting
   the lesser one's labels. Turns retrain-same-labels into
   learn-from-divergence.
3. **Learned router** — the hegemony's allocation decision, learned from
   bench corpus rather than a hand-set feature router.

## Where this doc is referenced

- Cards: `chaba-nest-models`, `nest-collective-bench`, `nest-portable-brains`,
  `nest-micro-training`
- SSOT: `ssot.nest-brains.yml`, `ssot.nest-training.yml`
- KB: `docs/kb/nest-portable-brains-research.md`
- Personal KB: `devin-kb` → `docs/neal-asher-polity.md` (book arcs + glossary)
